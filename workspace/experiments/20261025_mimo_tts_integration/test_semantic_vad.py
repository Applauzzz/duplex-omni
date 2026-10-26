"""Stage 4 functional tests for the semantic VAD controller."""

import asyncio
import base64
import io
import unittest
import wave
from types import SimpleNamespace

from semantic_vad import (
    BREAK_TOKEN,
    COMPLETE_TOKEN,
    INCOMPLETE_TOKEN,
    NO_BREAK_TOKEN,
    SEMANTIC_TOKENS,
    SPEECH_TOKEN,
    DuplexInputFSM,
    FSMInput,
    InputEvent,
    InputState,
    MiMoSemanticVADProvider,
    SemanticLabel,
    SemanticRealtimeAdapter,
    SemanticVADConfig,
    SemanticVADController,
    VAEDDecision,
    VASDDecision,
    audio_chunks_to_wav,
    choose_decode_token,
    extract_semantic_vad_config,
)


def chunk(value):
    return {"id": value}


class ScriptedProvider:
    def __init__(self, *, breaks=(), completes=()):
        self.breaks = list(breaks)
        self.completes = list(completes)
        self.calls = []

    async def decide_break(self, audio_chunks, *, context):
        self.calls.append(("break", tuple(audio_chunks), dict(context)))
        return self.breaks.pop(0)

    async def decide_complete(self, audio_chunks, *, context):
        self.calls.append(("complete", tuple(audio_chunks), dict(context)))
        return self.completes.pop(0)


class FSMTests(unittest.TestCase):
    def test_t01_t02_silence_and_candidate_start(self):
        fsm = DuplexInputFSM()
        output = fsm.step(FSMInput(chunk(0), speech=False))
        self.assertEqual((output.state, output.event), (InputState.SILENCE, InputEvent.NO_OP))
        output = fsm.step(FSMInput(chunk(1), speech=True))
        self.assertEqual((output.state, output.event), (InputState.JUDGE, InputEvent.NO_OP))
        self.assertEqual(fsm.candidate_audio, (chunk(1),))

    def test_t03_no_break_stays_in_judge(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        output = fsm.step(FSMInput(chunk(2), speech=True, break_decision=False, reject=False))
        self.assertEqual((output.state, output.event), (InputState.JUDGE, InputEvent.NO_OP))
        self.assertEqual(output.semantic_label, SemanticLabel.NO_BREAK)

    def test_t04_t05_reject_then_silence_discards_candidate(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        rejected = fsm.step(FSMInput(chunk(2), speech=True, break_decision=True, reject=True))
        self.assertEqual((rejected.state, rejected.event), (InputState.JUDGE, InputEvent.NO_OP))
        self.assertFalse(rejected.interrupt)
        self.assertEqual(rejected.semantic_label, SemanticLabel.REJECT)
        stopped = fsm.step(FSMInput(chunk(3), speech=False, break_decision=False, reject=True))
        self.assertEqual((stopped.state, stopped.event), (InputState.SILENCE, InputEvent.NO_OP))
        self.assertEqual(fsm.candidate_audio, ())

    def test_t06_prefill_is_exactly_once_and_break_has_priority(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        output = fsm.step(FSMInput(chunk(2), speech=False, break_decision=True, reject=False))
        self.assertEqual((output.state, output.event), (InputState.LISTEN, InputEvent.PREFILL))
        self.assertTrue(output.interrupt)
        self.assertEqual(output.prefill_audio, (chunk(1), chunk(2)))
        self.assertEqual(fsm.candidate_audio, ())

    def test_t07_t08_t11_chunk_then_complete_without_duplicate(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        initial = fsm.step(FSMInput(chunk(2), speech=True, break_decision=True, reject=False))
        middle = fsm.step(FSMInput(chunk(3), speech=True, complete=False))
        final = fsm.step(FSMInput(chunk(4), speech=True, complete=True))
        self.assertEqual(initial.prefill_audio, (chunk(1), chunk(2)))
        self.assertEqual((middle.state, middle.event, middle.prefill_audio),
                         (InputState.LISTEN, InputEvent.CHUNK_PREFILL, (chunk(3),)))
        self.assertEqual((final.state, final.event, final.prefill_audio),
                         (InputState.SILENCE, InputEvent.DECODE, (chunk(4),)))
        delivered = initial.prefill_audio + middle.prefill_audio + final.prefill_audio
        self.assertEqual(delivered, tuple(chunk(i) for i in range(1, 5)))

    def test_t09_speech_zero_immediately_decodes(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        fsm.step(FSMInput(chunk(2), speech=True, break_decision=True, reject=False))
        output = fsm.step(FSMInput(chunk(3), speech=False, complete=False))
        self.assertEqual((output.state, output.event), (InputState.SILENCE, InputEvent.DECODE))

    def test_t10_reject_overrides_break(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        output = fsm.step(FSMInput(chunk(2), speech=True, break_decision=True, reject=True))
        self.assertEqual((output.state, output.event), (InputState.JUDGE, InputEvent.NO_OP))
        self.assertFalse(output.interrupt)
        self.assertIsNone(output.prefill_audio)

    def test_required_decisions_and_bounded_buffer(self):
        fsm = DuplexInputFSM(max_buffered_chunks=1)
        fsm.step(FSMInput(chunk(1), speech=True))
        missing = DuplexInputFSM()
        missing.step(FSMInput(chunk(0), speech=True))
        with self.assertRaises(ValueError):
            missing.step(FSMInput(chunk(1), speech=True))
        with self.assertRaises(OverflowError):
            fsm.step(FSMInput(chunk(2), speech=True, break_decision=False, reject=False))


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_specific_provider_calls_and_context(self):
        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[VAEDDecision(False), VAEDDecision(True)],
        )
        controller = SemanticVADController(provider)
        await controller.process(chunk(1), speech=True, context={"request_id": "r"})
        prefill = await controller.process(chunk(2), speech=True, context={"request_id": "r"})
        incremental = await controller.process(chunk(3), speech=True, context={"request_id": "r"})
        decoded = await controller.process(chunk(4), speech=True, context={"request_id": "r"})
        self.assertEqual([prefill.event, incremental.event, decoded.event], [
            InputEvent.PREFILL, InputEvent.CHUNK_PREFILL, InputEvent.DECODE,
        ])
        self.assertEqual([call[0] for call in provider.calls], ["break", "complete", "complete"])
        self.assertEqual(provider.calls[0][1], (chunk(1), chunk(2)))
        self.assertEqual(provider.calls[-1][1], tuple(chunk(i) for i in range(1, 5)))

    async def test_speech_stop_decodes_without_vaed_call(self):
        provider = ScriptedProvider(breaks=[VASDDecision(True)])
        controller = SemanticVADController(provider)
        await controller.process(chunk(1), speech=True)
        await controller.process(chunk(2), speech=True)
        output = await controller.process(chunk(3), speech=False)
        self.assertEqual(output.event, InputEvent.DECODE)
        self.assertEqual([call[0] for call in provider.calls], ["break"])


class SpeakDecisionTests(unittest.TestCase):
    def test_t12_t13_speak_threshold(self):
        self.assertEqual(choose_decode_token("candidate", speak_probability=.8, threshold=.5, eos_token="EOS"),
                         "candidate")
        self.assertEqual(choose_decode_token("candidate", speak_probability=.5, threshold=.5, eos_token="EOS"),
                         "EOS")

    def test_six_tokens_are_exact(self):
        self.assertEqual(SEMANTIC_TOKENS, {
            "<s>", "</s>", "<b>", "</b>", "<c>", "</c>",
        })
        self.assertEqual((SPEECH_TOKEN, BREAK_TOKEN, NO_BREAK_TOKEN, COMPLETE_TOKEN, INCOMPLETE_TOKEN),
                         ("<s>", "<b>", "</b>", "<c>", "</c>"))


class AudioTests(unittest.TestCase):
    def test_pcm_chunks_form_one_wav(self):
        chunks = []
        for value in (1, 2):
            pcm = (value.to_bytes(2, "little", signed=True)) * 160
            chunks.append({
                "audio": base64.b64encode(pcm).decode(),
                "format": "pcm16",
                "sample_rate_hz": 16000,
            })
        raw = audio_chunks_to_wav(chunks)
        with wave.open(io.BytesIO(raw), "rb") as recording:
            self.assertEqual(recording.getparams()[:3], (1, 2, 16000))
            self.assertEqual(recording.getnframes(), 320)


class FakeResponse:
    def __init__(self, content):
        self.status = 200
        self.content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def json(self, content_type=None):
        return {"choices": [{"message": {"content": self.content}}]}


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeResponse(self.outputs.pop(0))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_mimo_labels_and_reject(self):
        pcm = base64.b64encode(b"\0\0" * 160).decode()
        chunks = [{"audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}]
        client = FakeClient(["<b>", "REJECT", "</c>", "<c>"])
        provider = MiMoSemanticVADProvider(client, "http://mimo")
        self.assertEqual(await provider.decide_break(chunks, context={}), VASDDecision(True, False))
        self.assertEqual(await provider.decide_break(chunks, context={}), VASDDecision(False, True))
        self.assertEqual(await provider.decide_complete(chunks, context={}), VAEDDecision(False))
        self.assertEqual(await provider.decide_complete(chunks, context={}), VAEDDecision(True))
        self.assertTrue(all(request[1]["json"]["stream"] is False for request in client.requests))

    async def test_ambiguous_model_output_is_rejected(self):
        pcm = base64.b64encode(b"\0\0" * 160).decode()
        chunks = [{"audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}]
        provider = MiMoSemanticVADProvider(FakeClient(["<b> or </b>"]), "http://mimo")
        with self.assertRaises(ValueError):
            await provider.decide_break(chunks, context={})


class ConfigTests(unittest.TestCase):
    def test_nested_semantic_config_is_removed_before_engine_validation(self):
        session = {
            "overlap_policy": "barge_in_on_speech",
            "audio": {"input": {"turn_detection": {
                "type": "semantic_vad",
                "threshold": 0.6,
                "max_buffered_chunks": 7,
            }}},
        }
        config = extract_semantic_vad_config(session)
        self.assertEqual(config, SemanticVADConfig(threshold=0.6, max_buffered_chunks=7))
        self.assertIsNone(session["audio"]["input"]["turn_detection"])
        self.assertEqual(session["overlap_policy"], "listen_only")

    def test_legacy_server_vad_is_untouched(self):
        session = {"turn_detection": {"type": "server_vad", "threshold": 0.5}}
        self.assertIsNone(extract_semantic_vad_config(session))
        self.assertEqual(session["turn_detection"]["type"], "server_vad")

    def test_unknown_semantic_config_is_refused(self):
        with self.assertRaises(ValueError):
            extract_semantic_vad_config({
                "turn_detection": {"type": "semantic_vad", "debounce_ms": 500},
            })


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    class AlwaysSpeechVAD:
        def __init__(self):
            self.reset_count = 0

        def process_base64(self, *_args, **_kwargs):
            return SimpleNamespace(speech_active=True)

        def reset(self):
            self.reset_count += 1

    def audio(self, high=True):
        value = 12000 if high else 0
        pcm = value.to_bytes(2, "little", signed=True) * 512
        return {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(pcm).decode(),
            "format": "pcm16",
            "sample_rate_hz": 16000,
        }

    async def test_prefill_chunk_and_decode_command_order(self):
        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[VAEDDecision(False), VAEDDecision(True)],
        )
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(min_speech_duration_ms=32),
            provider,
            vad=self.AlwaysSpeechVAD(),
        )
        first, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual((first.state, commands), (InputState.JUDGE, []))
        prefill, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(prefill.event, InputEvent.PREFILL)
        self.assertEqual([item["type"] for item in commands], [
            "barge_in", "input_audio_buffer.append", "input_audio_buffer.append",
        ])
        incremental, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(incremental.event, InputEvent.CHUNK_PREFILL)
        self.assertEqual([item["type"] for item in commands], ["input_audio_buffer.append"])
        decoded, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(decoded.event, InputEvent.DECODE)
        self.assertEqual([item["type"] for item in commands], [
            "input_audio_buffer.append", "input_audio_buffer.commit",
        ])

    async def test_reject_does_not_dispatch_audio_or_interrupt(self):
        provider = ScriptedProvider(breaks=[VASDDecision(True, True)])
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(min_speech_duration_ms=32),
            provider,
            vad=self.AlwaysSpeechVAD(),
        )
        await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        output, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(output.semantic_label, SemanticLabel.REJECT)
        self.assertEqual(commands, [])

    async def test_reset_clears_fsm_and_avad(self):
        provider = ScriptedProvider()
        vad = self.AlwaysSpeechVAD()
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(min_speech_duration_ms=32),
            provider,
            vad=vad,
        )
        await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(adapter.controller.fsm.state, InputState.JUDGE)
        adapter.reset()
        self.assertEqual(adapter.controller.fsm.state, InputState.SILENCE)
        self.assertEqual(adapter.controller.fsm.candidate_audio, ())
        self.assertEqual(vad.reset_count, 1)

    async def test_avads_delayed_activation_preserves_prefix_chunk(self):
        class DelayedVAD:
            def __init__(self):
                self.calls = 0

            def process_base64(self, *_args, **_kwargs):
                self.calls += 1
                return SimpleNamespace(speech_active=self.calls >= 2)

        provider = ScriptedProvider(breaks=[VASDDecision(True)])
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(prefix_padding_ms=300, min_speech_duration_ms=96),
            provider,
            vad=DelayedVAD(),
        )
        first = self.audio()
        second = self.audio()
        output, commands = await adapter.process_append(
            first, default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual((output.state, commands), (InputState.SILENCE, []))
        output, commands = await adapter.process_append(
            second, default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual((output.state, commands), (InputState.JUDGE, []))
        third = self.audio()
        output, commands = await adapter.process_append(
            third, default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(output.event, InputEvent.PREFILL)
        self.assertEqual(output.prefill_audio, (first, second, third))

    async def test_decode_tail_is_not_reused_as_next_turn_prefix(self):
        class ScriptedVAD:
            def __init__(self):
                self.values = iter((True, True, False, True, True))

            def process_base64(self, *_args, **_kwargs):
                return SimpleNamespace(speech_active=next(self.values))

        provider = ScriptedProvider(
            breaks=[VASDDecision(True), VASDDecision(True)],
        )
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(),
            provider,
            vad=ScriptedVAD(),
        )
        chunks = [self.audio() for _ in range(5)]
        await adapter.process_append(
            chunks[0], default_format="pcm16", default_sample_rate_hz=16000)
        await adapter.process_append(
            chunks[1], default_format="pcm16", default_sample_rate_hz=16000)
        decoded, _ = await adapter.process_append(
            chunks[2], default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(decoded.event, InputEvent.DECODE)
        await adapter.process_append(
            chunks[3], default_format="pcm16", default_sample_rate_hz=16000)
        prefill, _ = await adapter.process_append(
            chunks[4], default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(prefill.prefill_audio, (chunks[3], chunks[4]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
