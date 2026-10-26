"""Manual-turn MiMo content streaming and ordered independent TTS synthesis."""

import asyncio
import base64
from dataclasses import dataclass
import importlib.util
import io
import json
import logging
from pathlib import Path
import wave

from aiohttp import ClientSession, ClientTimeout


ROOT = Path(__file__).resolve().parents[3]
SPLITTER_PATH = ROOT / "vllm-omni/vllm_omni/entrypoints/openai/speech_text_splitter.py"
_spec = importlib.util.spec_from_file_location("mimo_tts_speech_splitter", SPLITTER_PATH)
_splitter_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_splitter_module)
SpeechTextSplitter = _splitter_module.SpeechTextSplitter
LOG = logging.getLogger("mimo_tts")
MAX_TEXT = 4096
MAX_SEGMENT = 320
MAX_AUDIO_BYTES = 3 * 1024 * 1024
SYSTEM = (
    "\u4f60\u662f\u8bed\u97f3\u5bf9\u8bdd\u52a9\u624b\u3002"
    "\u76f4\u63a5\u56de\u7b54\u7528\u6237\uff0c\u9ed8\u8ba4\u7b80\u77ed\u3001"
    "\u81ea\u7136\uff0c\u7528\u4e00\u5230\u4e09\u53e5\u8bdd\u3002"
    "\u8f93\u51fa\u9002\u5408\u6717\u8bfb\u7684\u7eaf\u6587\u672c\uff0c"
    "\u4e0d\u4f7f\u7528Markdown\uff0c\u4e0d\u8f93\u51fa\u601d\u8003\u8fc7\u7a0b\u3002"
)


class PipelineError(RuntimeError):
    pass


def validate_audio(audio):
    if not isinstance(audio, dict) or audio.get("format") != "wav":
        raise ValueError("Audio must be a WAV object.")
    encoded = audio.get("data")
    if not isinstance(encoded, str) or len(encoded) > MAX_AUDIO_BYTES * 4 // 3 + 4:
        raise ValueError("Audio exceeds the input limit.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(raw), "rb") as recording:
            frames = recording.getnframes()
            rate = recording.getframerate()
            if (recording.getnchannels() != 1 or recording.getsampwidth() != 2
                    or rate not in (16000, 24000, 48000)
                    or not 0 < frames <= rate * 30
                    or recording.getcomptype() != "NONE"):
                raise ValueError("Expected mono PCM16 WAV, at most 30 seconds.")
            if len(recording.readframes(frames)) != frames * 2:
                raise ValueError("Truncated WAV input.")
    except (ValueError, wave.Error, EOFError) as error:
        raise ValueError("Invalid audio: " + str(error)) from None
    return {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}}, len(raw)


def validate_request(body):
    if not isinstance(body, dict):
        raise ValueError("Expected a JSON object.")
    history = body.get("history", [])
    if not isinstance(history, list) or len(history) > 8:
        raise ValueError("History must contain at most eight messages.")
    messages = [{"role": "system", "content": SYSTEM}]
    audio_bytes = 0
    text_chars = 0
    expected_role = "user"
    for entry in [*history, {"role": "user", "input": body.get("input", ""),
                            "audio": body.get("audio")}]:
        if not isinstance(entry, dict) or entry.get("role") != expected_role:
            raise ValueError("History must alternate complete user/assistant turns.")
        text = entry.get("input", "")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError("Each text input must contain at most 4096 characters.")
        text_chars += len(text)
        content = []
        if entry.get("audio") is not None:
            if expected_role != "user":
                raise ValueError("Assistant audio history is not accepted.")
            audio_part, size = validate_audio(entry["audio"])
            audio_bytes += size
            content.append(audio_part)
        if text.strip():
            content.append({"type": "text", "text": text})
        if not content:
            raise ValueError("Supply text or an audio recording.")
        if text_chars > 16000 or audio_bytes > MAX_AUDIO_BYTES:
            raise ValueError("Conversation input exceeds its bounded budget.")
        messages.append({"role": expected_role,
                         "content": content if entry.get("audio") is not None else text})
        expected_role = "assistant" if expected_role == "user" else "user"
    if expected_role != "assistant":
        raise ValueError("History must end with a completed assistant reply.")
    voice = body.get("voice", "vivian")
    language = body.get("language", "Auto")
    if voice not in ("vivian", "serena", "ryan", "aiden"):
        raise ValueError("Unsupported voice.")
    if language not in ("Auto", "Chinese", "English", "Japanese", "Korean",
                        "French", "German", "Spanish"):
        raise ValueError("Unsupported language.")
    max_tokens = body.get("max_tokens", 512)
    if type(max_tokens) is not int or not 16 <= max_tokens <= 1024:
        raise ValueError("max_tokens must be an integer from 16 to 1024.")
    return messages, voice, language, max_tokens


async def sse_data(stream):
    fields = []
    event_size = 0
    async for raw in stream:
        if len(raw) > 65536:
            raise PipelineError("Oversized MiMo SSE line.")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if fields:
                yield "\n".join(fields)
                fields.clear()
                event_size = 0
        elif line.startswith("data:"):
            value = line[5:].removeprefix(" ")
            event_size += len(value)
            if event_size > 65536:
                raise PipelineError("Oversized MiMo SSE event.")
            fields.append(value)
    if fields:
        raise PipelineError("MiMo SSE ended inside an event.")


class ContentGuard:
    """Hold incomplete control-tag prefixes across delta boundaries."""

    markers = ("<think", "</think", "<|", "<tool", "</tool")

    def __init__(self):
        self.pending = ""

    def feed(self, text, final=False):
        self.pending += text
        if any(marker in self.pending for marker in self.markers):
            raise PipelineError("MiMo emitted a control token in speech content.")
        hold = 0
        if not final:
            for marker in self.markers:
                for size in range(1, len(marker)):
                    if self.pending.endswith(marker[:size]):
                        hold = max(hold, size)
        elif self.pending and any(
            self.pending.endswith(marker[:size])
            for marker in self.markers for size in range(1, len(marker))
        ):
            raise PipelineError("MiMo ended inside a control-token prefix.")
        safe = self.pending[:-hold] if hold else self.pending
        self.pending = self.pending[-hold:] if hold else ""
        return safe


@dataclass(frozen=True)
class Segment:
    index: int
    start: int
    end: int
    text: str


class SpannedSplitter:
    def __init__(self):
        self.splitter = SpeechTextSplitter("sentence")
        self.text = ""
        self.cursor = 0
        self.count = 0

    def _segments(self, units):
        result = []
        for unit in units:
            start = self.text.index(unit, self.cursor)
            end = start + len(unit)
            while start < end:
                boundary = min(start + MAX_SEGMENT, end)
                if boundary < end:
                    space = self.text.rfind(" ", start + MAX_SEGMENT // 2, boundary)
                    if space >= 0:
                        boundary = space + 1
                spoken = self.text[start:boundary].strip()
                if spoken:
                    left = start + len(self.text[start:boundary]) - len(self.text[start:boundary].lstrip())
                    right = boundary - len(self.text[start:boundary]) + len(self.text[start:boundary].rstrip())
                    result.append(Segment(self.count, left, right, spoken))
                    self.count += 1
                start = boundary
            self.cursor = end
        return result

    def feed(self, text):
        self.text += text
        if len(self.text) > MAX_TEXT:
            raise PipelineError("MiMo reply exceeds the speech budget.")
        result = self._segments(self.splitter.feed(text))
        if len(self.text) - self.cursor >= MAX_SEGMENT:
            result += self._segments(self.splitter.flush())
        return result

    def flush(self):
        return self._segments(self.splitter.flush())


class Backend:
    def __init__(self, client: ClientSession, mimo_url="http://127.0.0.1:8090",
                 tts_url="http://127.0.0.1:8093"):
        self.client = client
        self.mimo_url = mimo_url.rstrip("/")
        self.tts_url = tts_url.rstrip("/")

    async def run(self, response_id, messages, voice, language, max_tokens, emit):
        queue = asyncio.Queue(maxsize=4)
        splitter = SpannedSplitter()
        guard = ContentGuard()
        total_samples = 0
        finish_reason = None
        max_queue = 0

        async def enqueue(segments):
            nonlocal max_queue
            for segment in segments:
                await queue.put(segment)
                max_queue = max(max_queue, queue.qsize())

        async def text_delta(text):
            if not text:
                return
            segments = splitter.feed(text)
            await emit({"type": "text", "delta": text, "end": len(splitter.text)})
            await enqueue(segments)

        async def produce():
            nonlocal finish_reason
            payload = {
                "model": "mimo-v2.6-flash", "messages": messages,
                "max_tokens": max_tokens, "temperature": 0.0, "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            LOG.info("%s MiMo opened", response_id)
            try:
                async with self.client.post(
                    self.mimo_url + "/v1/chat/completions", json=payload,
                    headers={"X-Request-Id": response_id + "-mimo"},
                ) as response:
                    if response.status != 200:
                        await response.read()
                        raise PipelineError(f"MiMo HTTP {response.status}.")
                    done = False
                    async for data in sse_data(response.content):
                        if data == "[DONE]":
                            if finish_reason is None:
                                raise PipelineError("MiMo DONE without a finish reason.")
                            done = True
                            break
                        event = json.loads(data)
                        if not isinstance(event, dict) or event.get("error"):
                            raise PipelineError("MiMo returned an error event.")
                        for choice in event.get("choices", []):
                            delta = choice.get("delta", {})
                            if delta.get("tool_calls") or delta.get("function_call"):
                                raise PipelineError("Tool calls cannot enter speech.")
                            text = delta.get("content")
                            if text:
                                if not isinstance(text, str) or finish_reason is not None:
                                    raise PipelineError("Invalid MiMo content delta.")
                                await text_delta(guard.feed(text))
                            reason = choice.get("finish_reason")
                            if reason is not None:
                                if finish_reason is not None or reason not in ("stop", "length"):
                                    raise PipelineError("Invalid MiMo finish reason.")
                                finish_reason = reason
                    if not done:
                        raise PipelineError("MiMo disconnected before DONE.")
                    await text_delta(guard.feed("", final=True))
                    if not splitter.text.strip():
                        raise PipelineError("MiMo returned no reply text.")
                    await enqueue(splitter.flush())
                    await emit({"type": "model_done", "text": splitter.text,
                                "finish_reason": finish_reason})
                    await queue.put(None)
            finally:
                LOG.info("%s MiMo HTTP context closed", response_id)

        async def consume():
            nonlocal total_samples
            while True:
                segment = await queue.get()
                if segment is None:
                    return
                await emit({"type": "segment", "segment_id": segment.index,
                            "start": segment.start, "end": segment.end,
                            "text": segment.text, "sample_start": total_samples})
                payload = {
                    "model": "qwen3-tts-customvoice", "input": segment.text,
                    "voice": voice, "language": language, "task_type": "CustomVoice",
                    "stream": True, "stream_format": "audio", "response_format": "pcm",
                    "sample_rate": 24000, "max_new_tokens": 1024, "seed": 42,
                    "initial_codec_chunk_frames": 1,
                }
                pending = b""
                segment_samples = 0
                LOG.info("%s TTS segment %s opened", response_id, segment.index)
                try:
                    async with self.client.post(
                        self.tts_url + "/v1/audio/speech", json=payload,
                        headers={"X-Request-Id": f"{response_id}-tts-{segment.index}"},
                    ) as response:
                        if response.status != 200:
                            await response.read()
                            raise PipelineError(f"TTS HTTP {response.status}.")
                        if not response.headers.get("Content-Type", "").startswith("audio/pcm"):
                            raise PipelineError("TTS did not return PCM.")
                        async for chunk in response.content.iter_chunked(16384):
                            chunk = pending + chunk
                            size = len(chunk) - len(chunk) % 2
                            pending = chunk[size:]
                            if not size:
                                continue
                            pcm = chunk[:size]
                            segment_samples += size // 2
                            total_samples += size // 2
                            if segment_samples > 24000 * 45 or total_samples > 24000 * 180:
                                raise PipelineError("Synthesized audio exceeds its budget.")
                            await emit({"type": "audio", "segment_id": segment.index,
                                        "pcm": base64.b64encode(pcm).decode("ascii"),
                                        "samples": size // 2})
                        if pending or segment_samples == 0:
                            raise PipelineError("Incomplete or empty TTS PCM.")
                finally:
                    LOG.info("%s TTS segment %s HTTP context closed", response_id, segment.index)
                await emit({"type": "segment_done", "segment_id": segment.index,
                            "end": segment.end, "samples": segment_samples,
                            "sample_end": total_samples})

        tasks = [asyncio.create_task(produce()), asyncio.create_task(consume())]
        try:
            await asyncio.gather(*tasks)
            await emit({"type": "done", "text": splitter.text, "samples": total_samples,
                        "segments": splitter.count, "max_queue": max_queue,
                        "finish_reason": finish_reason})
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            while not queue.empty():
                queue.get_nowait()
            LOG.info("%s pipeline tasks closed; queue=%s", response_id, queue.qsize())


def client_timeout():
    return ClientTimeout(total=300, connect=10, sock_read=90)
