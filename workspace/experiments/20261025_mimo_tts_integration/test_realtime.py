"""Focused tests against the actual duplex manager, runner and playback ledger."""

import asyncio
import base64
import unittest
import numpy as np
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from vllm_omni.config.stage_config import DuplexSessionRuntimeConfig
from vllm_omni.engine.duplex.config import DuplexSessionConfig
from vllm_omni.engine.duplex.messages import (
    DuplexSessionCommandMessage, OpenDuplexSessionMessage,
)
from vllm_omni.engine.duplex.realtime_commands import translate_realtime_command
from vllm_omni.engine.duplex.session.manager import DuplexSessionManager

from realtime_backend import ExternalStagePort, MiMoTTSPlugin


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.hold = asyncio.Event()
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.slow = False
        self.fail = False

    async def run(self, rid, messages, voice, language, max_tokens, emit):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("Injected TTS failure.")
        await emit({"type": "text", "delta": "First. Second."})
        await emit({"type": "audio", "pcm": base64.b64encode(b"\x01\x00" * 2400).decode(),
                    "samples": 2400, "segment_id": 0})
        await emit({"type": "segment_done", "end": 6, "sample_end": 2400})
        self.started.set()
        try:
            if self.slow:
                await self.hold.wait()
            await emit({"type": "audio", "pcm": base64.b64encode(b"\x02\x00" * 2400).decode(),
                        "samples": 2400, "segment_id": 1})
            await emit({"type": "segment_done", "end": 14, "sample_end": 4800})
            await emit({"type": "done"})
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class RealtimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = FakeBackend()
        self.port = ExternalStagePort(self.backend)
        self.output = asyncio.Queue()
        self.results = asyncio.Queue()
        self.manager = DuplexSessionManager(
            plugin=MiMoTTSPlugin(), stage_port=self.port,
            output_sink=self.output, result_sink=self.results,
            runtime_config=DuplexSessionRuntimeConfig(), model_config=None,
        )
        self.port.manager = self.manager
        config = DuplexSessionConfig.from_realtime({
            "model": "mimo-v2.6-flash",
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                               "turn_detection": None}},
        })
        await self.manager.handle(OpenDuplexSessionMessage(
            control_id="open", session_id="test", session_config=config))
        self.assertTrue(self.results.get_nowait().ok)
        self.runner = self.manager.runners["test"]
        self.events = []
        await self.wait_type("session.updated")

    async def asyncTearDown(self):
        await self.port.shutdown()
        await self.manager.shutdown()

    def send(self, payload):
        self.manager.dispatch(DuplexSessionCommandMessage(
            session_id="test", command=translate_realtime_command(payload)))

    async def wait_type(self, kind):
        async with asyncio.timeout(5):
            while True:
                event = (await self.output.get()).event.to_realtime()
                self.events.append(event)
                if event["type"] == kind:
                    return event
                if event["type"] == "error" and kind != "error":
                    self.fail(str(event))

    async def text(self, value="Answer briefly."):
        self.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": value}],
        }})
        self.send({"type": "response.create"})

    async def test_runner_text_audio_ack_history(self):
        await self.text()
        done = await self.wait_type("response.done")
        rid = done["response"]["id"]
        audio = [event for event in self.events if event["type"] == "response.output_audio.delta"]
        self.assertEqual(len(audio), 2)
        self.assertFalse(any(message["role"] == "assistant"
                             for message in self.runner.session.history))
        self.send({"type": "playback.ack", "response_id": rid, "played_ms": 200,
                   "committed_ms": 200})
        await self.wait_type("playback.acknowledged")
        self.assertEqual(self.runner.session.history[-1]["content"], "First. Second.")
        await self.text("Remember previous turn.")
        await self.wait_type("response.done")
        self.assertTrue(any(message.get("content") == "First. Second."
                            for message in self.backend.calls[-1]))

    async def test_cancel_prefix_stale_and_recovery(self):
        self.backend.slow = True
        await self.text()
        audio = await self.wait_type("response.output_audio.delta")
        old_rid = audio["response_id"]
        old_context = next(iter(self.port.contexts.values()))
        self.send({"type": "playback.ack", "response_id": old_rid,
                   "played_ms": 100, "committed_ms": 100})
        await self.wait_type("playback.acknowledged")
        self.send({"type": "response.cancel", "response_id": old_rid})
        await self.wait_type("response.done")
        await asyncio.wait_for(self.backend.cancelled.wait(), 5)
        self.assertFalse(self.port.tasks)
        self.assertEqual(self.runner.session.history[-1]["content"], "First.")
        self.backend.slow = False
        await self.text("Recover.")
        done = await self.wait_type("response.done")
        self.assertNotEqual(done["response"]["id"], old_rid)
        from types import SimpleNamespace
        before = self.output.qsize()
        self.port._output(SimpleNamespace(context=old_context), {"text": "STALE"})
        await asyncio.sleep(.01)
        self.assertEqual(self.output.qsize(), before)

    async def test_real_runner_vad_auto_commit(self):
        self.send({"type": "session.update", "session": {
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                               "turn_detection": {"type": "server_vad"}}},
        }})
        await self.wait_type("session.updated")
        self.assertIsNotNone(self.runner.control._detector)
        vad = self.runner.control._detector.vad
        vad._frame_scorer = lambda frame: .95 if np.max(np.abs(frame)) > .1 else .0
        for samples in [np.ones(4800, dtype="<i2") * 12000,
                        np.zeros(14400, dtype="<i2")]:
            self.send({"type": "input_audio_buffer.append",
                       "format": "pcm16", "sample_rate_hz": 24000,
                       "audio": base64.b64encode(samples.tobytes()).decode()})
        await self.wait_type("response.done")
        kinds = [event["type"] for event in self.events]
        self.assertIn("input_audio_buffer.speech_started", kinds)
        self.assertIn("input_audio_buffer.speech_stopped", kinds)
        self.assertIn("input_audio_buffer.committed", kinds)
        self.assertTrue(any(part.get("type") == "input_audio"
                            for message in self.backend.calls[-1]
                            if isinstance(message.get("content"), list)
                            for part in message["content"]))

    async def test_pipeline_failure_terminal(self):
        self.backend.fail = True
        await self.text()
        await self.wait_type("error")
        done = await self.wait_type("response.done")
        self.assertEqual(done["response"]["status"], "failed")
        await asyncio.sleep(.1)
        self.assertFalse(self.port.tasks)
        self.backend.fail = False
        await self.text("Retry.")
        await self.wait_type("response.done")

    async def test_unheard_text_then_voice_preserves_order(self):
        self.backend.slow = True
        await self.text("Old unanswered city question.")
        first = await self.wait_type("response.output_audio.delta")
        self.send({"type": "response.cancel", "response_id": first["response_id"]})
        await self.wait_type("response.done")
        await asyncio.wait_for(self.backend.cancelled.wait(), 5)
        self.backend.slow = False
        self.send({"type": "input_audio_buffer.append",
                   "format": "pcm16", "sample_rate_hz": 24000,
                   "audio": base64.b64encode(
                       (np.ones(4800, dtype="<i2") * 12000).tobytes()).decode()})
        self.send({"type": "input_audio_buffer.commit"})
        await self.wait_type("input_audio_buffer.committed")
        self.send({"type": "response.create"})
        await self.wait_type("response.done")
        messages = self.backend.calls[-1]
        parts = messages[-1]["content"]
        self.assertEqual(parts[0]["text"], "Old unanswered city question.")
        self.assertEqual(parts[1]["type"], "input_audio")
        self.assertIn("do not transcribe", parts[2]["text"])
        self.assertFalse(any(message["role"] == "assistant" for message in messages))


class HostTests(unittest.IsolatedAsyncioTestCase):
    async def test_frontend_admission_close_and_reconnect(self):
        from realtime_server import create_app
        from vllm_omni.engine.duplex.vad import SileroVADBackendProvider
        app = create_app()
        app.cleanup_ctx.clear()
        app["backend"] = FakeBackend()
        app["vad_provider"] = SileroVADBackendProvider()
        async with TestServer(app) as server:
            async with ClientSession(trust_env=False) as client:
                async with client.get(server.make_url("/")) as response:
                    html = await response.text()
                    self.assertIn('"profile": "mimo-tts"', html)
                    self.assertLess(html.index("/mimo_profile.js"), html.index('src="static/app.js'))
                    self.assertNotIn("__FULL_DUPLEX_CONFIG__", html)
                session = {"type": "session.update", "session": {
                    "model": "mimo-v2.6-flash",
                    "audio": {"input": {"turn_detection": None}},
                }}
                async def ready(ws):
                    async with asyncio.timeout(5):
                        while (await ws.receive_json())["type"] != "session.updated":
                            pass
                first = await client.ws_connect(server.make_url("/v1/realtime"))
                await first.send_json({"type": "input_audio_buffer.append", "audio": "AA=="})
                self.assertEqual((await first.receive_json())["type"], "error")
                await first.send_json(session)
                await ready(first)
                second = await client.ws_connect(server.make_url("/v1/realtime"))
                await second.send_json(session)
                denied = await second.receive_json()
                self.assertEqual(denied["error"]["code"], "resource_exhausted")
                await second.close()
                await first.send_json({"type": "session.close"})
                async with asyncio.timeout(5):
                    while (await first.receive_json())["type"] != "session.closed":
                        pass
                await first.close()
                async with asyncio.timeout(5):
                    while app["active_sessions"]:
                        await asyncio.sleep(.01)
                third = await client.ws_connect(server.make_url("/v1/realtime"))
                await third.send_json(session)
                await ready(third)
                await third.close()
                async with asyncio.timeout(5):
                    while app["connections"]:
                        await asyncio.sleep(.01)
                self.assertFalse(app["active_sessions"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
