"""Three-state acoustic + MiMo semantic VAD controller."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import io
import json
import logging
import math
import re
import time
from typing import Protocol
import wave

import numpy as np


LOG = logging.getLogger("mimo_tts.semantic_vad")
SILERO_VAD_MIN_THRESHOLD = 0.15

SPEECH_TOKEN = "<s>"
NO_SPEECH_TOKEN = "</s>"
BREAK_TOKEN = "<b>"
NO_BREAK_TOKEN = "</b>"
COMPLETE_TOKEN = "<c>"
INCOMPLETE_TOKEN = "</c>"
SEMANTIC_TOKENS = frozenset({
    SPEECH_TOKEN,
    NO_SPEECH_TOKEN,
    BREAK_TOKEN,
    NO_BREAK_TOKEN,
    COMPLETE_TOKEN,
    INCOMPLETE_TOKEN,
})


class InputState(str, Enum):
    SILENCE = "Silence"
    JUDGE = "Judge"
    LISTEN = "Listen"


class InputEvent(str, Enum):
    NO_OP = "NO_OP"
    PREFILL = "PREFILL"
    CHUNK_PREFILL = "CHUNK_PREFILL"
    DECODE = "DECODE"


class SemanticLabel(str, Enum):
    BREAK = "BREAK"
    NO_BREAK = "NO_BREAK"
    REJECT = "REJECT"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    NOT_RUN = "NOT_RUN"


@dataclass(frozen=True, slots=True)
class AudioChunkBatch:
    chunks: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class VASDDecision:
    break_decision: bool
    reject: bool = False

    @property
    def label(self) -> SemanticLabel:
        if self.reject:
            return SemanticLabel.REJECT
        return SemanticLabel.BREAK if self.break_decision else SemanticLabel.NO_BREAK


@dataclass(frozen=True, slots=True)
class VAEDDecision:
    complete: bool

    @property
    def label(self) -> SemanticLabel:
        return SemanticLabel.COMPLETE if self.complete else SemanticLabel.INCOMPLETE


@dataclass(frozen=True, slots=True)
class FSMInput:
    audio_chunk: object
    speech: bool
    break_decision: bool | None = None
    reject: bool | None = None
    complete: bool | None = None


@dataclass(frozen=True, slots=True)
class FSMOutput:
    previous_state: InputState
    state: InputState
    event: InputEvent
    interrupt: bool
    prefill_audio: tuple[object, ...] | None
    semantic_label: SemanticLabel
    speech: bool
    break_decision: bool | None
    reject: bool | None
    complete: bool | None
    timestamp: float

    def as_log(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "previous_state": self.previous_state.value,
            "speech": self.speech,
            "break_decision": self.break_decision,
            "reject": self.reject,
            "complete": self.complete,
            "semantic_label": self.semantic_label.value,
            "next_state": self.state.value,
            "fsm_event": self.event.value,
            "interrupt": self.interrupt,
            "prefill_audio_chunk_count": len(self.prefill_audio or ()),
        }


class SemanticVADProvider(Protocol):
    async def decide_break(self, audio_chunks: Sequence[object], *, context: Mapping[str, object]) -> VASDDecision:
        ...

    async def decide_complete(
        self,
        audio_chunks: Sequence[object],
        *,
        context: Mapping[str, object],
    ) -> VAEDDecision:
        ...


class DuplexInputFSM:
    """The exact Silence/Judge/Listen state machine from the Stage 4 spec."""

    def __init__(self, *, max_buffered_chunks: int = 512) -> None:
        if max_buffered_chunks <= 0:
            raise ValueError("max_buffered_chunks must be positive")
        self.state = InputState.SILENCE
        self.max_buffered_chunks = max_buffered_chunks
        self._candidate_audio: list[object] = []
        self._turn_audio: list[object] = []

    @property
    def candidate_audio(self) -> tuple[object, ...]:
        return tuple(self._candidate_audio)

    @property
    def turn_audio(self) -> tuple[object, ...]:
        return tuple(self._turn_audio)

    def reset(self) -> None:
        self.state = InputState.SILENCE
        self._candidate_audio.clear()
        self._turn_audio.clear()

    @staticmethod
    def _chunks(audio_chunk: object) -> tuple[object, ...]:
        if isinstance(audio_chunk, AudioChunkBatch):
            return audio_chunk.chunks
        return (audio_chunk,)

    def semantic_audio_with(self, audio_chunk: object) -> tuple[object, ...]:
        chunks = self._chunks(audio_chunk)
        if self.state == InputState.JUDGE:
            return (*self._candidate_audio, *chunks)
        if self.state == InputState.LISTEN:
            return (*self._turn_audio, *chunks)
        return chunks

    def _append(self, target: list[object], chunk: object) -> None:
        chunks = self._chunks(chunk)
        if len(target) + len(chunks) > self.max_buffered_chunks:
            raise OverflowError("semantic VAD audio buffer exceeded max_buffered_chunks")
        target.extend(chunks)

    def step(self, item: FSMInput) -> FSMOutput:
        previous = self.state
        event = InputEvent.NO_OP
        interrupt = False
        prefill_audio: tuple[object, ...] | None = None
        semantic_label = SemanticLabel.NOT_RUN

        if previous == InputState.SILENCE:
            if item.speech:
                self._candidate_audio.clear()
                self._turn_audio.clear()
                self._append(self._candidate_audio, item.audio_chunk)
                self.state = InputState.JUDGE

        elif previous == InputState.JUDGE:
            if item.break_decision is None or item.reject is None:
                raise ValueError("Judge requires break_decision and reject")
            self._append(self._candidate_audio, item.audio_chunk)
            decision = VASDDecision(item.break_decision, item.reject)
            semantic_label = decision.label
            effective_break = decision.break_decision and not decision.reject
            if effective_break:
                self.state = InputState.LISTEN
                event = InputEvent.PREFILL
                interrupt = True
                prefill_audio = tuple(self._candidate_audio)
                self._turn_audio = list(self._candidate_audio)
                self._candidate_audio.clear()
            elif not item.speech:
                self.state = InputState.SILENCE
                self._candidate_audio.clear()
                self._turn_audio.clear()

        elif previous == InputState.LISTEN:
            if item.complete is None:
                raise ValueError("Listen requires complete")
            semantic_label = VAEDDecision(item.complete).label
            self._append(self._turn_audio, item.audio_chunk)
            prefill_audio = self._chunks(item.audio_chunk)
            if item.complete or not item.speech:
                self.state = InputState.SILENCE
                event = InputEvent.DECODE
                self._candidate_audio.clear()
                self._turn_audio.clear()
            else:
                event = InputEvent.CHUNK_PREFILL

        else:
            raise ValueError(f"Invalid state: {previous!r}")

        output = FSMOutput(
            previous_state=previous,
            state=self.state,
            event=event,
            interrupt=interrupt,
            prefill_audio=prefill_audio,
            semantic_label=semantic_label,
            speech=bool(item.speech),
            break_decision=item.break_decision,
            reject=item.reject,
            complete=item.complete,
            timestamp=time.time(),
        )
        LOG.info("semantic_vad_transition %s", json.dumps(output.as_log(), sort_keys=True))
        return output


class SemanticVADController:
    """Run only the semantic decision valid for the FSM's current state."""

    def __init__(self, provider: SemanticVADProvider, *, max_buffered_chunks: int = 512) -> None:
        self.provider = provider
        self.fsm = DuplexInputFSM(max_buffered_chunks=max_buffered_chunks)

    async def process(
        self,
        audio_chunk: object,
        *,
        speech: bool,
        context: Mapping[str, object] | None = None,
    ) -> FSMOutput:
        semantic_context = context or {}
        if self.fsm.state == InputState.JUDGE:
            decision = await self.provider.decide_break(
                self.fsm.semantic_audio_with(audio_chunk),
                context=semantic_context,
            )
            return self.fsm.step(FSMInput(
                audio_chunk=audio_chunk,
                speech=speech,
                break_decision=decision.break_decision,
                reject=decision.reject,
            ))
        if self.fsm.state == InputState.LISTEN:
            if not speech:
                return self.fsm.step(FSMInput(
                    audio_chunk=audio_chunk,
                    speech=False,
                    complete=False,
                ))
            decision = await self.provider.decide_complete(
                self.fsm.semantic_audio_with(audio_chunk),
                context=semantic_context,
            )
            return self.fsm.step(FSMInput(
                audio_chunk=audio_chunk,
                speech=speech,
                complete=decision.complete,
            ))
        return self.fsm.step(FSMInput(audio_chunk=audio_chunk, speech=speech))


@dataclass(frozen=True, slots=True)
class SemanticVADConfig:
    threshold: float = 0.5
    prefix_padding_ms: int = 300
    silence_duration_ms: int = 500
    min_speech_duration_ms: int = 96
    max_buffered_chunks: int = 512

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SemanticVADConfig":
        allowed = {
            "type",
            "threshold",
            "prefix_padding_ms",
            "silence_duration_ms",
            "min_speech_duration_ms",
            "max_buffered_chunks",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"Unknown semantic_vad field(s): {', '.join(unknown)}")
        threshold = value.get("threshold", 0.5)
        if (
            not isinstance(threshold, int | float)
            or isinstance(threshold, bool)
            or not math.isfinite(float(threshold))
            or not SILERO_VAD_MIN_THRESHOLD < float(threshold) <= 1.0
        ):
            raise ValueError(
                f"semantic_vad.threshold must be greater than {SILERO_VAD_MIN_THRESHOLD} and at most 1"
            )
        numbers = {}
        for name, default in (
            ("prefix_padding_ms", 300),
            ("silence_duration_ms", 500),
            ("min_speech_duration_ms", 96),
        ):
            item = value.get(name, default)
            if (
                not isinstance(item, int | float)
                or isinstance(item, bool)
                or not math.isfinite(float(item))
                or float(item) < 0
            ):
                raise ValueError(f"semantic_vad.{name} must be a non-negative number")
            numbers[name] = int(item)
        max_chunks = value.get("max_buffered_chunks", 512)
        if not isinstance(max_chunks, int) or isinstance(max_chunks, bool) or max_chunks <= 0:
            raise ValueError("semantic_vad.max_buffered_chunks must be a positive integer")
        return cls(
            threshold=float(threshold),
            max_buffered_chunks=max_chunks,
            **numbers,
        )


def extract_semantic_vad_config(session_payload: dict[str, object]) -> SemanticVADConfig | None:
    """Remove app-owned semantic_vad from a session before engine validation."""
    selected: object = session_payload.get("turn_detection")
    container: dict[str, object] = session_payload
    audio = session_payload.get("audio")
    if isinstance(audio, dict):
        audio_input = audio.get("input")
        if isinstance(audio_input, dict) and "turn_detection" in audio_input:
            selected = audio_input.get("turn_detection")
            container = audio_input
    if not isinstance(selected, Mapping) or selected.get("type") != "semantic_vad":
        return None
    config = SemanticVADConfig.from_mapping(selected)
    container["turn_detection"] = None
    session_payload["overlap_policy"] = "listen_only"
    return config


class SemanticRealtimeAdapter:
    """Translate semantic FSM outputs into existing Realtime runner commands."""

    def __init__(
        self,
        config: SemanticVADConfig,
        provider: SemanticVADProvider,
        *,
        backend_provider=None,
        frame_scorer=None,
        vad=None,
    ) -> None:
        self.config = config
        self._prefix_audio: list[dict[str, object]] = []
        self.controller = SemanticVADController(
            provider,
            max_buffered_chunks=config.max_buffered_chunks,
        )
        if vad is None:
            from vllm_omni.engine.duplex.vad import (
                SileroStreamingVAD,
                SileroVADConfig,
            )
            vad = SileroStreamingVAD(
                SileroVADConfig(
                    threshold=config.threshold,
                    prefix_padding_ms=config.prefix_padding_ms,
                    silence_duration_ms=config.silence_duration_ms,
                    min_speech_duration_ms=max(32, config.min_speech_duration_ms),
                ),
                backend_provider=backend_provider,
                frame_scorer=frame_scorer,
            )
        self.vad = vad

    def reset(self) -> None:
        self.controller.fsm.reset()
        self._prefix_audio.clear()
        reset = getattr(self.vad, "reset", None)
        if callable(reset):
            reset()

    def _remember_prefix(self, chunk: dict[str, object]) -> None:
        self._prefix_audio.append(chunk)
        target_ms = self.config.prefix_padding_ms + self.config.min_speech_duration_ms + 32
        total_ms = sum(_chunk_duration_ms(item) for item in self._prefix_audio)
        while len(self._prefix_audio) > 1 and total_ms > target_ms:
            total_ms -= _chunk_duration_ms(self._prefix_audio.pop(0))

    async def process_append(
        self,
        payload: Mapping[str, object],
        *,
        default_format: str,
        default_sample_rate_hz: int,
        context: Mapping[str, object] | None = None,
    ) -> tuple[FSMOutput, list[dict[str, object]]]:
        if payload.get("type") != "input_audio_buffer.append":
            raise ValueError("SemanticRealtimeAdapter only accepts audio append events")
        audio = payload.get("audio")
        if not isinstance(audio, str) or not audio:
            raise ValueError("semantic_vad requires non-empty audio append data")
        audio_format = payload.get("format", default_format)
        sample_rate = payload.get("sample_rate_hz", default_sample_rate_hz)
        chunk = dict(payload)
        chunk["format"] = audio_format
        chunk["sample_rate_hz"] = sample_rate
        vad_result = self.vad.process_base64(
            audio,
            fmt=audio_format,
            sample_rate_hz=sample_rate,
        )
        state_before = self.controller.fsm.state
        controller_chunk: object = chunk
        if state_before == InputState.SILENCE and vad_result.speech_active and self._prefix_audio:
            controller_chunk = AudioChunkBatch((*self._prefix_audio, chunk))
            self._prefix_audio.clear()
        output = await self.controller.process(
            controller_chunk,
            speech=vad_result.speech_active,
            context=context,
        )
        if (
            state_before == InputState.SILENCE
            and output.state == InputState.SILENCE
            and not vad_result.speech_active
        ):
            self._remember_prefix(chunk)
        commands: list[dict[str, object]] = []
        if output.event == InputEvent.PREFILL:
            commands.append({"type": "barge_in"})
            commands.extend(dict(item) for item in output.prefill_audio or ())
        elif output.event == InputEvent.CHUNK_PREFILL:
            commands.extend(dict(item) for item in output.prefill_audio or ())
        elif output.event == InputEvent.DECODE:
            commands.extend(dict(item) for item in output.prefill_audio or ())
            commands.append({
                "type": "input_audio_buffer.commit",
                "final": True,
                "create_response": True,
            })
        return output, commands


def _chunk_duration_ms(chunk: Mapping[str, object]) -> float:
    encoded = chunk.get("audio")
    if not isinstance(encoded, str):
        return 0.0
    try:
        byte_count = len(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError):
        return 0.0
    sample_width = 4 if chunk.get("format") == "pcm_f32le" else 2
    sample_rate = chunk.get("sample_rate_hz")
    if not isinstance(sample_rate, int | float) or sample_rate <= 0:
        return 0.0
    return byte_count / sample_width * 1000.0 / float(sample_rate)


_VASD_SYSTEM = """You are the semantic interruption classifier for a duplex voice assistant.
Listen to the candidate user audio and output exactly one label:
<b> if it contains meaningful speech that should interrupt the assistant;
</b> if it has understandable meaning but should not interrupt;
REJECT if it has no acceptable semantic content, such as noise or unintelligible audio.
Do not explain your answer."""

_VAED_SYSTEM = """You are the semantic endpoint classifier for a duplex voice assistant.
Listen to the current user utterance and output exactly one label:
<c> if the user's meaning is complete and the assistant may answer;
</c> if the user is still speaking an incomplete thought.
Do not explain your answer."""


class MiMoSemanticVADProvider:
    """Use the existing MiMo audio chat endpoint for VASD and VAED."""

    def __init__(self, client, mimo_url: str, *, model: str = "mimo-v2.6-flash") -> None:
        self.client = client
        self.mimo_url = mimo_url.rstrip("/")
        self.model = model

    async def decide_break(self, audio_chunks, *, context):
        content = await self._classify(audio_chunks, system=_VASD_SYSTEM, request_kind="vasd", context=context)
        labels = _labels(content, (BREAK_TOKEN, NO_BREAK_TOKEN, SemanticLabel.REJECT.value))
        if labels == [BREAK_TOKEN]:
            return VASDDecision(True, False)
        if labels == [NO_BREAK_TOKEN]:
            return VASDDecision(False, False)
        if labels == [SemanticLabel.REJECT.value]:
            return VASDDecision(False, True)
        raise ValueError(f"Invalid VASD output: {content!r}")

    async def decide_complete(self, audio_chunks, *, context):
        content = await self._classify(audio_chunks, system=_VAED_SYSTEM, request_kind="vaed", context=context)
        labels = _labels(content, (COMPLETE_TOKEN, INCOMPLETE_TOKEN))
        if labels == [COMPLETE_TOKEN]:
            return VAEDDecision(True)
        if labels == [INCOMPLETE_TOKEN]:
            return VAEDDecision(False)
        raise ValueError(f"Invalid VAED output: {content!r}")

    async def _classify(self, audio_chunks, *, system, request_kind, context):
        wav = audio_chunks_to_wav(audio_chunks)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [{
                    "type": "input_audio",
                    "input_audio": {
                        "data": base64.b64encode(wav).decode("ascii"),
                        "format": "wav",
                    },
                }]},
            ],
            "max_tokens": 8,
            "temperature": 0.0,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        request_id = str(context.get("request_id") or f"semantic-vad-{time.time_ns()}")
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions",
            json=payload,
            headers={"X-Request-Id": f"{request_id}-{request_kind}"},
        ) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"MiMo semantic VAD HTTP {response.status}")
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("MiMo semantic VAD returned no classifier content") from exc
        if not isinstance(content, str):
            raise ValueError("MiMo semantic VAD classifier content must be text")
        return content.strip()


def _labels(content: str, allowed: Sequence[str]) -> list[str]:
    upper = content.upper()
    found: list[tuple[int, str]] = []
    for label in allowed:
        source = upper if label == SemanticLabel.REJECT.value else content
        target = label if source is content else label.upper()
        for match in re.finditer(re.escape(target), source):
            found.append((match.start(), label))
    found.sort()
    return [label for _, label in found]


def audio_chunks_to_wav(audio_chunks: Sequence[object]) -> bytes:
    pcm_parts: list[bytes] = []
    sample_rate: int | None = None
    for chunk in audio_chunks:
        if not isinstance(chunk, Mapping):
            raise ValueError("Semantic VAD audio chunk must be a mapping")
        encoded = chunk.get("audio")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("Semantic VAD audio chunk requires base64 audio")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Semantic VAD audio chunk contains invalid base64") from exc
        chunk_rate = chunk.get("sample_rate_hz", 16000)
        if not isinstance(chunk_rate, int) or chunk_rate <= 0:
            raise ValueError("Semantic VAD audio chunk requires a positive sample rate")
        if sample_rate is None:
            sample_rate = chunk_rate
        elif sample_rate != chunk_rate:
            raise ValueError("Semantic VAD audio sample rate cannot change within a turn")
        fmt = chunk.get("format", "pcm16")
        if fmt == "pcm16":
            if len(raw) % 2:
                raise ValueError("Semantic VAD received an incomplete pcm16 sample")
            pcm_parts.append(raw)
        elif fmt == "pcm_f32le":
            if len(raw) % 4:
                raise ValueError("Semantic VAD received an incomplete pcm_f32le sample")
            samples = np.frombuffer(raw, dtype="<f4")
            if not np.isfinite(samples).all():
                raise ValueError("Semantic VAD audio must contain finite samples")
            pcm_parts.append((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        else:
            raise ValueError("Semantic VAD requires pcm16 or pcm_f32le audio")
    if sample_rate is None or not pcm_parts:
        raise ValueError("Semantic VAD requires non-empty audio")
    output = io.BytesIO()
    with wave.open(output, "wb") as recording:
        recording.setparams((1, 2, sample_rate, 0, "NONE", ""))
        recording.writeframes(b"".join(pcm_parts))
    return output.getvalue()


def choose_decode_token(
    candidate_token: object,
    *,
    speak_probability: float,
    threshold: float,
    eos_token: object,
) -> object:
    if not math.isfinite(speak_probability) or not math.isfinite(threshold):
        raise ValueError("Speak probability and threshold must be finite")
    if not 0.0 <= speak_probability <= 1.0 or not 0.0 <= threshold <= 1.0:
        raise ValueError("Speak probability and threshold must be within [0, 1]")
    return candidate_token if speak_probability > threshold else eos_token
