"""Stage 4 functional tests for the semantic VAD controller."""

import asyncio
import base64
import io
import time
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
    InvalidSemanticCommand,
    MiMoSemanticVADProvider,
    MiMoChatProvider,
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
        final = fsm.step(FSMInput(
            chunk(4), speech=False, complete=True, semantic_endpoint_evaluated=True))
        self.assertEqual(initial.prefill_audio, (chunk(1), chunk(2)))
        self.assertEqual((middle.state, middle.event, middle.prefill_audio),
                         (InputState.LISTEN, InputEvent.CHUNK_PREFILL, (chunk(3),)))
        self.assertEqual((final.state, final.event, final.prefill_audio),
                         (InputState.SILENCE, InputEvent.DECODE, (chunk(4),)))
        delivered = initial.prefill_audio + middle.prefill_audio + final.prefill_audio
        self.assertEqual(delivered, tuple(chunk(i) for i in range(1, 5)))

    def test_t09_incomplete_endpoint_stays_listen_across_silence(self):
        fsm = DuplexInputFSM()
        fsm.step(FSMInput(chunk(1), speech=True))
        fsm.step(FSMInput(chunk(2), speech=True, break_decision=True, reject=False))
        endpoint = fsm.step(FSMInput(
            chunk(3), speech=False, complete=False, semantic_endpoint_evaluated=True))
        waiting = fsm.step(FSMInput(None, speech=False, complete=False))
        resumed = fsm.step(FSMInput(chunk(4), speech=True, complete=False))
        complete = fsm.step(FSMInput(
            chunk(5), speech=False, complete=True, semantic_endpoint_evaluated=True))
        self.assertEqual((endpoint.state, endpoint.event), (InputState.LISTEN, InputEvent.CHUNK_PREFILL))
        self.assertEqual((waiting.state, waiting.event), (InputState.LISTEN, InputEvent.NO_OP))
        self.assertEqual((resumed.state, resumed.event), (InputState.LISTEN, InputEvent.CHUNK_PREFILL))
        self.assertEqual((complete.state, complete.event), (InputState.SILENCE, InputEvent.DECODE))

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
    async def test_weak_break_candidate_stays_in_judge(self):
        provider = ScriptedProvider(breaks=[
            VASDDecision(True, probability=.54, margin=.25, command="<b>"),
        ])
        controller = SemanticVADController(
            provider,
            break_probability_threshold=.8,
            break_margin_threshold=1.5,
        )
        output = await controller.process(chunk(1), speech=True)
        self.assertEqual((output.state, output.event), (InputState.JUDGE, InputEvent.NO_OP))
        self.assertEqual(output.semantic_label, SemanticLabel.BREAK)
        self.assertFalse(output.break_accepted)
        self.assertEqual(output.break_confirmation_count, 0)

    async def test_break_confirmations_gate_prefill(self):
        provider = ScriptedProvider(breaks=[
            VASDDecision(True, probability=.9, margin=2.0, command="<b>"),
            VASDDecision(True, probability=.92, margin=2.25, command="<b>"),
        ])
        controller = SemanticVADController(provider, break_confirmations=2)
        first = await controller.process(chunk(1), speech=True)
        second = await controller.process(chunk(2), speech=True)
        self.assertEqual((first.state, first.event, first.break_confirmation_count), (
            InputState.JUDGE, InputEvent.NO_OP, 1,
        ))
        self.assertFalse(first.break_accepted)
        self.assertEqual((second.state, second.event, second.break_confirmation_count), (
            InputState.LISTEN, InputEvent.PREFILL, 2,
        ))
        self.assertTrue(second.break_accepted)

    async def test_no_break_resets_break_confirmation_count(self):
        provider = ScriptedProvider(breaks=[
            VASDDecision(True, probability=.9, margin=2.0, command="<b>"),
            VASDDecision(False, probability=.9, margin=2.0, command="</b>"),
            VASDDecision(True, probability=.9, margin=2.0, command="<b>"),
        ])
        controller = SemanticVADController(provider, break_confirmations=2)
        first = await controller.process(chunk(1), speech=True)
        no_break = await controller.process(chunk(2), speech=True)
        restarted = await controller.process(chunk(3), speech=True)
        self.assertEqual(first.break_confirmation_count, 1)
        self.assertEqual(no_break.break_confirmation_count, 0)
        self.assertEqual(restarted.break_confirmation_count, 1)
        self.assertEqual(restarted.state, InputState.JUDGE)

    async def test_state_specific_provider_calls_and_context(self):
        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[
                VAEDDecision(False, probability=.9, margin=2.0),
                VAEDDecision(True, probability=.95, margin=3.0),
            ],
        )
        controller = SemanticVADController(provider)
        prefill = await controller.process(chunk(1), speech=True, context={"request_id": "r"})
        incremental = await controller.process(chunk(2), speech=True, context={"request_id": "r"})
        await controller.process(chunk(3), speech=True, context={"request_id": "r"})
        endpoint = await controller.process(
            chunk(4), speech=False, speech_stopped=True, context={"request_id": "r"})
        waiting = await controller.process(None, speech=False, context={"request_id": "r"})
        resumed = await controller.process(chunk(5), speech=True, context={"request_id": "r"})
        decoded = await controller.process(
            chunk(6), speech=False, speech_stopped=True, context={"request_id": "r"})
        self.assertEqual([prefill.event, incremental.event, endpoint.event, waiting.event,
                          resumed.event, decoded.event], [
            InputEvent.PREFILL, InputEvent.CHUNK_PREFILL, InputEvent.CHUNK_PREFILL,
            InputEvent.NO_OP, InputEvent.CHUNK_PREFILL, InputEvent.DECODE,
        ])
        self.assertEqual([call[0] for call in provider.calls], ["break", "complete", "complete"])
        self.assertEqual(provider.calls[0][1], (chunk(1),))
        self.assertEqual(provider.calls[-1][1], tuple(chunk(i) for i in range(1, 7)))
        self.assertFalse(endpoint.completion_accepted)
        self.assertTrue(decoded.completion_accepted)

    async def test_speech_stop_runs_vaed_and_incomplete_waits(self):
        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[VAEDDecision(False, probability=.9, margin=2.0)],
        )
        controller = SemanticVADController(provider)
        await controller.process(chunk(1), speech=True)
        await controller.process(chunk(2), speech=True)
        output = await controller.process(chunk(3), speech=False, speech_stopped=True)
        repeated = await controller.process(None, speech=False)
        self.assertEqual(output.event, InputEvent.CHUNK_PREFILL)
        self.assertEqual(repeated.event, InputEvent.NO_OP)
        self.assertEqual([call[0] for call in provider.calls], ["break", "complete"])

    async def test_low_confidence_complete_candidate_does_not_decode(self):
        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[
                VAEDDecision(True, probability=.77, margin=1.25),
                VAEDDecision(True, probability=.95, margin=3.0),
            ],
        )
        controller = SemanticVADController(provider)
        await controller.process(chunk(1), speech=True)
        await controller.process(chunk(2), speech=True)
        low = await controller.process(chunk(3), speech=False, speech_stopped=True)
        await controller.process(chunk(4), speech=True)
        accepted = await controller.process(chunk(5), speech=False, speech_stopped=True)
        self.assertEqual(low.event, InputEvent.CHUNK_PREFILL)
        self.assertFalse(low.completion_accepted)
        self.assertEqual(low.completion_confirmation_count, 0)
        self.assertEqual(accepted.event, InputEvent.DECODE)
        self.assertEqual(accepted.completion_confirmation_count, 1)
        self.assertEqual(provider.calls[-1][1], tuple(chunk(i) for i in range(1, 6)))

    async def test_multiple_confirmations_are_counted_across_acoustic_endpoints(self):
        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[
                VAEDDecision(True, probability=.95, margin=3.0),
                VAEDDecision(True, probability=.96, margin=3.5),
            ],
        )
        controller = SemanticVADController(provider, complete_confirmations=2)
        await controller.process(chunk(1), speech=True)
        await controller.process(chunk(2), speech=True)
        first = await controller.process(chunk(3), speech=False, speech_stopped=True)
        await controller.process(chunk(4), speech=True)
        second = await controller.process(chunk(5), speech=False, speech_stopped=True)
        self.assertEqual((first.event, first.completion_confirmation_count), (
            InputEvent.CHUNK_PREFILL, 1,
        ))
        self.assertEqual((second.event, second.completion_confirmation_count), (
            InputEvent.DECODE, 2,
        ))

    async def test_silence_is_logged_as_one_interval(self):
        provider = ScriptedProvider(breaks=[VASDDecision(False)])
        controller = SemanticVADController(provider)
        with self.assertLogs("mimo_tts.semantic_vad", level="INFO") as captured:
            for index in range(4):
                await controller.process(chunk(index), speech=False, context={"request_id": f"svad-log-{index}"})
            await controller.process(chunk(4), speech=True, context={"request_id": "svad-log-4"})
        intervals = [line for line in captured.output if "semantic_vad_state_interval" in line]
        transitions = [line for line in captured.output if "semantic_vad_transition" in line]
        self.assertEqual(len(intervals), 1)
        self.assertIn('"audio_chunk_count": 4', intervals[0])
        self.assertIn('"session_id": "svad-log"', intervals[0])
        self.assertEqual(len(transitions), 2)
        self.assertIn('"previous_state": "Silence"', transitions[0])
        self.assertIn('"next_state": "Judge"', transitions[0])
        self.assertIn('"request_kind": "VASD"', transitions[1])

    async def test_vasd_uses_duration_bounded_sliding_window_but_keeps_full_candidate(self):
        def audio_chunk(index):
            pcm = index.to_bytes(2, "little", signed=True) * 8000
            return {
                "id": index,
                "audio": base64.b64encode(pcm).decode(),
                "format": "pcm16",
                "sample_rate_hz": 16000,
            }

        provider = ScriptedProvider(breaks=[VASDDecision(False)] * 17)
        controller = SemanticVADController(provider, vasd_window_ms=8000)
        chunks = [audio_chunk(index) for index in range(17)]
        for item in chunks:
            output = await controller.process(item, speech=True)
            self.assertEqual(output.state, InputState.JUDGE)
        self.assertEqual(provider.calls[0][1], (chunks[0],))
        self.assertEqual(provider.calls[15][1], tuple(chunks[:16]))
        self.assertEqual(provider.calls[16][1], tuple(chunks[1:17]))
        self.assertEqual(controller.fsm.candidate_audio, tuple(chunks))


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
        if isinstance(self.content, dict):
            return self.content
        sampled = self.content.strip()
        scores = {"有": -3.0, "无": -3.0, "已": -3.0, "未": -3.0}
        if sampled in scores:
            scores[sampled] = -0.1
        return {"choices": [{
            "message": {"content": self.content},
            "logprobs": {"content": [{"top_logprobs": [
                {"token": token, "logprob": score}
                for token, score in scores.items()
            ]}]},
        }]}


class FakeClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return FakeResponse(self.outputs.pop(0))


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_mimo_binary_vasd_and_vaed_labels(self):
        pcm = base64.b64encode(b"\0\0" * 160).decode()
        chunks = [{"audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}]
        client = FakeClient(["有", "无", "未", "已"])
        provider = MiMoSemanticVADProvider(client, "http://mimo")
        self.assertEqual(await provider.decide_break(chunks, context={}), VASDDecision(True, False))
        self.assertEqual(await provider.decide_break(chunks, context={}), VASDDecision(False, False))
        self.assertEqual(await provider.decide_complete(chunks, context={}), VAEDDecision(False))
        self.assertEqual(await provider.decide_complete(chunks, context={}), VAEDDecision(True))
        self.assertTrue(all(request[1]["json"]["stream"] is False for request in client.requests))
        self.assertEqual(client.requests[0][1]["json"]["allowed_token_ids"], [18830, 42192])
        self.assertEqual(client.requests[0][1]["json"]["logprob_token_ids"], [18830, 42192])
        self.assertEqual(client.requests[2][1]["json"]["allowed_token_ids"], [36667, 38342])
        self.assertEqual(client.requests[-1][1]["json"]["allowed_token_ids"], [36667, 38342])
        self.assertTrue(all(request[1]["json"]["max_tokens"] == 1 for request in client.requests))

    async def test_exact_chinese_code_is_valid_but_whitespace_and_explanations_are_invalid(self):
        pcm = base64.b64encode(b"\0\0" * 160).decode()
        chunks = [{"audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}]
        provider = MiMoSemanticVADProvider(FakeClient(["有", "答案：已", "已 "]), "http://mimo")
        decision = await provider.decide_break(chunks, context={})
        self.assertEqual(decision.command, "<b>")
        self.assertEqual(decision.raw_output, "有")
        self.assertEqual(set(decision.logprobs), {"<b>", "</b>"})
        self.assertGreater(decision.probability, .8)
        with self.assertRaises(InvalidSemanticCommand) as caught:
            await provider.decide_complete(chunks, context={})
        self.assertEqual(caught.exception.raw_output, "答案：已")
        self.assertEqual(caught.exception.allowed, ("已", "未"))
        with self.assertRaises(InvalidSemanticCommand) as caught:
            await provider.decide_complete(chunks, context={})
        self.assertEqual(caught.exception.raw_output, "已 ")

    async def test_ambiguous_model_output_is_rejected(self):
        pcm = base64.b64encode(b"\0\0" * 160).decode()
        chunks = [{"audio": pcm, "format": "pcm16", "sample_rate_hz": 16000}]
        provider = MiMoSemanticVADProvider(FakeClient(["有或无"]), "http://mimo")
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
        class EndpointVAD:
            def __init__(self):
                self.values = iter((True, True, True, False))

            def process_base64(self, *_args, **_kwargs):
                active = next(self.values)
                return SimpleNamespace(
                    is_speech=active,
                    speech_active=active,
                    speech_started=False,
                    speech_stopped=not active,
                    speech_probability=1.0 if active else 0.0,
                )

        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[VAEDDecision(True, probability=.95, margin=3.0)],
        )
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(min_speech_duration_ms=32, complete_confirmations=1),
            provider,
            vad=EndpointVAD(),
        )
        first, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(first.event, InputEvent.PREFILL)
        self.assertEqual([item["type"] for item in commands], [
            "barge_in", "input_audio_buffer.append",
        ])
        incremental, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(incremental.event, InputEvent.CHUNK_PREFILL)
        self.assertEqual([item["type"] for item in commands], ["input_audio_buffer.append"])
        incremental, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(incremental.event, InputEvent.CHUNK_PREFILL)
        decoded, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(decoded.event, InputEvent.DECODE)
        self.assertEqual([item["type"] for item in commands], [
            "input_audio_buffer.append", "input_audio_buffer.commit",
        ])

    async def test_no_semantic_does_not_dispatch_audio_or_interrupt(self):
        provider = ScriptedProvider(breaks=[VASDDecision(False), VASDDecision(False)])
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(min_speech_duration_ms=32),
            provider,
            vad=self.AlwaysSpeechVAD(),
        )
        output, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(output.semantic_label, SemanticLabel.NO_BREAK)
        self.assertEqual(output.state, InputState.JUDGE)
        self.assertEqual(commands, [])
        output, commands = await adapter.process_append(
            self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(output.semantic_label, SemanticLabel.NO_BREAK)
        self.assertEqual(commands, [])

    async def test_reset_clears_fsm_and_avad(self):
        provider = ScriptedProvider(breaks=[VASDDecision(False)])
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
        self.assertEqual(output.event, InputEvent.PREFILL)
        self.assertEqual(output.prefill_audio, (first, second))
        third = self.audio()
        output, commands = await adapter.process_append(
            third, default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(output.event, InputEvent.CHUNK_PREFILL)
        self.assertEqual(output.prefill_audio, (third,))

    async def test_decode_tail_is_not_reused_as_next_turn_prefix(self):
        class ScriptedVAD:
            def __init__(self):
                self.values = iter((True, True, False, True, True))

            def process_base64(self, *_args, **_kwargs):
                active = next(self.values)
                return SimpleNamespace(
                    is_speech=active,
                    speech_active=active,
                    speech_started=False,
                    speech_stopped=not active,
                    speech_probability=1.0 if active else 0.0,
                )

        provider = ScriptedProvider(
            breaks=[VASDDecision(True), VASDDecision(True)],
            completes=[VAEDDecision(True, probability=.95, margin=3.0)],
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
        prefill, _ = await adapter.process_append(
            chunks[3], default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(prefill.prefill_audio, (chunks[3],))
        incremental, _ = await adapter.process_append(
            chunks[4], default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(incremental.prefill_audio, (chunks[4],))

    async def test_incomplete_pause_resumes_same_listen_turn_then_decodes(self):
        class ScriptedVAD:
            def __init__(self):
                self.values = iter((True, True, True, False, False, True, False))

            def process_base64(self, *_args, **_kwargs):
                value = next(self.values)
                stopped = not value and self.last_active
                self.last_active = value
                return SimpleNamespace(
                    is_speech=value, speech_active=value,
                    speech_started=False, speech_stopped=stopped,
                    speech_probability=1.0 if value else 0.0,
                )

            last_active = False

        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[
                VAEDDecision(False, probability=.95, margin=3.0),
                VAEDDecision(True, probability=.95, margin=3.0),
            ],
        )
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(complete_confirmations=1), provider, vad=ScriptedVAD())
        outputs = []
        commands = []
        for _ in range(7):
            output, _commands = await adapter.process_append(
                self.audio(), default_format="pcm16", default_sample_rate_hz=16000)
            outputs.append(output)
            commands.append(_commands)
        self.assertEqual([item.state for item in outputs], [
            InputState.LISTEN, InputState.LISTEN, InputState.LISTEN,
            InputState.LISTEN, InputState.LISTEN, InputState.LISTEN,
            InputState.SILENCE,
        ])
        self.assertEqual([item.event for item in outputs[3:]], [
            InputEvent.CHUNK_PREFILL, InputEvent.NO_OP,
            InputEvent.CHUNK_PREFILL, InputEvent.DECODE,
        ])
        self.assertEqual(commands[4], [])
        self.assertEqual([call[0] for call in provider.calls], [
            "break", "complete", "complete",
        ])
        self.assertEqual(len(provider.calls[1][1]), 4)
        self.assertEqual(len(provider.calls[2][1]), 6)
        self.assertEqual(len(outputs[-1].decode_audio), 6)

    async def test_incomplete_silence_timeout_forces_decode_without_appending_silence(self):
        class ScriptedVAD:
            def __init__(self):
                self.values = iter((True, True, False, False))
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
                    speech_probability=1.0 if active else 0.0,
                )

        provider = ScriptedProvider(
            breaks=[VASDDecision(True)],
            completes=[VAEDDecision(False, probability=.95, margin=3.0)],
        )
        adapter = SemanticRealtimeAdapter(
            SemanticVADConfig(incomplete_silence_timeout_ms=10),
            provider,
            vad=ScriptedVAD(),
        )
        chunks = [self.audio() for _ in range(4)]
        for payload in chunks[:3]:
            output, _ = await adapter.process_append(
                payload, default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual(output.event, InputEvent.CHUNK_PREFILL)
        adapter._incomplete_silence_started = time.monotonic() - 1
        decoded, commands = await adapter.process_append(
            chunks[3], default_format="pcm16", default_sample_rate_hz=16000)
        self.assertEqual((decoded.state, decoded.event, decoded.decode_reason), (
            InputState.SILENCE, InputEvent.DECODE, "incomplete_silence_timeout",
        ))
        self.assertEqual(decoded.decode_audio, tuple(chunks[:3]))
        self.assertEqual([item["type"] for item in commands], [
            "input_audio_buffer.commit",
        ])
        self.assertEqual([call[0] for call in provider.calls], ["break", "complete"])


class ChatProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_audio_is_followed_by_chinese_answer_instruction(self):
        class Response:
            status = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            @property
            def content(self):
                async def stream():
                    for line in (
                        b'data: {"choices":[{"delta":{"content":"\xe5\x9b\x9e\xe7\xad\x94"},"finish_reason":null}]}\n',
                        b'\n',
                        b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n',
                        b'\n',
                        b'data: [DONE]\n',
                        b'\n',
                    ):
                        yield line
                return stream()

        class Client:
            def __init__(self):
                self.payload = None

            def post(self, _url, *, json, headers):
                self.payload = json
                return Response()

        client = Client()
        provider = MiMoChatProvider(client, "http://mimo")
        audio = self._pcm_chunk()
        deltas = [delta async for delta in provider.stream_reply(
            [audio],
            history=[{"audio_wav": base64.b64encode(audio_chunks_to_wav([audio])).decode(),
                      "assistant": "上一轮回答"}],
            prompt="中文 Chat Prompt",
            context={"request_id": "chat-test"},
        )]
        self.assertEqual(deltas, ["回答"])
        self.assertEqual(client.payload["messages"][0]["content"], "中文 Chat Prompt")
        user_messages = [row for row in client.payload["messages"] if row["role"] == "user"]
        self.assertEqual(len(user_messages), 2)
        for message in user_messages:
            self.assertEqual(message["content"][0]["type"], "input_audio")
            self.assertIn("不要转写", message["content"][1]["text"])

    @staticmethod
    def _pcm_chunk():
        return {
            "type": "input_audio_buffer.append",
            "audio": base64.b64encode(b"\0\0" * 160).decode(),
            "format": "pcm16",
            "sample_rate_hz": 16000,
        }


if __name__ == "__main__":
    unittest.main(verbosity=2)
