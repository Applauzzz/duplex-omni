"""Protocol tests for the standalone semantic VAD visualization service."""

import base64
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from semantic_vad import (
    DEFAULT_CHAT_PROMPT,
    DEFAULT_VAED_PROMPT,
    DEFAULT_VASD_PROMPT,
    InvalidSemanticCommand,
    SemanticRealtimeAdapter,
    VAEDDecision,
    VASDDecision,
)
from svad_debug_server import create_app


class Provider:
    async def decide_break(self, audio_chunks, *, context):
        return VASDDecision(
            True, raw_output="A", command="<b>",
            logprobs={"<b>": -.1, "</b>": -2.1},
            probability=.844, margin=2.0,
        )

    async def decide_complete(self, audio_chunks, *, context):
        return VAEDDecision(
            True, raw_output="A", command="<c>",
            logprobs={"<c>": -.1, "</c>": -2.1},
            probability=.95, margin=3.0,
        )

class VAD:
    def process_base64(self, *_args, **_kwargs):
        return SimpleNamespace(
            is_speech=True,
            speech_active=True,
            speech_started=False,
            speech_stopped=False,
            speech_probability=.91,
        )

    def reset(self):
        pass


class ChatProvider:
    def __init__(self):
        self.calls = []

    async def stream_reply(self, audio_chunks, *, history, prompt, context):
        self.calls.append({
            "audio_chunks": tuple(audio_chunks),
            "history": list(history),
            "prompt": prompt,
            "context": dict(context),
        })
        yield "你好，"
        yield "这是测试回复。"


class BlockingChatProvider:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.hold = asyncio.Event()

    async def stream_reply(self, audio_chunks, *, history, prompt, context):
        self.started.set()
        try:
            yield "尚未完成"
            await self.hold.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class DebugServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "svad_config.json"
        self.settings = {
            "_说明": {"threshold": "测试注释字段，服务应忽略"},
            "config": {
                "audio_chunk_ms": 500,
                "threshold": .5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "min_speech_duration_ms": 96,
                "max_buffered_chunks": 512,
                "vasd_window_ms": 8000,
                "break_probability_threshold": .8,
                "break_margin_threshold": 1.5,
                "break_confirmations": 1,
                "complete_probability_threshold": .9,
                "complete_margin_threshold": 2.0,
                "complete_confirmations": 1,
                "incomplete_silence_timeout_ms": 8000,
            },
            "prompts": {
                "vasd_prompt": DEFAULT_VASD_PROMPT,
                "vaed_prompt": DEFAULT_VAED_PROMPT,
                "chat_prompt": DEFAULT_CHAT_PROMPT,
            },
        }
        self.config_path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
        self.app = create_app(mimo_url="http://unused", config_path=self.config_path)
        self.app.cleanup_ctx.clear()
        self.app["semantic_provider"] = Provider()
        self.chat = ChatProvider()
        self.app["chat_provider"] = self.chat
        self.app["vad_provider"] = None
        self.app["adapter_factory"] = lambda config, provider, **_kwargs: (
            SemanticRealtimeAdapter(config, provider, vad=VAD())
        )
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = ClientSession(trust_env=False)

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temp_dir.cleanup()

    async def test_page_and_capture_worklet(self):
        async with self.client.get(self.server.make_url("/")) as response:
            html = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn("MiMo Semantic VAD Console", html)
        self.assertIn("Persistent state timeline", html)
        for state in ("Silence", "Judge", "Listen"):
            self.assertIn(f'data-state="{state}"', html)
        for token in ("&lt;s&gt;", "&lt;/s&gt;", "&lt;b&gt;", "&lt;/b&gt;", "&lt;c&gt;", "&lt;/c&gt;"):
            self.assertIn(token, html)
        self.assertIn("if(last.state!==t.next_state)", html)
        self.assertIn("const meaningful=t.previous_state!==t.next_state", html)
        self.assertIn("全部设置", html)
        self.assertIn('id="applySettings"', html)
        self.assertIn('id="maxChunks"', html)
        self.assertIn('id="breakProbability"', html)
        self.assertIn('id="breakMargin"', html)
        self.assertIn('id="breakConfirmations"', html)
        self.assertIn('audioChunkMs', html)
        self.assertIn('now-lastFlushAt<target', html)
        self.assertIn("对话", html)
        async with self.client.get(self.server.make_url("/defaults")) as response:
            defaults = await response.json()
        self.assertEqual(defaults["config"]["max_buffered_chunks"], 512)
        self.assertEqual(defaults["config"]["audio_chunk_ms"], 500)
        self.assertEqual(defaults["prompts"]["vasd_prompt"], DEFAULT_VASD_PROMPT)
        self.assertEqual(defaults["prompts"]["vaed_prompt"], DEFAULT_VAED_PROMPT)
        self.assertEqual(defaults["prompts"]["chat_prompt"], DEFAULT_CHAT_PROMPT)
        self.assertEqual(defaults["source"], str(self.config_path))
        async with self.client.get(self.server.make_url("/capture_worklet.js")) as response:
            worklet = await response.text()
        self.assertEqual(response.status, 200)
        self.assertIn("fullduplex-pcm-capture", worklet)

    async def test_defaults_reread_local_file_on_every_refresh(self):
        async with self.client.get(self.server.make_url("/defaults")) as response:
            before = await response.json()
        self.settings["config"]["threshold"] = .7
        self.settings["prompts"]["chat_prompt"] = "刷新后生效的本地 Chat Prompt"
        self.config_path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
        async with self.client.get(self.server.make_url("/defaults")) as response:
            after = await response.json()
        self.assertEqual(before["config"]["threshold"], .5)
        self.assertEqual(after["config"]["threshold"], .7)
        self.assertEqual(after["prompts"]["chat_prompt"], "刷新后生效的本地 Chat Prompt")

    async def test_invalid_local_file_returns_explicit_error(self):
        self.config_path.write_text("{broken", encoding="utf-8")
        async with self.client.get(self.server.make_url("/defaults")) as response:
            payload = await response.json()
        self.assertEqual(response.status, 500)
        self.assertIn("Invalid SVAD config JSON", payload["error"])

    async def test_configure_transitions_and_reset(self):
        class EndpointVAD:
            def __init__(self):
                self.values = iter((True, True, False))
                self.last_active = False

            def process_base64(self, *_args, **_kwargs):
                active = next(self.values)
                stopped = not active and self.last_active
                self.last_active = active
                return SimpleNamespace(
                    is_speech=active,
                    speech_active=active,
                    speech_started=False,
                    speech_stopped=stopped,
                    speech_probability=.91 if active else .0,
                )

            def reset(self):
                pass

        self.app["adapter_factory"] = lambda config, provider, **_kwargs: (
            SemanticRealtimeAdapter(config, provider, vad=EndpointVAD())
        )
        async with asyncio.timeout(5):
            ws = await self.client.ws_connect(self.server.make_url("/ws"))
            await ws.send_json({
                "type": "configure",
                "threshold": .5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": 500,
                "min_speech_duration_ms": 32,
                "complete_confirmations": 1,
            })
            configured = await ws.receive_json()
            self.assertEqual(configured["type"], "configured")
            self.assertEqual(configured["prompts"]["chat_prompt"], DEFAULT_CHAT_PROMPT)
            self.assertEqual(configured["config"]["max_buffered_chunks"], 512)
            self.assertEqual(configured["config"]["audio_chunk_ms"], 500)
            self.assertEqual(configured["config"]["break_probability_threshold"], .8)
            audio_payloads = []
            for amplitude in (10000, 12000, 14000):
                pcm = base64.b64encode(
                    (np.ones(512, dtype="<i2") * amplitude).tobytes()
                ).decode()
                audio_payloads.append({
                    "type": "audio",
                    "audio": pcm,
                    "format": "pcm16",
                    "sample_rate_hz": 16000,
                })
            for expected_state, payload in zip(("Listen", "Listen", "Silence"), audio_payloads):
                await ws.send_json(payload)
                event = await ws.receive_json()
                self.assertEqual(event["type"], "transition")
                self.assertEqual(event["transition"]["next_state"], expected_state)
                expected_probability = .0 if expected_state == "Silence" else .91
                self.assertEqual(event["avad"]["speech_probability"], expected_probability)
                if event["transition"]["request_kind"] is not None:
                    self.assertTrue(event["transition"]["semantic_valid"])
                    self.assertEqual(event["transition"]["model_output"], "A")
                    self.assertGreater(event["transition"]["semantic_probability"], .8)
                    expected_margin = 2.0 if event["transition"]["request_kind"] == "VASD" else 3.0
                    self.assertEqual(event["transition"]["semantic_margin"], expected_margin)
            started = await ws.receive_json()
            self.assertEqual(started["type"], "chat.started")
            delta1 = await ws.receive_json()
            delta2 = await ws.receive_json()
            done = await ws.receive_json()
            self.assertEqual([delta1["type"], delta2["type"], done["type"]], [
                "chat.delta", "chat.delta", "chat.done",
            ])
            self.assertEqual(done["text"], "你好，这是测试回复。")
            self.assertEqual(self.chat.calls[0]["prompt"], DEFAULT_CHAT_PROMPT)
            self.assertEqual(self.chat.calls[0]["audio_chunks"], tuple(
                {
                    "type": "input_audio_buffer.append",
                    "audio": payload["audio"],
                    "format": "pcm16",
                    "sample_rate_hz": 16000,
                }
                for payload in audio_payloads
            ))
            await ws.send_json({"type": "reset"})
            self.assertEqual((await ws.receive_json())["type"], "reset")
            await ws.close()

    async def test_reconfigure_rebuilds_all_settings_and_prompts(self):
        ws = await self.client.ws_connect(self.server.make_url("/ws"))
        await ws.send_json({"type": "configure", "min_speech_duration_ms": 32})
        self.assertEqual((await ws.receive_json())["type"], "configured")
        await ws.send_json({
            "type": "configure",
            "audio_chunk_ms": 750,
            "threshold": .65,
            "prefix_padding_ms": 450,
            "silence_duration_ms": 900,
            "min_speech_duration_ms": 64,
            "max_buffered_chunks": 768,
            "vasd_window_ms": 6000,
            "break_probability_threshold": .75,
            "break_margin_threshold": 1.25,
            "break_confirmations": 2,
            "complete_probability_threshold": .85,
            "complete_margin_threshold": 1.5,
            "complete_confirmations": 2,
            "incomplete_silence_timeout_ms": 12000,
            "vasd_prompt": "中文 VASD all in one",
            "vaed_prompt": "中文 VAED all in one",
            "chat_prompt": "中文 Chat all in one",
        })
        configured = await ws.receive_json()
        self.assertEqual(configured["type"], "configured")
        self.assertEqual(configured["config"], {
            "audio_chunk_ms": 750,
            "threshold": .65,
            "prefix_padding_ms": 450,
            "silence_duration_ms": 900,
            "min_speech_duration_ms": 64,
            "max_buffered_chunks": 768,
            "vasd_window_ms": 6000,
            "break_probability_threshold": .75,
            "break_margin_threshold": 1.25,
            "break_confirmations": 2,
            "complete_probability_threshold": .85,
            "complete_margin_threshold": 1.5,
            "complete_confirmations": 2,
            "incomplete_silence_timeout_ms": 12000,
        })
        self.assertEqual(configured["prompts"]["chat_prompt"], "中文 Chat all in one")
        await ws.close()

    async def test_invalid_audio_chunk_interval_is_rejected(self):
        self.settings["config"]["audio_chunk_ms"] = 10
        self.config_path.write_text(json.dumps(self.settings, ensure_ascii=False), encoding="utf-8")
        async with self.client.get(self.server.make_url("/defaults")) as response:
            payload = await response.json()
        self.assertEqual(response.status, 500)
        self.assertIn("audio_chunk_ms must be within [50, 5000]", payload["error"])

    async def test_prompts_update_applies_to_following_requests(self):
        ws = await self.client.ws_connect(self.server.make_url("/ws"))
        await ws.send_json({
            "type": "configure",
            "min_speech_duration_ms": 32,
            "vasd_prompt": "中文 VASD 初始",
            "vaed_prompt": "中文 VAED 初始",
            "chat_prompt": "中文 Chat 初始",
        })
        configured = await ws.receive_json()
        self.assertEqual(configured["prompts"]["vasd_prompt"], "中文 VASD 初始")
        await ws.send_json({
            "type": "prompts.update",
            "vasd_prompt": "中文 VASD 更新",
            "vaed_prompt": "中文 VAED 更新",
            "chat_prompt": "中文 Chat 更新",
        })
        updated = await ws.receive_json()
        self.assertEqual(updated["prompts"]["chat_prompt"], "中文 Chat 更新")
        await ws.close()

    async def test_effective_break_cancels_active_chat(self):
        class ScriptedProvider:
            def __init__(self):
                self.breaks = 0

            async def decide_break(self, audio_chunks, *, context):
                self.breaks += 1
                return VASDDecision(
                    True, raw_output="A", command="<b>",
                    logprobs={"<b>": -.1, "</b>": -2.1},
                    probability=.9, margin=2.0,
                )

            async def decide_complete(self, audio_chunks, *, context):
                return VAEDDecision(
                    True, raw_output="A", command="<c>",
                    logprobs={"<c>": -.1, "</c>": -2.1},
                    probability=.9, margin=2.0,
                )

        blocking = BlockingChatProvider()
        self.app["semantic_provider"] = ScriptedProvider()
        self.app["chat_provider"] = blocking
        class ReleaseVAD:
            def __init__(self):
                self.values = iter((True, True, False, True, True))
                self.last_active = False

            def process_base64(self, *_args, **_kwargs):
                value = next(self.values)
                stopped = not value and self.last_active
                self.last_active = value
                return SimpleNamespace(
                    is_speech=value,
                    speech_active=value,
                    speech_started=False,
                    speech_stopped=stopped,
                    speech_probability=.91 if value else .0,
                )

            def reset(self):
                pass

        self.app["adapter_factory"] = lambda config, provider, **_kwargs: (
            SemanticRealtimeAdapter(config, provider, vad=ReleaseVAD())
        )
        async with asyncio.timeout(5):
            ws = await self.client.ws_connect(self.server.make_url("/ws"))
            await ws.send_json({
                "type": "configure",
                "min_speech_duration_ms": 32,
                "complete_confirmations": 1,
            })
            await ws.receive_json()
            pcm = base64.b64encode((np.ones(512, dtype="<i2") * 12000).tobytes()).decode()
            payload = {"type": "audio", "audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}
            for _ in range(3):
                await ws.send_json(payload)
                self.assertEqual((await ws.receive_json())["type"], "transition")
            self.assertEqual((await ws.receive_json())["type"], "chat.started")
            self.assertEqual((await ws.receive_json())["type"], "chat.delta")
            await asyncio.wait_for(blocking.started.wait(), 1)
            # The first inactive block already completed the prior turn. Start a new one.
            await ws.send_json(payload)
            cancelled = await ws.receive_json()
            transition = await ws.receive_json()
            self.assertEqual(cancelled["type"], "chat.cancelled")
            self.assertEqual(cancelled["reason"], "semantic_break")
            self.assertEqual(transition["type"], "transition")
            self.assertEqual(transition["transition"]["fsm_event"], "PREFILL")
            await asyncio.wait_for(blocking.cancelled.wait(), 1)
            await ws.close()

    async def test_invalid_model_command_is_visible_and_session_stays_open(self):
        class InvalidProvider:
            async def decide_break(self, audio_chunks, *, context):
                raise InvalidSemanticCommand("VASD", "需要。", ("需要", "不需要"))

            async def decide_complete(self, audio_chunks, *, context):
                return VAEDDecision(True, raw_output="<c>", command="<c>")

        self.app["semantic_provider"] = InvalidProvider()
        ws = await self.client.ws_connect(self.server.make_url("/ws"))
        await ws.send_json({"type": "configure", "min_speech_duration_ms": 32})
        await ws.receive_json()
        pcm = base64.b64encode((np.ones(512, dtype="<i2") * 12000).tobytes()).decode()
        payload = {"type": "audio", "audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}
        await ws.send_json(payload)
        error = await ws.receive_json()
        self.assertEqual(error["type"], "semantic_error")
        self.assertEqual(error["raw_output"], "需要。")
        self.assertEqual(error["allowed"], ["需要", "不需要"])
        self.assertFalse(ws.closed)
        await ws.send_json({"type": "reset"})
        self.assertEqual((await ws.receive_json())["type"], "reset")
        await ws.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
