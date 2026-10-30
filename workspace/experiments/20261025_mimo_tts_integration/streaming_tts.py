"""True incremental-text client for the CosyVoice submit/poll API."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import time
from typing import AsyncIterator, Mapping
import uuid

from aiohttp import ClientTimeout


MAX_TTS_TEXT = 500
MAX_TTS_SECONDS = 180


@dataclass(frozen=True, slots=True)
class PCMChunk:
    pcm: bytes
    sample_rate_hz: int
    request_id: str


class IncrementalTextChunker:
    """Emit low-latency readable chunks without waiting for the whole reply."""

    boundaries = frozenset("，。！？；：,.!?;:\n")

    def __init__(self, *, min_chars: int = 8, max_chars: int = 48) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.pending = ""

    def feed(self, text: str) -> list[str]:
        self.pending += text
        chunks: list[str] = []
        while True:
            boundary = self._boundary()
            if boundary is None:
                break
            chunk = self.pending[:boundary].strip()
            self.pending = self.pending[boundary:]
            if chunk:
                chunks.append(chunk)
        return chunks

    def flush(self) -> list[str]:
        chunk = self.pending.strip()
        self.pending = ""
        return [chunk] if chunk else []

    def _boundary(self) -> int | None:
        if len(self.pending) >= self.min_chars:
            limit = min(len(self.pending), self.max_chars)
            for index in range(self.min_chars - 1, limit):
                if self.pending[index] in self.boundaries:
                    return index + 1
        if len(self.pending) >= self.max_chars:
            split = self.pending.rfind(" ", self.min_chars, self.max_chars)
            return split + 1 if split >= self.min_chars else self.max_chars
        return None


class WeChatStreamingTTSSession:
    def __init__(
        self,
        client,
        tts_url: str,
        *,
        reg_id: str,
        speed: float,
        target_rms: float,
        context: Mapping[str, object],
    ) -> None:
        if not isinstance(reg_id, str) or not reg_id.strip() or len(reg_id) > 100:
            raise ValueError("TTS reg_id must be a non-empty string of at most 100 characters")
        if not math.isfinite(speed) or not 0.5 <= speed <= 2.0:
            raise ValueError("TTS speed must be within [0.5, 2.0]")
        if not math.isfinite(target_rms) or not -40 <= target_rms <= -10:
            raise ValueError("TTS target_rms must be within [-40, -10]")
        self.client = client
        self.tts_url = tts_url.rstrip("/")
        self.reg_id = reg_id.strip()
        self.speed = speed
        self.target_rms = target_rms
        self.task_id = "svad-" + uuid.uuid4().hex
        self.trace_id = str(context.get("request_id") or self.task_id)
        self.text_idx = 0
        self.started = False
        self.finished = False
        self.total_chars = 0

    async def submit_text(self, text: str, *, final: bool = False) -> None:
        if self.finished:
            raise RuntimeError("TTS text stream is already finished")
        spoken = text.strip()
        if not spoken and not final:
            return
        if len(spoken) > MAX_TTS_TEXT:
            raise ValueError(f"TTS text chunk exceeds {MAX_TTS_TEXT} characters")
        self.total_chars += len(spoken)
        if self.total_chars > 4096:
            raise ValueError("TTS response text exceeds 4096 characters")
        payload = {
            "task_id": self.task_id,
            "reg_id": self.reg_id,
            "text": spoken,
            "is_streaming": True,
            "is_text_streaming": True,
            "text_idx": self.text_idx,
            "is_text_complete": final,
            "tts_strategy": "EagerTTSStrategy",
            "speed": self.speed,
            "target_rms": self.target_rms,
            "trace_msgid": self.trace_id,
        }
        async with self.client.post(
            self.tts_url + "/submit",
            json=payload,
            timeout=ClientTimeout(total=30, connect=10, sock_read=20),
        ) as response:
            body = await response.read()
            if response.status != 200:
                raise RuntimeError(f"TTS submit HTTP {response.status}: {body[:300]!r}")
            try:
                submitted = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("TTS submit returned invalid JSON") from error
            if not isinstance(submitted, dict) or int(submitted.get("ret", -1)) != 0:
                raise RuntimeError(str(submitted.get("message") or "TTS submit failed"))
        self.started = True
        self.text_idx += 1
        self.finished = final

    async def finish(self) -> None:
        if self.finished:
            return
        await self.submit_text("", final=True)

    async def stream_pcm(self) -> AsyncIterator[PCMChunk]:
        deadline = time.monotonic() + MAX_TTS_SECONDS
        total_samples = 0
        sample_rate = None
        while True:
            if not self.started:
                await asyncio.sleep(0.01)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("TTS polling timed out")
            async with self.client.post(
                self.tts_url + "/poll",
                json={
                    "task_id": self.task_id,
                    "speech_idx": -1,
                    "trace_msgid": self.trace_id,
                },
                timeout=ClientTimeout(
                    total=min(20, max(1, remaining)), connect=10,
                    sock_read=min(15, max(1, remaining)),
                ),
            ) as response:
                body = await response.read()
                if response.status != 200:
                    raise RuntimeError(f"TTS poll HTTP {response.status}: {body[:300]!r}")
            separator = body.find(b"\0")
            meta_bytes = body if separator < 0 else body[:separator]
            pcm = b"" if separator < 0 else body[separator + 1:]
            try:
                meta = json.loads(meta_bytes)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RuntimeError("TTS poll returned invalid metadata") from error
            if not isinstance(meta, dict) or int(meta.get("ret", -1)) != 0:
                raise RuntimeError(str(meta.get("message") or "TTS poll failed"))
            try:
                current_rate = int(meta.get("sample_rate", 24000))
            except (TypeError, ValueError) as error:
                raise RuntimeError("TTS poll returned invalid sample_rate") from error
            if not 8000 <= current_rate <= 96000:
                raise RuntimeError(f"TTS sample rate is out of range: {current_rate}")
            if sample_rate is not None and sample_rate != current_rate:
                raise RuntimeError("TTS sample rate changed within one task")
            sample_rate = current_rate
            if len(pcm) % 2:
                raise RuntimeError("TTS returned incomplete PCM16 data")
            if pcm:
                total_samples += len(pcm) // 2
                if total_samples > sample_rate * MAX_TTS_SECONDS:
                    raise RuntimeError("TTS audio exceeds the duration budget")
                yield PCMChunk(pcm, sample_rate, self.task_id)
            if meta.get("is_complete"):
                if total_samples == 0:
                    raise RuntimeError("TTS returned empty PCM audio")
                return
            if not pcm:
                await asyncio.sleep(0.02)


class WeChatStreamingTTSProvider:
    def __init__(self, client, tts_url: str) -> None:
        self.client = client
        self.tts_url = tts_url.rstrip("/")

    def create_stream(
        self,
        *,
        reg_id: str,
        speed: float,
        target_rms: float,
        context: Mapping[str, object],
    ) -> WeChatStreamingTTSSession:
        return WeChatStreamingTTSSession(
            self.client,
            self.tts_url,
            reg_id=reg_id,
            speed=speed,
            target_rms=target_rms,
            context=context,
        )
