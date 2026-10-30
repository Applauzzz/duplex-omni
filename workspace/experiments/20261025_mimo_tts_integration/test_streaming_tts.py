"""Contract tests for true incremental-text CosyVoice submit/poll sessions."""

import asyncio
import json
import unittest

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from streaming_tts import IncrementalTextChunker, WeChatStreamingTTSProvider


def poll_body(meta, pcm=b""):
    encoded = json.dumps(meta).encode()
    return encoded if not pcm else encoded + b"\0" + pcm


class ChunkerTests(unittest.TestCase):
    def test_emits_at_punctuation_before_reply_completion(self):
        chunker = IncrementalTextChunker(min_chars=4, max_chars=12)
        self.assertEqual(chunker.feed("你好，这是"), [])
        self.assertEqual(chunker.feed("第一句。后面"), ["你好，这是第一句。"])
        self.assertEqual(chunker.flush(), ["后面"])

    def test_hard_limit_prevents_unbounded_wait(self):
        chunker = IncrementalTextChunker(min_chars=4, max_chars=8)
        self.assertEqual(chunker.feed("一二三四五六七八九"), ["一二三四五六七八"])
        self.assertEqual(chunker.flush(), ["九"])


class StreamingTTSTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.submits = []
        self.polls = []
        self.poll_index = 0

        async def submit(request):
            self.submits.append(await request.json())
            return web.json_response({"ret": 0, "message": ""})

        async def poll(request):
            self.polls.append(await request.json())
            responses = [
                poll_body({
                    "ret": 0, "speech_idx": -1, "sample_rate": 24000,
                    "is_complete": False, "message": "",
                }),
                poll_body({
                    "ret": 0, "speech_idx": 0, "sample_rate": 24000,
                    "is_complete": False, "message": "",
                }, b"\x01\x00"),
                poll_body({
                    "ret": 0, "speech_idx": 1, "sample_rate": 24000,
                    "is_complete": True, "message": "",
                }, b"\x02\x00"),
            ]
            body = responses[min(self.poll_index, len(responses) - 1)]
            self.poll_index += 1
            return web.Response(body=body, content_type="application/octet-stream")

        app = web.Application()
        app.router.add_post("/submit", submit)
        app.router.add_post("/poll", poll)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = ClientSession(trust_env=False)

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_reuses_one_task_for_ordered_text_chunks_and_empty_final(self):
        provider = WeChatStreamingTTSProvider(self.client, str(self.server.make_url("/")))
        session = provider.create_stream(
            reg_id="test_voice", speed=1.2, target_rms=-24,
            context={"request_id": "request-1"},
        )
        await session.submit_text("第一段，")
        poll_task = asyncio.create_task(self._collect(session))
        await session.submit_text("第二段。")
        await session.finish()
        chunks = await poll_task
        self.assertEqual(b"".join(item.pcm for item in chunks), b"\x01\x00\x02\x00")
        self.assertTrue(all(item.request_id == session.task_id for item in chunks))
        self.assertEqual([(item["text_idx"], item["text"], item["is_text_complete"])
                          for item in self.submits], [
            (0, "第一段，", False),
            (1, "第二段。", False),
            (2, "", True),
        ])
        self.assertTrue(all(item["task_id"] == session.task_id for item in self.submits))
        self.assertTrue(all(item["tts_strategy"] == "EagerTTSStrategy"
                            for item in self.submits))

    async def test_finish_without_text_produces_empty_upstream_error(self):
        async def submit(_request):
            return web.json_response({"ret": 0, "message": ""})

        async def poll(_request):
            return web.Response(body=poll_body({
                "ret": 0, "sample_rate": 24000, "is_complete": True,
            }))

        app = web.Application()
        app.router.add_post("/submit", submit)
        app.router.add_post("/poll", poll)
        server = TestServer(app)
        await server.start_server()
        try:
            provider = WeChatStreamingTTSProvider(self.client, str(server.make_url("/")))
            session = provider.create_stream(
                reg_id="test_voice", speed=1.0, target_rms=-25, context={})
            await session.finish()
            with self.assertRaisesRegex(RuntimeError, "empty PCM"):
                _ = [item async for item in session.stream_pcm()]
        finally:
            await server.close()

    async def test_rejects_odd_poll_pcm(self):
        async def submit(_request):
            return web.json_response({"ret": 0, "message": ""})

        async def poll(_request):
            return web.Response(body=poll_body({
                "ret": 0, "sample_rate": 24000, "is_complete": True,
            }, b"\x01"))

        app = web.Application()
        app.router.add_post("/submit", submit)
        app.router.add_post("/poll", poll)
        server = TestServer(app)
        await server.start_server()
        try:
            provider = WeChatStreamingTTSProvider(self.client, str(server.make_url("/")))
            session = provider.create_stream(
                reg_id="test_voice", speed=1.0, target_rms=-25, context={})
            await session.submit_text("测试", final=True)
            with self.assertRaisesRegex(RuntimeError, "incomplete PCM16"):
                _ = [item async for item in session.stream_pcm()]
        finally:
            await server.close()

    async def test_submit_failure_includes_upstream_status(self):
        async def unavailable(_request):
            return web.json_response({"error": "offline"}, status=503)

        app = web.Application()
        app.router.add_post("/submit", unavailable)
        server = TestServer(app)
        await server.start_server()
        try:
            provider = WeChatStreamingTTSProvider(self.client, str(server.make_url("/")))
            session = provider.create_stream(
                reg_id="test_voice", speed=1.0, target_rms=-25, context={})
            with self.assertRaisesRegex(RuntimeError, "TTS submit HTTP 503"):
                await session.submit_text("测试")
        finally:
            await server.close()

    @staticmethod
    async def _collect(session):
        return [item async for item in session.stream_pcm()]


if __name__ == "__main__":
    unittest.main(verbosity=2)
