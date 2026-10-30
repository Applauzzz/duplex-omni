"""Standalone browser acceptance service for AVAD + MiMo semantic VAD + FSM."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import math
from pathlib import Path
import time
import uuid

from aiohttp import ClientSession, WSMsgType, web

from backend import client_timeout
from semantic_vad import (
    DEFAULT_CHAT_PROMPT,
    DEFAULT_VAED_PROMPT,
    DEFAULT_VASD_BREAK_PROMPT,
    DEFAULT_VASD_SEM_PROMPT,
    INTERRUPTION_MARKER,
    InvalidSemanticCommand,
    InputEvent,
    MiMoChatProvider,
    MiMoSemanticVADProvider,
    SemanticRealtimeAdapter,
    SemanticVADConfig,
    audio_chunks_to_wav,
)
from streaming_tts import IncrementalTextChunker, WeChatStreamingTTSProvider


HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = HERE / "svad_config.json"
LOG = logging.getLogger("mimo_tts.svad_debug")


def load_local_settings(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"SVAD config file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid SVAD config JSON at {path}:{error.lineno}:{error.colno}: {error.msg}"
        ) from error
    if not isinstance(payload, dict):
        raise ValueError("SVAD config root must be a JSON object")
    raw_config = payload.get("config")
    raw_prompts = payload.get("prompts")
    if not isinstance(raw_config, dict):
        raise ValueError("SVAD config requires a config object")
    if not isinstance(raw_prompts, dict):
        raise ValueError("SVAD config requires a prompts object")
    audio_chunk_ms = raw_config.get("audio_chunk_ms", 500)
    if (
        not isinstance(audio_chunk_ms, int | float)
        or isinstance(audio_chunk_ms, bool)
        or not 50 <= float(audio_chunk_ms) <= 5000
    ):
        raise ValueError("SVAD config audio_chunk_ms must be within [50, 5000]")
    app_config_names = {
        "audio_chunk_ms", "tts_enabled", "tts_reg_id", "tts_min_chars",
        "tts_max_chars", "tts_speed", "tts_target_rms",
        "retain_interrupted_context",
    }
    semantic_config = {key: value for key, value in raw_config.items() if key not in app_config_names}
    config = SemanticVADConfig.from_mapping({"type": "semantic_vad", **semantic_config})
    prompts = {}
    prompt_defaults = {
        "vasd_sem_prompt": DEFAULT_VASD_SEM_PROMPT,
        "vasd_break_prompt": raw_prompts.get(
            "vasd_prompt", DEFAULT_VASD_BREAK_PROMPT),
        "vaed_prompt": DEFAULT_VAED_PROMPT,
        "chat_prompt": DEFAULT_CHAT_PROMPT,
    }
    for name, default in prompt_defaults.items():
        value = raw_prompts.get(name, default)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError(f"SVAD config prompts.{name} must be a non-empty string of at most 4096 characters")
        prompts[name] = value
    tts_enabled = raw_config.get("tts_enabled", True)
    if not isinstance(tts_enabled, bool):
        raise ValueError("SVAD config tts_enabled must be a boolean")
    tts_reg_id = raw_config.get("tts_reg_id", "bench_spk")
    if not isinstance(tts_reg_id, str) or not tts_reg_id.strip() or len(tts_reg_id) > 100:
        raise ValueError("SVAD config tts_reg_id must be a non-empty string of at most 100 characters")
    tts_min_chars = raw_config.get("tts_min_chars", 8)
    tts_max_chars = raw_config.get("tts_max_chars", 48)
    if not isinstance(tts_min_chars, int) or isinstance(tts_min_chars, bool) or not 1 <= tts_min_chars <= 100:
        raise ValueError("SVAD config tts_min_chars must be within [1, 100]")
    if not isinstance(tts_max_chars, int) or isinstance(tts_max_chars, bool) or not tts_min_chars <= tts_max_chars <= 500:
        raise ValueError("SVAD config tts_max_chars must be within [tts_min_chars, 500]")
    tts_speed = raw_config.get("tts_speed", 1.0)
    if (
        not isinstance(tts_speed, int | float)
        or isinstance(tts_speed, bool)
        or not math.isfinite(float(tts_speed))
        or not 0.5 <= float(tts_speed) <= 2.0
    ):
        raise ValueError("SVAD config tts_speed must be within [0.5, 2.0]")
    tts_target_rms = raw_config.get("tts_target_rms", -25)
    if (
        not isinstance(tts_target_rms, int | float)
        or isinstance(tts_target_rms, bool)
        or not math.isfinite(float(tts_target_rms))
        or not -40 <= float(tts_target_rms) <= -10
    ):
        raise ValueError("SVAD config tts_target_rms must be within [-40, -10]")
    retain_interrupted_context = raw_config.get("retain_interrupted_context", False)
    if not isinstance(retain_interrupted_context, bool):
        raise ValueError("SVAD config retain_interrupted_context must be a boolean")
    return {
        "config": {
            "audio_chunk_ms": int(audio_chunk_ms),
            "tts_enabled": tts_enabled,
            "tts_reg_id": tts_reg_id.strip(),
            "tts_min_chars": tts_min_chars,
            "tts_max_chars": tts_max_chars,
            "tts_speed": float(tts_speed),
            "tts_target_rms": float(tts_target_rms),
            "retain_interrupted_context": retain_interrupted_context,
            "threshold": config.threshold,
            "prefix_padding_ms": config.prefix_padding_ms,
            "silence_duration_ms": config.silence_duration_ms,
            "min_speech_duration_ms": config.min_speech_duration_ms,
            "max_buffered_chunks": config.max_buffered_chunks,
            "vasd_window_ms": config.vasd_window_ms,
            "sem_probability_threshold": config.sem_probability_threshold,
            "sem_margin_threshold": config.sem_margin_threshold,
            "sem_confirmations": config.sem_confirmations,
            "break_probability_threshold": config.break_probability_threshold,
            "break_margin_threshold": config.break_margin_threshold,
            "break_confirmations": config.break_confirmations,
            "complete_probability_threshold": config.complete_probability_threshold,
            "complete_margin_threshold": config.complete_margin_threshold,
            "complete_confirmations": config.complete_confirmations,
            "incomplete_silence_timeout_ms": config.incomplete_silence_timeout_ms,
        },
        "prompts": prompts,
        "source": str(path),
    }


async def index(_request):
    return web.FileResponse(HERE / "svad_debug.html", headers={"Cache-Control": "no-store"})


async def health(request):
    started = time.monotonic()
    try:
        async with request.app["client"].get(request.app["mimo_url"] + "/health") as response:
            healthy = response.status == 200
    except Exception:
        healthy = False
    try:
        async with request.app["client"].get(request.app["tts_url"] + "/health") as response:
            tts_healthy = response.status == 200
    except Exception:
        tts_healthy = False
    return web.json_response({
        "mimo": healthy,
        "tts": tts_healthy,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        "mode": "fsm-avad-semantic-vad",
    })


async def defaults(request):
    try:
        payload = load_local_settings(request.app["config_path"])
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=500,
                                 headers={"Cache-Control": "no-store"})
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def websocket(request):
    ws = web.WebSocketResponse(max_msg_size=2 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)
    session_id = "svad-" + uuid.uuid4().hex[:12]
    adapter = None
    sequence = 0
    local_settings = load_local_settings(request.app["config_path"])
    local_config = dict(local_settings["config"])
    prompts = dict(local_settings["prompts"])
    history: list[dict[str, str]] = []
    chat_task = None
    chat_turn_id = None
    chat_tts_enabled = False
    chat_text_done = False
    tts_playback_active = False
    active_response = None
    pending_decode = None
    response_settings = {
        "tts_enabled": bool(local_config["tts_enabled"]),
        "tts_reg_id": str(local_config["tts_reg_id"]),
        "tts_min_chars": int(local_config["tts_min_chars"]),
        "tts_max_chars": int(local_config["tts_max_chars"]),
        "tts_speed": float(local_config["tts_speed"]),
        "tts_target_rms": float(local_config["tts_target_rms"]),
        "retain_interrupted_context": bool(local_config["retain_interrupted_context"]),
    }
    send_lock = asyncio.Lock()

    async def send(payload):
        async with send_lock:
            await ws.send_json(payload)

    async def cancel_chat(reason):
        nonlocal chat_task, chat_turn_id, chat_tts_enabled, chat_text_done, active_response
        task = chat_task
        turn_id = chat_turn_id
        active = task is not None and not task.done()
        retained_entry = None
        if (
            active
            and response_settings["retain_interrupted_context"]
            and isinstance(active_response, dict)
            and not active_response.get("text_done")
        ):
            partial = str(active_response.get("text") or "").rstrip()
            audio_wav = active_response.get("audio_wav")
            if partial and isinstance(audio_wav, str) and audio_wav:
                retained_entry = {
                    "audio_wav": audio_wav,
                    "assistant": partial + INTERRUPTION_MARKER,
                }
        if active:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        chat_task = None
        chat_turn_id = None
        had_tts = chat_tts_enabled
        text_done = chat_text_done
        chat_tts_enabled = False
        chat_text_done = False
        retained = False
        if retained_entry is not None:
            history.append(retained_entry)
            del history[:-4]
            retained = True
        active_response = None
        if turn_id is not None:
            event_type = "tts.cancelled" if text_done else "chat.cancelled"
            if active or had_tts:
                await send({
                    "type": event_type,
                    "turn_id": turn_id,
                    "reason": reason,
                    "retained": retained,
                    "interruption_marker": INTERRUPTION_MARKER if retained else None,
                })

    async def run_chat(turn_id, audio_chunks, chat_prompt):
        nonlocal chat_text_done, chat_tts_enabled, active_response
        text = ""
        chunker = IncrementalTextChunker(
            min_chars=response_settings["tts_min_chars"],
            max_chars=response_settings["tts_max_chars"],
        )
        tts_queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=8)
        tts_session = request.app["tts_provider"].create_stream(
            reg_id=response_settings["tts_reg_id"],
            speed=response_settings["tts_speed"],
            target_rms=response_settings["tts_target_rms"],
            context={
                "session_id": session_id,
                "request_id": f"{session_id}-{turn_id}-tts",
            },
        ) if response_settings["tts_enabled"] else None
        audio_wav = base64.b64encode(audio_chunks_to_wav(audio_chunks)).decode("ascii")
        active_response = {
            "turn_id": turn_id,
            "audio_wav": audio_wav,
            "text": "",
            "text_done": False,
        }
        await send({
            "type": "chat.started",
            "turn_id": turn_id,
            "audio_chunk_count": len(audio_chunks),
        })
        async def run_tts():
            total_samples = 0
            submitted_chunks = 0

            async def submit_text():
                nonlocal submitted_chunks
                while True:
                    chunk = await tts_queue.get()
                    if chunk is None:
                        await tts_session.finish()
                        await send({
                            "type": "tts.text",
                            "turn_id": turn_id,
                            "text_idx": tts_session.text_idx - 1,
                            "text": "",
                            "final": True,
                            "request_id": tts_session.task_id,
                        })
                        return
                    await tts_session.submit_text(chunk)
                    submitted_chunks += 1
                    await send({
                        "type": "tts.text",
                        "turn_id": turn_id,
                        "text_idx": tts_session.text_idx - 1,
                        "text": chunk,
                        "final": False,
                        "request_id": tts_session.task_id,
                    })

            async def poll_audio():
                nonlocal total_samples
                async for chunk in tts_session.stream_pcm():
                    samples = len(chunk.pcm) // 2
                    total_samples += samples
                    await send({
                        "type": "tts.audio",
                        "turn_id": turn_id,
                        "pcm": base64.b64encode(chunk.pcm).decode("ascii"),
                        "samples": samples,
                        "sample_rate_hz": chunk.sample_rate_hz,
                        "request_id": chunk.request_id,
                    })

            submit_task = asyncio.create_task(
                submit_text(), name=f"tts-submit-{session_id}-{turn_id}")
            poll_task = asyncio.create_task(
                poll_audio(), name=f"tts-poll-{session_id}-{turn_id}")
            try:
                done, pending = await asyncio.wait(
                    {submit_task, poll_task}, return_when=asyncio.FIRST_EXCEPTION)
                for task in done:
                    error = task.exception()
                    if error is not None:
                        raise error
                await asyncio.gather(*pending)
                await send({
                    "type": "tts.done",
                    "turn_id": turn_id,
                    "text_chunks": submitted_chunks,
                    "samples": total_samples,
                })
            except asyncio.CancelledError:
                raise
            except Exception as error:
                LOG.exception("TTS failed session=%s turn=%s", session_id, turn_id)
                await send({"type": "tts.error", "turn_id": turn_id,
                            "message": str(error)[:500]})
                while await tts_queue.get() is not None:
                    pass
            finally:
                for task in (submit_task, poll_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(submit_task, poll_task, return_exceptions=True)

        tts_task = asyncio.create_task(run_tts(), name=f"tts-{session_id}-{turn_id}") \
            if tts_session is not None else None
        try:
            async for delta in request.app["chat_provider"].stream_reply(
                audio_chunks,
                history=history,
                prompt=chat_prompt,
                context={"request_id": f"{session_id}-{turn_id}"},
            ):
                text += delta
                if isinstance(active_response, dict) and active_response.get("turn_id") == turn_id:
                    active_response["text"] = text
                await send({"type": "chat.delta", "turn_id": turn_id, "delta": delta})
                if tts_session is not None:
                    for chunk in chunker.feed(delta):
                        await tts_queue.put(chunk)
            if tts_session is not None:
                if text.strip().lower() == "listening":
                    tts_task.cancel()
                    await asyncio.gather(tts_task, return_exceptions=True)
                    tts_task = None
                    chat_tts_enabled = False
                else:
                    for chunk in chunker.flush():
                        await tts_queue.put(chunk)
                    await tts_queue.put(None)
            history.append({"audio_wav": audio_wav, "assistant": text})
            del history[:-4]
            await send({"type": "chat.done", "turn_id": turn_id, "text": text})
            chat_text_done = True
            if isinstance(active_response, dict) and active_response.get("turn_id") == turn_id:
                active_response["text"] = text
                active_response["text_done"] = True
            if tts_task is not None:
                await tts_task
        except asyncio.CancelledError:
            if tts_task is not None and not tts_task.done():
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            raise
        except Exception as error:
            if tts_task is not None and not tts_task.done():
                tts_task.cancel()
                await asyncio.gather(tts_task, return_exceptions=True)
            LOG.exception("MiMo Chat failed session=%s turn=%s", session_id, turn_id)
            await send({"type": "chat.error", "turn_id": turn_id, "message": str(error)[:500]})

    async def maybe_start_pending():
        nonlocal pending_decode
        if pending_decode is None or tts_playback_active:
            return
        if chat_task is not None and not chat_task.done():
            return
        turn_id, audio_chunks = pending_decode
        pending_decode = None
        start_chat(turn_id, audio_chunks)

    def start_chat(turn_id, audio_chunks):
        nonlocal chat_turn_id, chat_task, chat_tts_enabled, chat_text_done
        chat_turn_id = turn_id
        chat_tts_enabled = response_settings["tts_enabled"]
        chat_text_done = False
        chat_prompt = prompts["chat_prompt"]
        chat_task = asyncio.create_task(
            run_chat(turn_id, audio_chunks, chat_prompt),
            name=f"chat-{session_id}-{turn_id}",
        )
        chat_task.add_done_callback(
            lambda _task: asyncio.create_task(maybe_start_pending()))

    def update_prompts(payload):
        for key in prompts:
            if key not in payload:
                continue
            value = payload[key]
            if not isinstance(value, str) or not value.strip() or len(value) > 4096:
                raise ValueError(f"{key} must be a non-empty string of at most 4096 characters")
            prompts[key] = value
    try:
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                if frame.type == WSMsgType.ERROR:
                    break
                continue
            payload = json.loads(frame.data)
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            event_type = payload.get("type")
            if event_type == "configure":
                await cancel_chat("settings_reconfigured")
                if adapter is not None:
                    adapter.close()
                update_prompts(payload)
                config = SemanticVADConfig.from_mapping({
                    "type": "semantic_vad",
                    "threshold": payload.get("threshold", local_config["threshold"]),
                    "prefix_padding_ms": payload.get("prefix_padding_ms", local_config["prefix_padding_ms"]),
                    "silence_duration_ms": payload.get("silence_duration_ms", local_config["silence_duration_ms"]),
                    "min_speech_duration_ms": payload.get("min_speech_duration_ms", local_config["min_speech_duration_ms"]),
                    "max_buffered_chunks": payload.get("max_buffered_chunks", local_config["max_buffered_chunks"]),
                    "vasd_window_ms": payload.get("vasd_window_ms", local_config["vasd_window_ms"]),
                    "sem_probability_threshold": payload.get("sem_probability_threshold", local_config["sem_probability_threshold"]),
                    "sem_margin_threshold": payload.get("sem_margin_threshold", local_config["sem_margin_threshold"]),
                    "sem_confirmations": payload.get("sem_confirmations", local_config["sem_confirmations"]),
                    "break_probability_threshold": payload.get("break_probability_threshold", local_config["break_probability_threshold"]),
                    "break_margin_threshold": payload.get("break_margin_threshold", local_config["break_margin_threshold"]),
                    "break_confirmations": payload.get("break_confirmations", local_config["break_confirmations"]),
                    "complete_probability_threshold": payload.get("complete_probability_threshold", local_config["complete_probability_threshold"]),
                    "complete_margin_threshold": payload.get("complete_margin_threshold", local_config["complete_margin_threshold"]),
                    "complete_confirmations": payload.get("complete_confirmations", local_config["complete_confirmations"]),
                    "incomplete_silence_timeout_ms": payload.get("incomplete_silence_timeout_ms", local_config["incomplete_silence_timeout_ms"]),
                })
                audio_chunk_ms = payload.get("audio_chunk_ms", local_config["audio_chunk_ms"])
                if (
                    not isinstance(audio_chunk_ms, int | float)
                    or isinstance(audio_chunk_ms, bool)
                    or not 50 <= float(audio_chunk_ms) <= 5000
                ):
                    raise ValueError("audio_chunk_ms must be within [50, 5000]")
                tts_enabled = payload.get("tts_enabled", local_config["tts_enabled"])
                tts_reg_id = payload.get("tts_reg_id", local_config["tts_reg_id"])
                tts_min_chars = payload.get("tts_min_chars", local_config["tts_min_chars"])
                tts_max_chars = payload.get("tts_max_chars", local_config["tts_max_chars"])
                tts_speed = payload.get("tts_speed", local_config["tts_speed"])
                tts_target_rms = payload.get("tts_target_rms", local_config["tts_target_rms"])
                retain_interrupted_context = payload.get(
                    "retain_interrupted_context",
                    local_config["retain_interrupted_context"],
                )
                if not isinstance(tts_enabled, bool):
                    raise ValueError("tts_enabled must be a boolean")
                if not isinstance(tts_reg_id, str) or not tts_reg_id.strip() or len(tts_reg_id) > 100:
                    raise ValueError("tts_reg_id must be a non-empty string of at most 100 characters")
                if not isinstance(tts_min_chars, int) or isinstance(tts_min_chars, bool) or not 1 <= tts_min_chars <= 100:
                    raise ValueError("tts_min_chars must be within [1, 100]")
                if not isinstance(tts_max_chars, int) or isinstance(tts_max_chars, bool) or not tts_min_chars <= tts_max_chars <= 500:
                    raise ValueError("tts_max_chars must be within [tts_min_chars, 500]")
                if (
                    not isinstance(tts_speed, int | float)
                    or isinstance(tts_speed, bool)
                    or not math.isfinite(float(tts_speed))
                    or not 0.5 <= float(tts_speed) <= 2.0
                ):
                    raise ValueError("tts_speed must be within [0.5, 2.0]")
                if (
                    not isinstance(tts_target_rms, int | float)
                    or isinstance(tts_target_rms, bool)
                    or not math.isfinite(float(tts_target_rms))
                    or not -40 <= float(tts_target_rms) <= -10
                ):
                    raise ValueError("tts_target_rms must be within [-40, -10]")
                if not isinstance(retain_interrupted_context, bool):
                    raise ValueError("retain_interrupted_context must be a boolean")
                response_settings.update({
                    "tts_enabled": tts_enabled,
                    "tts_reg_id": tts_reg_id.strip(),
                    "tts_min_chars": tts_min_chars,
                    "tts_max_chars": tts_max_chars,
                    "tts_speed": float(tts_speed),
                    "tts_target_rms": float(tts_target_rms),
                    "retain_interrupted_context": retain_interrupted_context,
                })
                adapter = request.app["adapter_factory"](
                    config,
                    request.app["semantic_provider"],
                    backend_provider=request.app["vad_provider"],
                )
                await send({
                    "type": "configured",
                    "session_id": session_id,
                    "config": {
                        "audio_chunk_ms": int(audio_chunk_ms),
                        **response_settings,
                        "threshold": config.threshold,
                        "prefix_padding_ms": config.prefix_padding_ms,
                        "silence_duration_ms": config.silence_duration_ms,
                        "min_speech_duration_ms": config.min_speech_duration_ms,
                        "max_buffered_chunks": config.max_buffered_chunks,
                        "vasd_window_ms": config.vasd_window_ms,
                        "sem_probability_threshold": config.sem_probability_threshold,
                        "sem_margin_threshold": config.sem_margin_threshold,
                        "sem_confirmations": config.sem_confirmations,
                        "break_probability_threshold": config.break_probability_threshold,
                        "break_margin_threshold": config.break_margin_threshold,
                        "break_confirmations": config.break_confirmations,
                        "complete_probability_threshold": config.complete_probability_threshold,
                        "complete_margin_threshold": config.complete_margin_threshold,
                        "complete_confirmations": config.complete_confirmations,
                        "incomplete_silence_timeout_ms": config.incomplete_silence_timeout_ms,
                    },
                    "prompts": dict(prompts),
                })
                continue
            if event_type == "prompts.update":
                update_prompts(payload)
                await send({"type": "prompts.updated", "prompts": dict(prompts)})
                continue
            if event_type == "playback.state":
                tts_playback_active = bool(payload.get("active"))
                if not tts_playback_active:
                    await maybe_start_pending()
                continue
            if event_type == "reset":
                await cancel_chat("fsm_reset")
                if adapter is not None:
                    adapter.reset()
                sequence = 0
                history.clear()
                pending_decode = None
                tts_playback_active = False
                await send({"type": "reset", "session_id": session_id})
                continue
            if event_type != "audio":
                raise ValueError(f"Unknown event: {event_type!r}")
            if adapter is None:
                raise ValueError("Configure the session before sending audio")
            sequence += 1
            append = {
                "type": "input_audio_buffer.append",
                "audio": payload.get("audio"),
                "format": payload.get("format", "pcm16"),
                "sample_rate_hz": payload.get("sample_rate_hz", 16000),
            }
            try:
                output, commands = await adapter.process_append(
                    append,
                    default_format="pcm16",
                    default_sample_rate_hz=16000,
                    context={
                        "request_id": f"{session_id}-{sequence}",
                        "tts_playback_active": tts_playback_active,
                        **prompts,
                    },
                )
            except InvalidSemanticCommand as error:
                LOG.error(
                    "Invalid MiMo command session=%s sequence=%s kind=%s raw=%r allowed=%r",
                    session_id,
                    sequence,
                    error.kind,
                    error.raw_output,
                    error.allowed,
                )
                await send({
                    "type": "semantic_error",
                    "session_id": session_id,
                    "sequence": sequence,
                    "request_kind": error.kind,
                    "raw_output": error.raw_output,
                    "normalized": error.normalized,
                    "allowed": list(error.allowed),
                    "state": adapter.controller.fsm.state.value,
                    "avad": adapter.last_avad,
                })
                continue
            if output.interrupt:
                await cancel_chat("semantic_break")
            await send({
                "type": "transition",
                "session_id": session_id,
                "sequence": sequence,
                "avad": adapter.last_avad,
                "transition": output.as_log(),
                "candidate_chunk_count": len(adapter.controller.fsm.candidate_audio),
                "turn_chunk_count": len(adapter.controller.fsm.turn_audio),
                "commands": [item["type"] for item in commands],
            })
            if output.event == InputEvent.DECODE and output.decode_audio:
                if chat_task is not None and not chat_task.done() or tts_playback_active:
                    pending_decode = (sequence, output.decode_audio)
                    await send({
                        "type": "chat.pending",
                        "turn_id": sequence,
                        "reason": "current_response_not_interrupted",
                    })
                else:
                    start_chat(sequence, output.decode_audio)
    except (ValueError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        LOG.exception("SVAD debug session %s failed", session_id)
        if not ws.closed:
            await ws.send_json({"type": "error", "message": str(error)[:500]})
    finally:
        if adapter is not None:
            adapter.close()
        if chat_task is not None and not chat_task.done():
            chat_task.cancel()
            await asyncio.gather(chat_task, return_exceptions=True)
        await ws.close()
    return ws


async def context(app):
    from vllm_omni.engine.duplex.vad import SileroVADBackendProvider

    app["vad_provider"] = SileroVADBackendProvider()
    backend = await asyncio.to_thread(app["vad_provider"].get)
    LOG.info("AVAD backend loaded: %s", type(backend).__name__)
    async with ClientSession(trust_env=False, timeout=client_timeout()) as client:
        app["client"] = client
        app["semantic_provider"] = MiMoSemanticVADProvider(client, app["mimo_url"])
        app["chat_provider"] = MiMoChatProvider(client, app["mimo_url"])
        app["tts_provider"] = WeChatStreamingTTSProvider(client, app["tts_url"])
        yield


def create_app(
    *,
    mimo_url="http://127.0.0.1:8090",
    tts_url="http://29.213.195.135:8100",
    config_path=DEFAULT_CONFIG_PATH,
):
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app["mimo_url"] = mimo_url.rstrip("/")
    app["tts_url"] = tts_url.rstrip("/")
    app["config_path"] = Path(config_path)
    app["adapter_factory"] = SemanticRealtimeAdapter
    app.cleanup_ctx.append(context)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/defaults", defaults)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/capture_worklet.js", lambda _request: web.FileResponse(
        Path(__file__).parents[3] / "vllm-omni/examples/online_serving/realtime_web/app/static/pcm_worklet.js"))
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mimo-url", default="http://127.0.0.1:8090")
    parser.add_argument("--tts-url", default="http://29.213.195.135:8100")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    web.run_app(create_app(
        mimo_url=args.mimo_url,
        tts_url=args.tts_url,
        config_path=args.config,
    ), host=args.host, port=args.port,
                handler_cancellation=True)


if __name__ == "__main__":
    main()
