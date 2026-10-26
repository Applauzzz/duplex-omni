"""Focused protocol tests; no inference-stack/CPU regression dependency."""

import asyncio
import base64
import io
import json
import unittest
import wave

from aiohttp import ClientSession, ClientTimeout, web

from backend import Backend, ContentGuard, PipelineError, SpannedSplitter, validate_request
from server import create_app


async def serve(app):
    runner = web.AppRunner(app, handler_cancellation=True)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


class Contracts(unittest.TestCase):
    def test_exact_spans_and_numbers(self):
        splitter = SpannedSplitter()
        text = "Dr. Smith paid 3.14 dollars. \u4f60\u597d\uff01 \u518d\u89c1\u3002"
        segments = []
        for char in text:
            segments += splitter.feed(char)
        segments += splitter.flush()
        self.assertEqual(len(segments), 3)
        for item in segments:
            self.assertEqual(text[item.start:item.end], item.text)
        self.assertEqual([x.text for x in segments], [
            "Dr. Smith paid 3.14 dollars.", "\u4f60\u597d\uff01", "\u518d\u89c1\u3002"
        ])

    def test_long_reply_budget(self):
        splitter = SpannedSplitter()
        segments = splitter.feed("a" * 1000) + splitter.flush()
        self.assertTrue(all(len(x.text) <= 320 for x in segments))
        self.assertEqual("".join(x.text for x in segments), "a" * 1000)
        with self.assertRaises(PipelineError):
            splitter.feed("b" * 4096)

    def test_control_prefix(self):
        guard = ContentGuard()
        self.assertEqual(guard.feed("Hello <thi"), "Hello ")
        with self.assertRaises(PipelineError):
            guard.feed("nk>secret")

    def test_history_and_audio_validation(self):
        _, _, _, tokens = validate_request({"input": "hello"})
        self.assertEqual(tokens, 512)
        for bad in ([], {"input": ""}, {"input": "x", "history": [{"role": "assistant", "input": "x"}]},
                    {"input": "x", "max_tokens": True}, {"audio": {"format": "wav", "data": "bad!"}}):
            with self.assertRaises(ValueError):
                validate_request(bad)
        recording = io.BytesIO()
        with wave.open(recording, "wb") as output:
            output.setparams((1, 2, 24000, 0, "NONE", ""))
            output.writeframes(b"\0\0" * 2400)
        messages, *_ = validate_request({"audio": {
            "format": "wav", "data": base64.b64encode(recording.getvalue()).decode()
        }})
        self.assertEqual(messages[-1]["content"][0]["type"], "input_audio")


class Protocol(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.closed = []

        async def mimo(request):
            body = await request.json()
            mode = body["messages"][-1]["content"]
            self.requests.append(("mimo", mode))
            response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await response.prepare(request)
            async def send(delta, reason=None):
                event = {"choices": [{"delta": delta, "finish_reason": reason}]}
                data = ("data: " + json.dumps(event) + "\n\n").encode()
                for i in range(0, len(data), 7):
                    await response.write(data[i:i + 7])
            try:
                await send({"reasoning_content": "DO NOT SPEAK"})
                await send({"content": "First sentence. "})
                if mode == "slow":
                    await asyncio.sleep(.12)
                elif mode == "cancel":
                    await asyncio.sleep(60)
                elif mode == "truncate":
                    await response.write_eof()
                    return response
                elif mode == "tool":
                    await send({"tool_calls": [{"id": "tool"}]})
                    return response
                elif mode == "queue":
                    await send({"content": "More text. " * 25})
                await send({"content": "Second sentence."})
                await send({}, "stop")
                await response.write(b"data: [DONE]\n\n")
                await response.write_eof()
                return response
            finally:
                self.closed.append("mimo")

        async def tts(request):
            body = await request.json()
            self.requests.append(("tts", body["input"]))
            if body["voice"] == "serena":
                return web.Response(status=503)
            response = web.StreamResponse(headers={"Content-Type": "audio/pcm"})
            await response.prepare(request)
            try:
                await response.write(b"\0\x10" * 960)
                if body["voice"] == "ryan":
                    await response.write(b"\0")
                    return response
                await asyncio.sleep(.03)
                await response.write(b"\0\x10" * 960)
                await response.write_eof()
                return response
            finally:
                self.closed.append("tts")
        app = web.Application()
        app.router.add_post("/v1/chat/completions", mimo)
        app.router.add_post("/v1/audio/speech", tts)
        self.upstream, self.url = await serve(app)
        self.client = ClientSession(trust_env=False, timeout=ClientTimeout(total=5))
        self.backend = Backend(self.client, self.url, self.url)
        self.app = create_app(self.url, self.url)
        self.runner, self.app_url = await serve(self.app)

    async def asyncTearDown(self):
        await self.runner.cleanup()
        await self.client.close()
        await self.upstream.cleanup()

    async def run_backend(self, mode, voice="vivian"):
        events = []
        async def emit(event):
            events.append(event)
        messages = [{"role": "user", "content": mode}]
        await self.backend.run("test", messages, voice, "English", 512, emit)
        return events

    async def test_slow_sse_audio_before_done(self):
        events = await self.run_backend("slow")
        types = [e["type"] for e in events]
        self.assertLess(types.index("audio"), types.index("model_done"))
        self.assertEqual(events[-1]["type"], "done")
        text = "".join(e["delta"] for e in events if e["type"] == "text")
        self.assertNotIn("DO NOT SPEAK", text)
        self.assertEqual(text, "First sentence. Second sentence.")
        segments = [e for e in events if e["type"] == "segment"]
        tts_inputs = [text for role, text in self.requests if role == "tts"]
        self.assertEqual(tts_inputs, [s["text"] for s in segments])
        for segment in segments:
            self.assertEqual(text[segment["start"]:segment["end"]], segment["text"])

    async def test_bounded_queue(self):
        events = await self.run_backend("queue")
        self.assertEqual(events[-1]["max_queue"], 4)
        self.assertLessEqual(events[-1]["max_queue"], 4)
        indices = [e["segment_id"] for e in events if e["type"] == "segment_done"]
        self.assertEqual(indices, list(range(len(indices))))

    async def test_truncated_and_tools_fail(self):
        for mode in ("truncate", "tool"):
            with self.assertRaises(PipelineError):
                await self.run_backend(mode)

    async def test_tts_error_cancels_mimo(self):
        with self.assertRaises(PipelineError):
            await self.run_backend("cancel", "serena")
        await asyncio.sleep(.05)
        self.assertIn("mimo", self.closed)

    async def test_incomplete_pcm_is_error(self):
        with self.assertRaises(PipelineError):
            await self.run_backend("slow", "ryan")

    async def test_disconnect_cleanup_and_recovery(self):
        async with self.client.post(self.app_url + "/api/chat", json={"input": "cancel"}) as response:
            self.assertEqual(response.status, 200)
            async for line in response.content:
                if json.loads(line)["type"] == "audio":
                    response.close()
                    break
        for _ in range(50):
            if self.app["outcomes"][-1]["status"] != "running":
                break
            await asyncio.sleep(.02)
        self.assertIn(self.app["outcomes"][-1]["status"], ("cancelled", "disconnected"))
        self.assertIn("mimo", self.closed)
        async with self.client.post(self.app_url + "/api/chat", json={"input": "slow"}) as response:
            events = [json.loads(line) async for line in response.content]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(len({e["response_id"] for e in events}), 1)

    async def test_admission_and_invalid_requests(self):
        await self.app["gate"].acquire()
        await self.app["gate"].acquire()
        try:
            async with self.client.post(self.app_url + "/api/chat", json={"input": "x"}) as response:
                self.assertEqual(response.status, 429)
        finally:
            self.app["gate"].release()
            self.app["gate"].release()
        for body in ([], {}, {"input": "a" * 4097}):
            async with self.client.post(self.app_url + "/api/chat", json=body) as response:
                self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
