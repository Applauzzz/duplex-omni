"""Three-state acoustic + MiMo semantic VAD controller."""

from __future__ import annotations

import asyncio
import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
import io
import json
import logging
import math
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
INTERRUPTION_MARKER = "⏸"
INTERRUPTION_MARKER_TOKEN_ID = 149660
INTERRUPTED_CONTEXT_INSTRUCTION = f"""对话历史中的符号 {INTERRUPTION_MARKER} 是单 token 的回复中断标记。
它表示该条 assistant 回复在此位置被用户打断，并未继续完成。
下一轮中，如果用户没有主动问起被打断前的内容，不得从该标记前的未完成回复继续生成，必须转向用户当前的新问题或新需求。
如果用户主动追问被打断前的内容，可以结合标记前已经生成的内容回答，并明确提醒用户该回复当时在标记处被打断。"""
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
    SEMANTIC = "SEMANTIC"
    NO_SEMANTIC = "NO_SEMANTIC"
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
    raw_output: str | None = field(default=None, compare=False)
    command: str | None = field(default=None, compare=False)
    valid: bool = field(default=True, compare=False)
    logprobs: dict[str, float] = field(default_factory=dict, compare=False)
    probability: float | None = field(default=None, compare=False)
    margin: float | None = field(default=None, compare=False)

    @property
    def label(self) -> SemanticLabel:
        if self.reject:
            return SemanticLabel.REJECT
        return SemanticLabel.BREAK if self.break_decision else SemanticLabel.NO_BREAK


@dataclass(frozen=True, slots=True)
class VASDSemDecision:
    semantic: bool
    raw_output: str | None = field(default=None, compare=False)
    command: str | None = field(default=None, compare=False)
    valid: bool = field(default=True, compare=False)
    logprobs: dict[str, float] = field(default_factory=dict, compare=False)
    probability: float | None = field(default=None, compare=False)
    margin: float | None = field(default=None, compare=False)

    @property
    def label(self) -> SemanticLabel:
        return SemanticLabel.SEMANTIC if self.semantic else SemanticLabel.NO_SEMANTIC


@dataclass(frozen=True, slots=True)
class VAEDDecision:
    complete: bool
    raw_output: str | None = field(default=None, compare=False)
    command: str | None = field(default=None, compare=False)
    valid: bool = field(default=True, compare=False)
    logprobs: dict[str, float] = field(default_factory=dict, compare=False)
    probability: float | None = field(default=None, compare=False)
    margin: float | None = field(default=None, compare=False)

    @property
    def label(self) -> SemanticLabel:
        return SemanticLabel.COMPLETE if self.complete else SemanticLabel.INCOMPLETE


@dataclass(frozen=True, slots=True)
class FSMInput:
    audio_chunk: object | None
    speech: bool
    semantic_decision: bool | None = None
    break_decision: bool | None = None
    interrupt_decision: bool | None = None
    playback_active: bool = False
    reject: bool | None = None
    complete: bool | None = None
    model_output: str | None = None
    semantic_command: str | None = None
    semantic_valid: bool | None = None
    request_kind: str | None = None
    semantic_logprobs: dict[str, float] | None = None
    semantic_probability: float | None = None
    semantic_margin: float | None = None
    semantic_accepted: bool | None = None
    semantic_confirmation_count: int | None = None
    break_accepted: bool | None = None
    break_confirmation_count: int | None = None
    completion_accepted: bool | None = None
    completion_confirmation_count: int | None = None
    semantic_endpoint_evaluated: bool = False
    force_decode: bool = False
    decode_reason: str | None = None
    parallel_decisions: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FSMOutput:
    previous_state: InputState
    state: InputState
    event: InputEvent
    interrupt: bool
    prefill_audio: tuple[object, ...] | None
    decode_audio: tuple[object, ...] | None
    semantic_label: SemanticLabel
    speech: bool
    semantic_decision: bool | None
    break_decision: bool | None
    interrupt_decision: bool | None
    playback_active: bool
    reject: bool | None
    complete: bool | None
    timestamp: float
    decision_latency_ms: float | None = None
    model_output: str | None = None
    semantic_command: str | None = None
    semantic_valid: bool | None = None
    request_kind: str | None = None
    semantic_logprobs: dict[str, float] | None = None
    semantic_probability: float | None = None
    semantic_margin: float | None = None
    semantic_accepted: bool | None = None
    semantic_confirmation_count: int | None = None
    break_accepted: bool | None = None
    break_confirmation_count: int | None = None
    completion_accepted: bool | None = None
    completion_confirmation_count: int | None = None
    semantic_endpoint_evaluated: bool = False
    decode_reason: str | None = None
    parallel_decisions: dict[str, object] | None = None

    def as_log(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "previous_state": self.previous_state.value,
            "speech": self.speech,
            "semantic_decision": self.semantic_decision,
            "break_decision": self.break_decision,
            "interrupt_decision": self.interrupt_decision,
            "playback_active": self.playback_active,
            "reject": self.reject,
            "complete": self.complete,
            "semantic_label": self.semantic_label.value,
            "next_state": self.state.value,
            "fsm_event": self.event.value,
            "interrupt": self.interrupt,
            "prefill_audio_chunk_count": len(self.prefill_audio or ()),
            "decode_audio_chunk_count": len(self.decode_audio or ()),
            "decision_latency_ms": self.decision_latency_ms,
            "model_output": self.model_output,
            "semantic_command": self.semantic_command,
            "semantic_valid": self.semantic_valid,
            "request_kind": self.request_kind,
            "semantic_logprobs": self.semantic_logprobs,
            "semantic_probability": self.semantic_probability,
            "semantic_margin": self.semantic_margin,
            "semantic_accepted": self.semantic_accepted,
            "semantic_confirmation_count": self.semantic_confirmation_count,
            "break_accepted": self.break_accepted,
            "break_confirmation_count": self.break_confirmation_count,
            "completion_accepted": self.completion_accepted,
            "completion_confirmation_count": self.completion_confirmation_count,
            "semantic_endpoint_evaluated": self.semantic_endpoint_evaluated,
            "decode_reason": self.decode_reason,
            "parallel_decisions": self.parallel_decisions,
        }


class SemanticVADProvider(Protocol):
    async def decide_sem(self, audio_chunks: Sequence[object], *, context: Mapping[str, object]) -> VASDSemDecision:
        ...

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
        self._silence_interval_started = time.time()
        self._silence_interval_chunks = 0
        self._session_id = ""

    @property
    def candidate_audio(self) -> tuple[object, ...]:
        return tuple(self._candidate_audio)

    @property
    def turn_audio(self) -> tuple[object, ...]:
        return tuple(self._turn_audio)

    def reset(self) -> None:
        self._flush_silence_interval(time.time(), reason="reset", session_id=self._session_id)
        self.state = InputState.SILENCE
        self._candidate_audio.clear()
        self._turn_audio.clear()
        self._silence_interval_started = time.time()
        self._silence_interval_chunks = 0

    def close(self) -> None:
        self._flush_silence_interval(time.time(), reason="close", session_id=self._session_id)

    def record(self, output: FSMOutput, *, context: Mapping[str, object] | None = None) -> None:
        request_id = str((context or {}).get("request_id") or "")
        session_id = request_id.rsplit("-", 1)[0] if request_id.rsplit("-", 1)[-1].isdigit() else request_id
        if session_id:
            self._session_id = session_id
        if output.previous_state == InputState.SILENCE:
            if output.state == InputState.SILENCE:
                self._silence_interval_chunks += 1
                return
            self._flush_silence_interval(output.timestamp, reason="state_change", session_id=session_id)
        LOG.info("semantic_vad_transition %s", json.dumps(output.as_log(), sort_keys=True))
        if output.state == InputState.SILENCE and output.previous_state != InputState.SILENCE:
            self._silence_interval_started = output.timestamp
            self._silence_interval_chunks = 0

    def _flush_silence_interval(self, ended: float, *, reason: str, session_id: str = "") -> None:
        if self._silence_interval_chunks <= 0:
            return
        LOG.info(
            "semantic_vad_state_interval %s",
            json.dumps({
                "state": InputState.SILENCE.value,
                "started": self._silence_interval_started,
                "ended": ended,
                "duration_ms": round((ended - self._silence_interval_started) * 1000, 3),
                "audio_chunk_count": self._silence_interval_chunks,
                "reason": reason,
                "session_id": session_id,
            }, sort_keys=True),
        )
        self._silence_interval_started = ended
        self._silence_interval_chunks = 0

    @staticmethod
    def _chunks(audio_chunk: object) -> tuple[object, ...]:
        if audio_chunk is None:
            return ()
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
        decode_audio: tuple[object, ...] | None = None
        semantic_label = SemanticLabel.NOT_RUN

        if previous == InputState.SILENCE:
            if item.speech:
                self._candidate_audio.clear()
                self._turn_audio.clear()
                self._append(self._candidate_audio, item.audio_chunk)
                self.state = InputState.JUDGE

        elif previous == InputState.JUDGE:
            legacy_break_input = item.semantic_decision is None
            semantic_decision = (
                item.semantic_decision
                if item.semantic_decision is not None
                else item.break_decision
            )
            if semantic_decision is None:
                raise ValueError("Judge requires semantic_decision")
            self._append(self._candidate_audio, item.audio_chunk)
            semantic_label = (
                VASDDecision(bool(item.break_decision), bool(item.reject)).label
                if legacy_break_input
                else (
                    SemanticLabel.SEMANTIC if semantic_decision
                    else SemanticLabel.NO_SEMANTIC
                )
            )
            if semantic_decision:
                self.state = InputState.LISTEN
                event = InputEvent.PREFILL
                interrupt = (
                    bool(item.break_decision and not item.reject)
                    if legacy_break_input
                    else bool(item.playback_active and item.interrupt_decision)
                )
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
            semantic_label = (
                VAEDDecision(item.complete).label
                if item.semantic_endpoint_evaluated
                else SemanticLabel.NOT_RUN
            )
            chunks = self._chunks(item.audio_chunk)
            if chunks:
                self._append(self._turn_audio, item.audio_chunk)
            if item.force_decode or item.complete:
                prefill_audio = chunks or None
                decode_audio = tuple(self._turn_audio)
                self.state = InputState.SILENCE
                event = InputEvent.DECODE
                self._candidate_audio.clear()
                self._turn_audio.clear()
            elif item.speech or item.semantic_endpoint_evaluated:
                prefill_audio = chunks or None
                event = InputEvent.CHUNK_PREFILL
            else:
                event = InputEvent.NO_OP

        else:
            raise ValueError(f"Invalid state: {previous!r}")

        output = FSMOutput(
            previous_state=previous,
            state=self.state,
            event=event,
            interrupt=interrupt,
            prefill_audio=prefill_audio,
            decode_audio=decode_audio,
            semantic_label=semantic_label,
            speech=bool(item.speech),
            semantic_decision=item.semantic_decision,
            break_decision=item.break_decision,
            interrupt_decision=item.interrupt_decision,
            playback_active=item.playback_active,
            reject=item.reject,
            complete=item.complete,
            timestamp=time.time(),
            model_output=item.model_output,
            semantic_command=item.semantic_command,
            semantic_valid=item.semantic_valid,
            request_kind=item.request_kind,
            semantic_logprobs=item.semantic_logprobs,
            semantic_probability=item.semantic_probability,
            semantic_margin=item.semantic_margin,
            semantic_accepted=item.semantic_accepted,
            semantic_confirmation_count=item.semantic_confirmation_count,
            break_accepted=item.break_accepted,
            break_confirmation_count=item.break_confirmation_count,
            completion_accepted=item.completion_accepted,
            completion_confirmation_count=item.completion_confirmation_count,
            semantic_endpoint_evaluated=item.semantic_endpoint_evaluated,
            decode_reason=item.decode_reason,
            parallel_decisions=item.parallel_decisions,
        )
        return output


class SemanticVADController:
    """Run only the semantic decision valid for the FSM's current state."""

    def __init__(
        self,
        provider: SemanticVADProvider,
        *,
        max_buffered_chunks: int = 512,
        vasd_window_ms: int = 8000,
        sem_probability_threshold: float = 0.8,
        sem_margin_threshold: float = 1.5,
        sem_confirmations: int = 1,
        break_probability_threshold: float = 0.8,
        break_margin_threshold: float = 1.5,
        break_confirmations: int = 1,
        complete_probability_threshold: float = 0.9,
        complete_margin_threshold: float = 2.0,
        complete_confirmations: int = 1,
    ) -> None:
        self.provider = provider
        self.fsm = DuplexInputFSM(max_buffered_chunks=max_buffered_chunks)
        self.vasd_window_ms = vasd_window_ms
        self.sem_probability_threshold = sem_probability_threshold
        self.sem_margin_threshold = sem_margin_threshold
        self.sem_confirmations = sem_confirmations
        self.break_probability_threshold = break_probability_threshold
        self.break_margin_threshold = break_margin_threshold
        self.break_confirmations = break_confirmations
        self.complete_probability_threshold = complete_probability_threshold
        self.complete_margin_threshold = complete_margin_threshold
        self.complete_confirmations = complete_confirmations
        self._sem_confirmation_count = 0
        self._break_confirmation_count = 0
        self._complete_confirmation_count = 0

    @staticmethod
    def _qualifies(decision, probability_threshold: float, margin_threshold: float) -> bool:
        return bool(
            getattr(decision, "semantic", getattr(decision, "break_decision", False))
            and (
                (decision.probability is None and decision.margin is None)
                or (
                    decision.probability is not None
                    and decision.margin is not None
                    and decision.probability >= probability_threshold
                    and decision.margin >= margin_threshold
                )
            )
        )

    def _vasd_audio(self, audio_chunk: object) -> tuple[object, ...]:
        chunks = self.fsm.semantic_audio_with(audio_chunk)
        if self.vasd_window_ms <= 0 or not chunks:
            return chunks
        selected: list[object] = []
        duration_ms = 0.0
        for chunk in reversed(chunks):
            chunk_ms = _chunk_duration_ms(chunk) if isinstance(chunk, Mapping) else 0.0
            if chunk_ms <= 0:
                return chunks
            if selected and duration_ms + chunk_ms > self.vasd_window_ms:
                break
            selected.append(chunk)
            duration_ms += chunk_ms
            if duration_ms >= self.vasd_window_ms:
                break
        return tuple(reversed(selected))

    async def _process_judge(
        self,
        audio_chunk: object,
        *,
        speech: bool,
        semantic_context: Mapping[str, object],
    ) -> FSMOutput:
        self._complete_confirmation_count = 0
        started = time.monotonic()
        audio = self._vasd_audio(audio_chunk)
        playback_active = bool(semantic_context.get("tts_playback_active", False))
        decide_sem = getattr(self.provider, "decide_sem", None)
        if decide_sem is None:
            async def decide_sem(audio_chunks, *, context):
                legacy = await self.provider.decide_break(audio_chunks, context=context)
                return VASDSemDecision(
                    legacy.break_decision and not legacy.reject,
                    legacy.raw_output, legacy.command, legacy.valid,
                    legacy.logprobs, legacy.probability, legacy.margin,
                )
        sem_task = asyncio.create_task(decide_sem(audio, context=semantic_context))
        break_task = (
            asyncio.create_task(self.provider.decide_break(audio, context=semantic_context))
            if playback_active else None
        )
        sem_decision = await sem_task
        break_decision = await break_task if break_task is not None else None

        sem_qualifies = self._qualifies(
            sem_decision, self.sem_probability_threshold, self.sem_margin_threshold)
        self._sem_confirmation_count = self._sem_confirmation_count + 1 if sem_qualifies else 0
        sem_accepted = sem_qualifies and self._sem_confirmation_count >= self.sem_confirmations

        break_qualifies = bool(
            break_decision is not None
            and self._qualifies(
                break_decision,
                self.break_probability_threshold,
                self.break_margin_threshold,
            )
        )
        self._break_confirmation_count = self._break_confirmation_count + 1 if break_qualifies else 0
        break_accepted = bool(
            break_qualifies
            and self._break_confirmation_count >= self.break_confirmations
        )
        parallel_decisions = {
            "VASD_SEM": {
                "raw_output": sem_decision.raw_output,
                "command": sem_decision.command,
                "label": sem_decision.label.value,
                "logprobs": sem_decision.logprobs,
                "probability": sem_decision.probability,
                "margin": sem_decision.margin,
                "accepted": sem_accepted,
                "confirmation_count": self._sem_confirmation_count,
            },
            "VASD_BREAK": None if break_decision is None else {
                "raw_output": break_decision.raw_output,
                "command": break_decision.command,
                "label": break_decision.label.value,
                "logprobs": break_decision.logprobs,
                "probability": break_decision.probability,
                "margin": break_decision.margin,
                "accepted": break_accepted,
                "confirmation_count": self._break_confirmation_count,
            },
        }
        output = replace(self.fsm.step(FSMInput(
            audio_chunk=audio_chunk,
            speech=speech,
            semantic_decision=sem_accepted,
            break_decision=(break_decision.break_decision if break_decision is not None else None),
            interrupt_decision=break_accepted,
            playback_active=playback_active,
            reject=False,
            model_output=sem_decision.raw_output,
            semantic_command=sem_decision.command,
            semantic_valid=sem_decision.valid,
            request_kind="VASD_SEM",
            semantic_logprobs=sem_decision.logprobs,
            semantic_probability=sem_decision.probability,
            semantic_margin=sem_decision.margin,
            semantic_accepted=sem_accepted,
            semantic_confirmation_count=self._sem_confirmation_count,
            break_accepted=break_accepted,
            break_confirmation_count=self._break_confirmation_count,
            parallel_decisions=parallel_decisions,
        )), semantic_label=sem_decision.label,
            decision_latency_ms=(time.monotonic() - started) * 1000)
        if sem_accepted or output.state != InputState.JUDGE:
            self._sem_confirmation_count = 0
            self._break_confirmation_count = 0
        elif not playback_active:
            self._break_confirmation_count = 0
        self.fsm.record(output, context=semantic_context)
        return output

    def reset(self) -> None:
        self.fsm.reset()
        self._sem_confirmation_count = 0
        self._break_confirmation_count = 0
        self._complete_confirmation_count = 0

    async def process(
        self,
        audio_chunk: object,
        *,
        speech: bool,
        speech_stopped: bool = False,
        force_decode: bool = False,
        decode_reason: str | None = None,
        context: Mapping[str, object] | None = None,
    ) -> FSMOutput:
        semantic_context = context or {}
        if self.fsm.state == InputState.JUDGE:
            return await self._process_judge(
                audio_chunk, speech=speech, semantic_context=semantic_context)
        if self.fsm.state == InputState.LISTEN:
            if force_decode:
                self._complete_confirmation_count = 0
                output = self.fsm.step(FSMInput(
                    audio_chunk=None,
                    speech=False,
                    complete=False,
                    force_decode=True,
                    decode_reason=decode_reason,
                ))
                self.fsm.record(output, context=semantic_context)
                return output
            if speech and not speech_stopped:
                output = self.fsm.step(FSMInput(
                    audio_chunk=audio_chunk,
                    speech=True,
                    complete=False,
                    semantic_endpoint_evaluated=False,
                ))
                self.fsm.record(output, context=semantic_context)
                return output
            if not speech_stopped:
                output = self.fsm.step(FSMInput(
                    audio_chunk=None,
                    speech=False,
                    complete=False,
                    semantic_endpoint_evaluated=False,
                ))
                self.fsm.record(output, context=semantic_context)
                return output
            started = time.monotonic()
            decision = await self.provider.decide_complete(
                self.fsm.semantic_audio_with(audio_chunk),
                context=semantic_context,
            )
            qualifies = bool(
                decision.complete
                and decision.probability is not None
                and decision.margin is not None
                and decision.probability >= self.complete_probability_threshold
                and decision.margin >= self.complete_margin_threshold
            )
            self._complete_confirmation_count = self._complete_confirmation_count + 1 if qualifies else 0
            accepted = qualifies and self._complete_confirmation_count >= self.complete_confirmations
            output = replace(self.fsm.step(FSMInput(
                audio_chunk=audio_chunk,
                speech=speech,
                complete=accepted,
                model_output=decision.raw_output,
                semantic_command=decision.command,
                semantic_valid=decision.valid,
                request_kind="VAED",
                semantic_logprobs=decision.logprobs,
                semantic_probability=decision.probability,
                semantic_margin=decision.margin,
                completion_accepted=accepted,
                completion_confirmation_count=self._complete_confirmation_count,
                semantic_endpoint_evaluated=True,
                decode_reason="semantic_complete" if accepted else None,
            )), decision_latency_ms=(time.monotonic() - started) * 1000)
            if accepted:
                self._complete_confirmation_count = 0
            self.fsm.record(output, context=semantic_context)
            return output
        output = self.fsm.step(FSMInput(audio_chunk=audio_chunk, speech=speech))
        self._sem_confirmation_count = 0
        self._break_confirmation_count = 0
        self.fsm.record(output, context=semantic_context)
        if speech and output.state == InputState.JUDGE:
            return await self._process_judge(
                None, speech=True, semantic_context=semantic_context)
        return output


@dataclass(frozen=True, slots=True)
class SemanticVADConfig:
    threshold: float = 0.5
    prefix_padding_ms: int = 300
    silence_duration_ms: int = 500
    min_speech_duration_ms: int = 96
    max_buffered_chunks: int = 512
    vasd_window_ms: int = 8000
    sem_probability_threshold: float = 0.8
    sem_margin_threshold: float = 1.5
    sem_confirmations: int = 1
    break_probability_threshold: float = 0.8
    break_margin_threshold: float = 1.5
    break_confirmations: int = 1
    complete_probability_threshold: float = 0.9
    complete_margin_threshold: float = 2.0
    complete_confirmations: int = 1
    incomplete_silence_timeout_ms: int = 8000

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "SemanticVADConfig":
        allowed = {
            "type",
            "threshold",
            "prefix_padding_ms",
            "silence_duration_ms",
            "min_speech_duration_ms",
            "max_buffered_chunks",
            "vasd_window_ms",
            "sem_probability_threshold",
            "sem_margin_threshold",
            "sem_confirmations",
            "break_probability_threshold",
            "break_margin_threshold",
            "break_confirmations",
            "complete_probability_threshold",
            "complete_margin_threshold",
            "complete_confirmations",
            "incomplete_silence_timeout_ms",
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
        vasd_window_ms = value.get("vasd_window_ms", 8000)
        if (
            not isinstance(vasd_window_ms, int | float)
            or isinstance(vasd_window_ms, bool)
            or not math.isfinite(float(vasd_window_ms))
            or float(vasd_window_ms) <= 0
        ):
            raise ValueError("semantic_vad.vasd_window_ms must be a positive number")
        sem_probability = value.get("sem_probability_threshold", 0.8)
        if (
            not isinstance(sem_probability, int | float)
            or isinstance(sem_probability, bool)
            or not math.isfinite(float(sem_probability))
            or not 0.0 <= float(sem_probability) <= 1.0
        ):
            raise ValueError("semantic_vad.sem_probability_threshold must be within [0, 1]")
        sem_margin = value.get("sem_margin_threshold", 1.5)
        if (
            not isinstance(sem_margin, int | float)
            or isinstance(sem_margin, bool)
            or not math.isfinite(float(sem_margin))
            or float(sem_margin) < 0
        ):
            raise ValueError("semantic_vad.sem_margin_threshold must be non-negative")
        sem_confirmations = value.get("sem_confirmations", 1)
        if (
            not isinstance(sem_confirmations, int)
            or isinstance(sem_confirmations, bool)
            or sem_confirmations <= 0
        ):
            raise ValueError("semantic_vad.sem_confirmations must be a positive integer")
        break_probability = value.get("break_probability_threshold", 0.8)
        if (
            not isinstance(break_probability, int | float)
            or isinstance(break_probability, bool)
            or not math.isfinite(float(break_probability))
            or not 0.0 <= float(break_probability) <= 1.0
        ):
            raise ValueError("semantic_vad.break_probability_threshold must be within [0, 1]")
        break_margin = value.get("break_margin_threshold", 1.5)
        if (
            not isinstance(break_margin, int | float)
            or isinstance(break_margin, bool)
            or not math.isfinite(float(break_margin))
            or float(break_margin) < 0
        ):
            raise ValueError("semantic_vad.break_margin_threshold must be non-negative")
        break_confirmations = value.get("break_confirmations", 1)
        if (
            not isinstance(break_confirmations, int)
            or isinstance(break_confirmations, bool)
            or break_confirmations <= 0
        ):
            raise ValueError("semantic_vad.break_confirmations must be a positive integer")
        complete_probability = value.get("complete_probability_threshold", 0.9)
        if (
            not isinstance(complete_probability, int | float)
            or isinstance(complete_probability, bool)
            or not math.isfinite(float(complete_probability))
            or not 0.0 <= float(complete_probability) <= 1.0
        ):
            raise ValueError("semantic_vad.complete_probability_threshold must be within [0, 1]")
        complete_margin = value.get("complete_margin_threshold", 2.0)
        if (
            not isinstance(complete_margin, int | float)
            or isinstance(complete_margin, bool)
            or not math.isfinite(float(complete_margin))
            or float(complete_margin) < 0
        ):
            raise ValueError("semantic_vad.complete_margin_threshold must be non-negative")
        confirmations = value.get("complete_confirmations", 1)
        if not isinstance(confirmations, int) or isinstance(confirmations, bool) or confirmations <= 0:
            raise ValueError("semantic_vad.complete_confirmations must be a positive integer")
        incomplete_timeout = value.get("incomplete_silence_timeout_ms", 8000)
        if (
            not isinstance(incomplete_timeout, int | float)
            or isinstance(incomplete_timeout, bool)
            or not math.isfinite(float(incomplete_timeout))
            or float(incomplete_timeout) < 0
        ):
            raise ValueError("semantic_vad.incomplete_silence_timeout_ms must be non-negative")
        return cls(
            threshold=float(threshold),
            max_buffered_chunks=max_chunks,
            vasd_window_ms=int(vasd_window_ms),
            sem_probability_threshold=float(sem_probability),
            sem_margin_threshold=float(sem_margin),
            sem_confirmations=sem_confirmations,
            break_probability_threshold=float(break_probability),
            break_margin_threshold=float(break_margin),
            break_confirmations=break_confirmations,
            complete_probability_threshold=float(complete_probability),
            complete_margin_threshold=float(complete_margin),
            complete_confirmations=confirmations,
            incomplete_silence_timeout_ms=int(incomplete_timeout),
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
        self.last_avad: dict[str, object] = {}
        self._semantic_waiting = False
        self._incomplete_silence_started: float | None = None
        self.controller = SemanticVADController(
            provider,
            max_buffered_chunks=config.max_buffered_chunks,
            vasd_window_ms=config.vasd_window_ms,
            sem_probability_threshold=config.sem_probability_threshold,
            sem_margin_threshold=config.sem_margin_threshold,
            sem_confirmations=config.sem_confirmations,
            break_probability_threshold=config.break_probability_threshold,
            break_margin_threshold=config.break_margin_threshold,
            break_confirmations=config.break_confirmations,
            complete_probability_threshold=config.complete_probability_threshold,
            complete_margin_threshold=config.complete_margin_threshold,
            complete_confirmations=config.complete_confirmations,
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
        self.controller.reset()
        self._prefix_audio.clear()
        self._semantic_waiting = False
        self._incomplete_silence_started = None
        reset = getattr(self.vad, "reset", None)
        if callable(reset):
            reset()

    def close(self) -> None:
        self.controller.fsm.close()

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
        self.last_avad = {
            "is_speech": bool(getattr(vad_result, "is_speech", vad_result.speech_active)),
            "speech_active": bool(vad_result.speech_active),
            "speech_started": bool(getattr(vad_result, "speech_started", False)),
            "speech_stopped": bool(getattr(vad_result, "speech_stopped", False)),
            "speech_probability": float(getattr(vad_result, "speech_probability", 0.0)),
            "semantic_waiting": self._semantic_waiting,
            "incomplete_silence_elapsed_ms": (
                0.0
                if self._incomplete_silence_started is None
                else (time.monotonic() - self._incomplete_silence_started) * 1000
            ),
        }
        if self._semantic_waiting and vad_result.speech_active:
            self._semantic_waiting = False
            self._incomplete_silence_started = None
            self.last_avad["semantic_waiting"] = False
            self.last_avad["incomplete_silence_elapsed_ms"] = 0.0
        if (
            self._semantic_waiting
            and not vad_result.speech_active
            and self._incomplete_silence_started is not None
            and self.config.incomplete_silence_timeout_ms > 0
            and (time.monotonic() - self._incomplete_silence_started) * 1000
            >= self.config.incomplete_silence_timeout_ms
        ):
            output = await self.controller.process(
                None,
                speech=False,
                force_decode=True,
                decode_reason="incomplete_silence_timeout",
                context=context,
            )
            self._semantic_waiting = False
            self._incomplete_silence_started = None
            self.last_avad["semantic_waiting"] = False
            commands = [{
                "type": "input_audio_buffer.commit",
                "final": True,
                "create_response": True,
            }]
            return output, commands
        state_before = self.controller.fsm.state
        controller_chunk: object = chunk
        if state_before == InputState.SILENCE and vad_result.speech_active and self._prefix_audio:
            controller_chunk = AudioChunkBatch((*self._prefix_audio, chunk))
            self._prefix_audio.clear()
        output = await self.controller.process(
            controller_chunk,
            speech=vad_result.speech_active,
            speech_stopped=bool(getattr(vad_result, "speech_stopped", False)),
            context=context,
        )
        if output.semantic_endpoint_evaluated and not output.completion_accepted:
            self._semantic_waiting = True
            self._incomplete_silence_started = time.monotonic()
            self.last_avad["semantic_waiting"] = True
            self.last_avad["incomplete_silence_elapsed_ms"] = 0.0
        elif output.event == InputEvent.DECODE:
            self._semantic_waiting = False
            self._incomplete_silence_started = None
            self.last_avad["semantic_waiting"] = False
        if (
            state_before == InputState.SILENCE
            and output.state == InputState.SILENCE
            and not vad_result.speech_active
        ):
            self._remember_prefix(chunk)
        commands: list[dict[str, object]] = []
        if output.event == InputEvent.PREFILL:
            if output.interrupt:
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


_VASD_SEM_CODES = {"有": "SEMANTIC", "无": "NO_SEMANTIC"}
_VASD_BREAK_CODES = {"有": BREAK_TOKEN, "无": NO_BREAK_TOKEN}
_VAED_CODES = {"已": COMPLETE_TOKEN, "未": INCOMPLETE_TOKEN}
_CODE_TOKEN_IDS = {
    "有": 18830,
    "无": 42192,
    "已": 36667,
    "未": 38342,
}

DEFAULT_VASD_SEM_PROMPT = """你是实时语音语义有效性分类器。
请判断当前音频窗口是否包含可识别、可进入对话上下文的语言语义。

判定为“有”：
- 用户说出了可以理解的词语、句子、问题、请求、陈述、附和或反馈。
- 内容可能完整也可能未完整，但已经包含可识别语义。

判定为“无”：
- 静音、环境噪声、纯非语言声音。
- 无法辨认或不包含可理解语言语义的声音。

只能输出“有”或“无”之一；不得输出空格、换行、解释或任何其他内容。"""

DEFAULT_VASD_BREAK_PROMPT = """你是一个实时语音语义边界判断助手。
你的任务是根据输入的语音信号，隐式理解语音内容，判断当前语音是否已经表达出打断助手的意图。

判定为“有”：
- 叫停或插话，例如“等等”“先别说”“我想问”。
- 反驳或否定，例如“不对”“你错了”“我不同意”。
- 急切表达、抢话或明确转移话题。

判定为“无”：
- 语气词，例如“嗯”“哦”“啊”“呃”“Well”“Oh”“Hum”。
- 附和，例如“对对对”“嗯你说得对”“是的”“挺好的”“you are right”“yeah”“Oh, good”。
- 表达继续听的兴趣，例如“继续”“然后呢”“有点意思”。
- 非语言声音，例如笑声、咳嗽声、背景声或噪声。

只能输出“有”或“无”之一；不得输出空格、换行、解释或任何其他内容。"""

# Backward-compatible import name for callers that still expect one VASD prompt.
DEFAULT_VASD_PROMPT = DEFAULT_VASD_BREAK_PROMPT

DEFAULT_VAED_PROMPT = """你是一个实时语音语义边界判断助手。
你的任务是根据输入的语音信号，隐式理解语音内容，判断当前累计语音是否已经形成完整表达。

判定为“已”：
- 已表达完整语义。
- 句子自然结束，例如陈述、评价、祈使、感叹或附和。
- 存在明确交接信号，例如提问、请求反馈或征询意见。

判定为“未”：
- 句子明显缺失、截断或悬空。
- 表达仍在进行中。
- 正在思考或犹豫，语义尚未收束。

只能输出“已”或“未”之一；不得输出空格、换行、解释或任何其他内容。"""

DEFAULT_CHAT_PROMPT = f"""你是一个实时语音对话助手。请直接理解用户音频并回答用户的问题。
回复应自然、简洁、口语化，优先使用一到三句话；不要输出 Markdown，不要展示思考过程。
始终使用用户所使用的语言回答。

{INTERRUPTED_CONTEXT_INSTRUCTION}"""
CHAT_AUDIO_INSTRUCTION = "这是用户对你的提问。请直接回答问题，不要转写、复述或描述这段音频。"


class MiMoSemanticVADProvider:
    """Use the existing MiMo audio chat endpoint for VASD and VAED."""

    def __init__(self, client, mimo_url: str, *, model: str = "mimo-v2.6-flash") -> None:
        self.client = client
        self.mimo_url = mimo_url.rstrip("/")
        self.model = model

    async def decide_sem(self, audio_chunks, *, context):
        result = await self._classify(
            audio_chunks,
            system=_prompt_from_context(
                context, "vasd_sem_prompt", DEFAULT_VASD_SEM_PROMPT),
            request_kind="VASD_SEM",
            code_map=_VASD_SEM_CODES,
            context=context,
        )
        command = result["command"]
        return VASDSemDecision(
            command == "SEMANTIC",
            result["raw_output"], command, True,
            result["logprobs"], result["probability"], result["margin"],
        )

    async def decide_break(self, audio_chunks, *, context):
        result = await self._classify(
            audio_chunks,
            system=_prompt_from_context(
                context,
                "vasd_break_prompt",
                _prompt_from_context(
                    context, "vasd_prompt", DEFAULT_VASD_BREAK_PROMPT),
            ),
            request_kind="VASD_BREAK",
            code_map=_VASD_BREAK_CODES,
            context=context,
        )
        command = result["command"]
        if command == BREAK_TOKEN:
            return VASDDecision(True, False, result["raw_output"], command, True,
                                result["logprobs"], result["probability"], result["margin"])
        if command == NO_BREAK_TOKEN:
            return VASDDecision(False, False, result["raw_output"], command, True,
                                result["logprobs"], result["probability"], result["margin"])
        raise ValueError(f"Unexpected VASD command: {command!r}")

    async def decide_complete(self, audio_chunks, *, context):
        result = await self._classify(
            audio_chunks,
            system=_prompt_from_context(context, "vaed_prompt", DEFAULT_VAED_PROMPT),
            request_kind="VAED",
            code_map=_VAED_CODES,
            context=context,
        )
        command = result["command"]
        return VAEDDecision(command == COMPLETE_TOKEN, result["raw_output"], command, True,
                            result["logprobs"], result["probability"], result["margin"])

    async def _classify(self, audio_chunks, *, system, request_kind, code_map, context):
        wav = audio_chunks_to_wav(audio_chunks)
        token_ids = [_CODE_TOKEN_IDS[code] for code in code_map]
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
            "max_tokens": 1,
            "temperature": 0.0,
            "stream": False,
            "logprobs": True,
            "top_logprobs": 0,
            "logprob_token_ids": token_ids,
            "allowed_token_ids": token_ids,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        request_id = str(context.get("request_id") or f"semantic-vad-{time.time_ns()}")
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions",
            json=payload,
            headers={"X-Request-Id": f"{request_id}-{request_kind.lower()}"},
        ) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"MiMo semantic VAD HTTP {response.status}")
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
            position = choice["logprobs"]["content"][0]
            candidates = position["top_logprobs"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("MiMo semantic VAD returned no usable classifier logprobs") from exc
        if not isinstance(content, str):
            raise ValueError("MiMo semantic VAD classifier content must be text")
        code_logprobs = {
            item["token"]: float(item["logprob"])
            for item in candidates
            if isinstance(item, dict) and item.get("token") in code_map
        }
        if set(code_logprobs) != set(code_map):
            raise ValueError(
                f"MiMo semantic VAD logprobs missing candidates: expected {sorted(code_map)}, "
                f"got {sorted(code_logprobs)}"
            )
        selected_code = max(code_logprobs, key=code_logprobs.get)
        raw_output = content
        sampled_code = content
        if sampled_code not in code_map:
            raise InvalidSemanticCommand(request_kind, content, tuple(code_map))
        if sampled_code != selected_code:
            raise ValueError(
                f"MiMo semantic VAD sampled code {sampled_code!r} differs from logprob argmax {selected_code!r}"
            )
        canonical_logprobs = {code_map[code]: value for code, value in code_logprobs.items()}
        ordered = sorted(code_logprobs.values(), reverse=True)
        maximum = ordered[0]
        denominator = sum(math.exp(value - maximum) for value in ordered)
        probability = 1.0 / denominator
        margin = ordered[0] - ordered[1] if len(ordered) > 1 else math.inf
        command = code_map[selected_code]
        LOG.info(
            "mimo_semantic_logprobs request_id=%s kind=%s code=%s command=%s "
            "probability=%.6f margin=%.6f logprobs=%s",
            request_id,
            request_kind,
            selected_code,
            command,
            probability,
            margin,
            json.dumps(canonical_logprobs, sort_keys=True),
        )
        return {
            "raw_output": selected_code,
            "command": command,
            "logprobs": canonical_logprobs,
            "probability": probability,
            "margin": margin,
        }


def _prompt_from_context(context: Mapping[str, object], key: str, default: str) -> str:
    value = context.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{key} must be a non-empty string of at most 4096 characters")
    return value


class MiMoChatProvider:
    """Stream text replies from the same MiMo backbone after an FSM DECODE."""

    def __init__(self, client, mimo_url: str, *, model: str = "mimo-v2.6-flash") -> None:
        self.client = client
        self.mimo_url = mimo_url.rstrip("/")
        self.model = model

    async def stream_reply(self, audio_chunks, *, history, prompt, context):
        system = _prompt_from_context({"chat_prompt": prompt}, "chat_prompt", DEFAULT_CHAT_PROMPT)
        messages: list[dict[str, object]] = [{"role": "system", "content": system}]
        for turn in history[-4:]:
            audio_data = turn.get("audio_wav") if isinstance(turn, Mapping) else None
            assistant = turn.get("assistant") if isinstance(turn, Mapping) else None
            if isinstance(audio_data, str) and audio_data:
                messages.append({"role": "user", "content": [
                    _chat_audio_part(audio_data),
                    {"type": "text", "text": CHAT_AUDIO_INSTRUCTION},
                ]})
            if isinstance(assistant, str) and assistant:
                messages.append({"role": "assistant", "content": assistant})
        wav = audio_chunks_to_wav(audio_chunks)
        if len(wav) > 3 * 1024 * 1024:
            raise ValueError("Chat audio exceeds 3 MiB")
        wav_b64 = base64.b64encode(wav).decode("ascii")
        messages.append({"role": "user", "content": [
            _chat_audio_part(wav_b64),
            {"type": "text", "text": CHAT_AUDIO_INSTRUCTION},
        ]})
        request_id = str(context.get("request_id") or f"semantic-chat-{time.time_ns()}")
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 512,
            "temperature": 0.0,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        async with self.client.post(
            self.mimo_url + "/v1/chat/completions",
            json=payload,
            headers={"X-Request-Id": f"{request_id}-chat"},
        ) as response:
            if response.status != 200:
                body = await response.read()
                raise RuntimeError(f"MiMo Chat HTTP {response.status}: {body[:200]!r}")
            finish_reason = None
            async for data in _sse_data(response.content):
                if data == "[DONE]":
                    if finish_reason is None:
                        raise RuntimeError("MiMo Chat ended without finish_reason")
                    return
                event = json.loads(data)
                if not isinstance(event, dict) or event.get("error"):
                    raise RuntimeError("MiMo Chat returned an error event")
                for choice in event.get("choices", []):
                    delta = choice.get("delta", {})
                    text = delta.get("content")
                    if isinstance(text, str) and text:
                        yield text
                    reason = choice.get("finish_reason")
                    if reason is not None:
                        finish_reason = reason
            raise RuntimeError("MiMo Chat disconnected before DONE")


def _chat_audio_part(wav_b64: str) -> dict[str, object]:
    return {
        "type": "input_audio",
        "input_audio": {"data": wav_b64, "format": "wav"},
    }


async def _sse_data(stream):
    fields: list[str] = []
    async for raw in stream:
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if fields:
                yield "\n".join(fields)
                fields.clear()
        elif line.startswith("data:"):
            fields.append(line[5:].removeprefix(" "))
    if fields:
        raise RuntimeError("MiMo Chat SSE ended inside an event")


class InvalidSemanticCommand(ValueError):
    def __init__(self, kind: str, raw_output: str, allowed: Sequence[str]) -> None:
        self.kind = kind
        self.raw_output = raw_output
        self.normalized = raw_output.strip()
        self.allowed = tuple(allowed)
        super().__init__(
            f"Invalid {kind} command {self.normalized!r}; expected exactly one of {self.allowed!r}"
        )


def _strict_command(content: str, allowed: Sequence[str], kind: str) -> str:
    normalized = content.strip()
    if normalized not in allowed:
        LOG.error(
            "mimo_semantic_output_invalid kind=%s raw=%s allowed=%s",
            kind,
            json.dumps(content, ensure_ascii=True),
            list(allowed),
        )
        raise InvalidSemanticCommand(kind, content, allowed)
    return normalized


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
