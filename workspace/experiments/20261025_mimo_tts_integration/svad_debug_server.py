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
from urllib.parse import urlsplit

from aiohttp import ClientSession, WSServerHandshakeError, WSMsgType, web

from agent_runtime import AgenticMiMoChatProvider
from background_reasoning import BackgroundReasoning
from mac_tools import EchoBridge, MacToolError, TOOL as MAC_ECHO_TOOL
from browser_trust import BrowserTrust, browser_origin
from mac_m2 import M2Bridge, FUNCTIONS as MAC_M2_FUNCTIONS, WRITES as MAC_M2_WRITES, CALLS as MAC_M2_CALLS
from backend import client_timeout
from semantic_vad import (
    CHAT_HISTORY_TURNS,
    DEFAULT_CHAT_PROMPT,
    DEFAULT_VAED_PROMPT,
    DEFAULT_VASD_SEM_PROMPT,
    INTERRUPTION_MARKER,
    InvalidSemanticCommand,
    InputEvent,
    MiMoChatProvider,
    MiMoSemanticVADProvider,
    SemanticRealtimeAdapter,
    SemanticVADConfig,
    audio_chunks_to_wav,
    video_chunks_to_jpeg_sequence,
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
        "history_turns",
        "background_reasoning",
    }
    semantic_config = {key: value for key, value in raw_config.items() if key not in app_config_names}
    server_policy = payload.get("server_policy", {})
    if not isinstance(server_policy, dict) or set(server_policy) - {"vaed_mode", "vaed_window_ms"}:
        raise ValueError("SVAD server_policy only supports vaed_mode and vaed_window_ms")
    semantic_config.update(server_policy)
    config = SemanticVADConfig.from_mapping({"type": "semantic_vad", **semantic_config})
    prompts = {}
    prompt_defaults = {
        "vasd_sem_prompt": DEFAULT_VASD_SEM_PROMPT,
        "vaed_prompt": DEFAULT_VAED_PROMPT,
        "chat_prompt": DEFAULT_CHAT_PROMPT,
    }
    for name, default in prompt_defaults.items():
        value = raw_prompts.get(name, default)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError(f"SVAD config prompts.{name} must be a non-empty string of at most 4096 characters")
        prompts[name] = value
    for name in ("agent_tool_prompt", "agent_forced_prompt", "background_reasoning_prompt"):
        if name in raw_prompts:
            value = raw_prompts[name]
            if not isinstance(value, str) or not value.strip() or len(value) > 16000:
                raise ValueError(f"SVAD config prompts.{name} must be a non-empty string of at most 16000 characters")
            prompts[name] = value
    history_turns = raw_config.get("history_turns", CHAT_HISTORY_TURNS)
    background_reasoning = raw_config.get("background_reasoning", False)
    if not isinstance(background_reasoning, bool):
        raise ValueError("SVAD config background_reasoning must be a boolean")
    if not isinstance(history_turns, int) or isinstance(history_turns, bool) or not 0 <= history_turns <= 100:
        raise ValueError("SVAD config history_turns must be an integer within [0, 100]")
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
            "history_turns": history_turns,
            "background_reasoning": background_reasoning,
            "threshold": config.threshold,
            "prefix_padding_ms": config.prefix_padding_ms,
            "silence_duration_ms": config.silence_duration_ms,
            "min_speech_duration_ms": config.min_speech_duration_ms,
            "max_buffered_chunks": config.max_buffered_chunks,
            "vasd_window_ms": config.vasd_window_ms,
            "vaed_mode": config.vaed_mode,
            "vaed_window_ms": config.vaed_window_ms,
            "sem_probability_threshold": config.sem_probability_threshold,
            "sem_margin_threshold": config.sem_margin_threshold,
            "sem_confirmations": config.sem_confirmations,
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


async def agent_frontend_proxy(request):
    tail = request.match_info.get("tail", "")
    if request.path == "/agent":
        target_path = "/agent"
    elif request.path == "/duplex_pcm_capture.js":
        target_path = request.path
    elif request.path.startswith("/api/tools/"):
        target_path = request.path
    else:
        target_path = "/_next/" + tail
    target = request.app["agent_frontend_url"] + target_path
    if request.query_string:
        target += "?" + request.query_string
    body = await request.read()
    async with request.app["client"].request(
        request.method,
        target,
        data=body if body else None,
        headers={
            key: value for key, value in request.headers.items()
            if key.lower() not in {
                "host", "connection", "upgrade", "content-length",
            }
        },
        allow_redirects=False,
    ) as response:
        body = await response.read()
        headers = {
            key: value for key, value in response.headers.items()
            if key.lower() not in {
                "content-length", "transfer-encoding", "connection",
                "content-encoding",
            }
        }
        return web.Response(body=body, status=response.status, headers=headers)


async def agent_websocket_proxy(request):
    if request.headers.get("Origin"):
        try:
            browser_origin(request)
        except MacToolError:
            return web.json_response({"error": "browser_origin_rejected"}, status=403)
    browser = web.WebSocketResponse(max_msg_size=2 * 1024 * 1024, heartbeat=20)
    await browser.prepare(request)
    async with request.app["client"].ws_connect(
        request.app["agent_backend_url"] + "/ws",
        max_msg_size=2 * 1024 * 1024,
        heartbeat=20,
        headers={k: request.headers[k] for k in ("Host", "Origin", "Cookie")
                 if k in request.headers},
    ) as backend:
        async def browser_to_backend():
            async for message in browser:
                if message.type == WSMsgType.TEXT:
                    await backend.send_str(message.data)
                elif message.type == WSMsgType.BINARY:
                    await backend.send_bytes(message.data)
                elif message.type in {WSMsgType.CLOSE, WSMsgType.ERROR}:
                    break

        async def backend_to_browser():
            async for message in backend:
                if message.type == WSMsgType.TEXT:
                    await browser.send_str(message.data)
                elif message.type == WSMsgType.BINARY:
                    await browser.send_bytes(message.data)
                elif message.type in {WSMsgType.CLOSE, WSMsgType.ERROR}:
                    break

        tasks = {
            asyncio.create_task(browser_to_backend()),
            asyncio.create_task(backend_to_browser()),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    await browser.close()
    return browser


async def mac_http_proxy(request):
    async with request.app["client"].request(
        request.method, request.app["agent_backend_url"] + request.path_qs,
        data=await request.read(),
        headers={k: v for k, v in request.headers.items()
                 if k.lower() not in {"content-length", "connection"}},
        allow_redirects=False,
    ) as response:
        return web.Response(body=await response.read(), status=response.status,
                            headers={k: v for k, v in response.headers.items()
                                     if k.lower() in {"content-type", "cache-control",
                                                      "vary", "retry-after", "set-cookie"}})


async def mac_websocket_proxy(request):
    require_origin = request.headers.get("Origin")
    if require_origin is not None:
        return web.json_response({"error": "native_client_required"}, status=403)
    try:
        upstream = await request.app["client"].ws_connect(
            request.app["agent_backend_url"] + request.path_qs,
            headers={"Authorization": request.headers.get("Authorization", "")},
            max_msg_size=32768,
        )
    except WSServerHandshakeError as error:
        return web.json_response({"error": "mac_bridge_connection_rejected"},
                                 status=error.status)
    async with upstream:
        native = web.WebSocketResponse(max_msg_size=32768, heartbeat=20)
        await native.prepare(request)

        async def relay(source, target):
            async for message in source:
                if message.type == WSMsgType.TEXT:
                    await target.send_str(message.data)
                else:
                    break
        tasks = [asyncio.create_task(relay(native, upstream)),
                 asyncio.create_task(relay(upstream, native))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await native.close(code=upstream.close_code or 1000)
        return native


async def websocket(request):
    origin = None
    if request.headers.get("Origin"):
        try:
            if request.app["agentic"]:
                origin = browser_origin(request)
            else:
                origin = request.headers["Origin"]
                parsed = urlsplit(origin)
                if (parsed.scheme not in {"http", "https"}
                        or parsed.netloc != request.host
                        or parsed.username or parsed.password
                        or parsed.path or parsed.query or parsed.fragment):
                    raise MacToolError("browser_origin_rejected")
        except MacToolError:
            return web.json_response({"error": "browser_origin_rejected"}, status=403)
    ws = web.WebSocketResponse(max_msg_size=2 * 1024 * 1024, heartbeat=20)
    await ws.prepare(request)
    session_id = "svad-" + uuid.uuid4().hex[:12]
    adapter = None
    sequence = 0
    local_settings = load_local_settings(request.app["config_path"])
    local_config = dict(local_settings["config"])
    prompts = dict(local_settings["prompts"])
    history: list[dict[str, str]] = []
    agent_config: dict[str, object] = {}
    pending_tool_calls: dict[str, asyncio.Future[str]] = {}
    pending_tool_names: dict[str, str] = {}
    pending_tool_arguments: dict[str, str] = {}
    mac_tasks: set[asyncio.Task] = set()
    mac_requested: set[str] = set()
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
        "history_turns": local_config["history_turns"],
    }
    send_lock = asyncio.Lock()

    async def send(payload):
        if payload.get("type") in {"agent.mac.status", "agent.mac.m2.status"} and agent_config:
            tools = [item for item in agent_config.get("tools", [])
                     if item.get("function", {}).get("name") not in {*MAC_M2_FUNCTIONS, "demo_echo"}]
            if mac_bridge.ready(mac_binding):
                tools.append(MAC_ECHO_TOOL)
            tools.extend(MAC_M2_FUNCTIONS[name] for name in mac_m2.available(m2_binding))
            agent_config["tools"] = tools
        async with send_lock:
            await ws.send_json(payload)

    mac_bridge = request.app["mac_bridge"]
    mac_binding = mac_bridge.open_session(session_id, send)
    mac_m2 = request.app["mac_m2"]
    m2_binding = mac_m2.open_session(session_id, send)
    browser_trust = request.app["browser_trust"]
    mac_binding.browser_origin = origin
    m2_approvals = {}
    capture_acks = {}
    background = BackgroundReasoning(send)
    background_calls = set()
    turn_background_result = None
    turn_result_only = False

    async def cancel_chat(reason):
        nonlocal chat_task, chat_turn_id, chat_tts_enabled, chat_text_done, active_response
        task = chat_task
        await mac_bridge.advance(mac_binding)
        await mac_m2.advance(m2_binding)
        for future in [*m2_approvals.values(), *capture_acks.values()]:
            if not future.done():
                future.cancel()
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
                video_frames = active_response.get("video_frames")
                if isinstance(video_frames, str) and video_frames:
                    retained_entry["video_frames"] = video_frames
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
        for call_id, future in list(pending_tool_calls.items()):
            if call_id in background_calls:
                continue
            if not future.done():
                future.cancel()
            pending_tool_calls.pop(call_id, None)
            pending_tool_names.pop(call_id, None)
        pending_tool_arguments.clear()
        mac_requested.clear()
        for mac_task in tuple(mac_tasks):
            mac_task.cancel()
        if retained_entry is not None:
            history.append(retained_entry)
            if response_settings["history_turns"]:
                del history[:-response_settings["history_turns"]]
            else:
                history.clear()
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
        result = turn_background_result
        result_only = turn_result_only

        async def run_agent_tool(call):
            call_id = call.get("id")
            function = call.get("function")
            if not isinstance(call_id, str) or not call_id:
                raise RuntimeError("MiMo agent tool call requires an id")
            if not isinstance(function, dict):
                raise RuntimeError("MiMo agent tool call requires a function")
            future = asyncio.get_running_loop().create_future()
            pending_tool_calls[call_id] = future
            pending_tool_names[call_id] = function.get("name")
            pending_tool_arguments[call_id] = function.get("arguments", "{}")
            await send({
                "type": "agent.function_call",
                "turn_id": turn_id,
                "call_id": call_id,
                "name": function.get("name"),
                "arguments": function.get("arguments", "{}"),
            })
            LOG.info(
                "agent_function_call session=%s turn=%s call_id=%s name=%s arguments=%s",
                session_id,
                turn_id,
                call_id,
                function.get("name"),
                str(function.get("arguments", "{}"))[:500],
            )
            try:
                return await future
            finally:
                pending_tool_calls.pop(call_id, None)
                pending_tool_names.pop(call_id, None)
                pending_tool_arguments.pop(call_id, None)

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
        audio_wav = (base64.b64encode(audio_chunks_to_wav(audio_chunks)).decode("ascii")
                     if audio_chunks else None)
        video_frames = video_chunks_to_jpeg_sequence(audio_chunks)
        active_response = {
            "turn_id": turn_id,
            "audio_wav": audio_wav,
            "video_frames": video_frames,
            "text": "",
            "text_done": False,
        }
        await send({
            "type": "chat.started",
            "turn_id": turn_id,
            "audio_chunk_count": len(audio_chunks),
            "video_frame_count": sum(
                1 for item in audio_chunks
                if isinstance(item, dict) and item.get("video_frame") is not None
            ),
        })
        LOG.info(
            "agent_chat_started session=%s turn=%s audio_chunks=%s video_frames=%s tools=%s",
            session_id,
            turn_id,
            len(audio_chunks),
            sum(
                1 for item in audio_chunks
                if isinstance(item, dict) and item.get("video_frame") is not None
            ),
            [
                item.get("function", {}).get("name")
                for item in agent_config.get("tools", [])
                if isinstance(item, dict)
            ],
        )
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
                context={
                    "request_id": f"{session_id}-{turn_id}",
                    "video_frames": video_frames,
                    "agent_config": agent_config,
                    "agent_tool_handler": run_agent_tool,
                    "history_turns": response_settings["history_turns"],
                    "background_reasoning_result": result,
                    "background_result_only": result_only,
                    "background_reasoning_prompt": prompts.get("background_reasoning_prompt", ""),
                    "background_reasoning_handler": (
                        lambda call: background.start(call, run_background_tool)
                    ) if local_config["background_reasoning"] and request.app["agentic"] else None,
                    **{key: prompts[key] for key in ("agent_tool_prompt", "agent_forced_prompt")
                       if key in prompts},
                },
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
            history_entry = {"audio_wav": audio_wav, "assistant": text}
            if result:
                history_entry["background_reasoning_result"] = result
            if video_frames is not None:
                history_entry["video_frames"] = video_frames
            history.append(history_entry)
            if response_settings["history_turns"]:
                del history[:-response_settings["history_turns"]]
            else:
                history.clear()
            await send({"type": "chat.done", "turn_id": turn_id, "text": text})
            if result and text.strip().lower() != "listening":
                await background.delivered(result["task_id"])
            LOG.info(
                "agent_chat_done session=%s turn=%s text_chars=%s tts=%s",
                session_id,
                turn_id,
                len(text),
                tts_task is not None,
            )
            chat_text_done = True
            if isinstance(active_response, dict) and active_response.get("turn_id") == turn_id:
                active_response["text"] = text
                active_response["text_done"] = True
            if tts_task is not None:
                await tts_task
                LOG.info(
                    "agent_tts_done session=%s turn=%s",
                    session_id,
                    turn_id,
                )
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
        nonlocal turn_background_result, turn_result_only
        turn_background_result = background.result()
        turn_result_only = not audio_chunks and bool(turn_background_result)
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

    async def run_background_tool(call):
        originating_turn = chat_turn_id
        call_id = call["id"]
        future = asyncio.get_running_loop().create_future()
        background_calls.add(call_id)
        pending_tool_calls[call_id] = future
        pending_tool_names[call_id] = "consult_reasoning_model"
        try:
            await send({"type": "agent.function_call", "turn_id": originating_turn,
                        "background": True,
                        "call_id": call_id, "name": "consult_reasoning_model",
                        "arguments": call["function"]["arguments"]})
            return await asyncio.wait_for(future, 120)
        finally:
            pending_tool_calls.pop(call_id, None)
            pending_tool_names.pop(call_id, None)
            if len(background_calls) > 32:
                background_calls.intersection_update(pending_tool_calls)
                background_calls.add(call_id)

    async def forget_browser():
        await cancel_chat("browser_authorization_revoked")
        await mac_bridge.revoke(mac_binding)
        await mac_m2.revoke(m2_binding)

    mac_binding.forget_browser = forget_browser

    def update_prompts(payload):
        for key in prompts:
            if key not in payload:
                continue
            value = payload[key]
            limit = 16000 if key.startswith("agent_") or key == "background_reasoning_prompt" else 4096
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError(f"{key} must be a non-empty string of at most {limit} characters")
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
                    "vaed_mode": local_config["vaed_mode"],
                    "vaed_window_ms": local_config["vaed_window_ms"],
                    "sem_probability_threshold": payload.get("sem_probability_threshold", local_config["sem_probability_threshold"]),
                    "sem_margin_threshold": payload.get("sem_margin_threshold", local_config["sem_margin_threshold"]),
                    "sem_confirmations": payload.get("sem_confirmations", local_config["sem_confirmations"]),
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
                history_turns = payload.get("history_turns", local_config["history_turns"])
                if not isinstance(history_turns, int) or isinstance(history_turns, bool) or not 0 <= history_turns <= 100:
                    raise ValueError("history_turns must be an integer within [0, 100]")
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
                    "history_turns": history_turns,
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
                        "vaed_mode": config.vaed_mode,
                        "vaed_window_ms": config.vaed_window_ms,
                        "sem_probability_threshold": config.sem_probability_threshold,
                        "sem_margin_threshold": config.sem_margin_threshold,
                        "sem_confirmations": config.sem_confirmations,
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
            if event_type == "agent.mac.status":
                if origin and not mac_binding.device_id:
                    try:
                        await browser_trust.restore(request, mac_binding, m2_binding)
                    except MacToolError as error:
                        await send({"type": "agent.mac.error", "message": str(error)})
                await mac_bridge.notify(mac_binding)
                await mac_m2.notify(m2_binding)
                continue
            if event_type == "agent.mac.m2.options":
                try:
                    await mac_m2.options(m2_binding, mac_binding)
                except MacToolError as error:
                    await send({"type": "agent.mac.error", "message": str(error)})
                continue
            if event_type == "agent.mac.m2.authorize":
                try:
                    await mac_m2.authorize(m2_binding, mac_binding,
                                           payload.get("scope"), payload.get("confirmed"))
                    await browser_trust.save(mac_binding)
                except MacToolError as error:
                    await send({"type": "agent.mac.error", "message": str(error)})
                continue
            if event_type == "agent.mac.m2.revoke":
                await cancel_chat("m2_revoked")
                await mac_m2.revoke(m2_binding)
                await browser_trust.save(mac_binding)
                continue
            if event_type == "agent.mac.m2.confirm":
                future = m2_approvals.get(payload.get("call_id"))
                if future and not future.done():
                    future.set_result(payload.get("approved") is True)
                continue
            if event_type == "agent.capture.ready":
                m2_binding.capture_ready = payload.get("supported") is True
                await mac_m2.notify(m2_binding)
                continue
            if event_type == "agent.capture.paused":
                future = capture_acks.get(payload.get("request_id"))
                if future and not future.done():
                    future.set_result(payload.get("stopped") is True)
                continue
            if event_type == "agent.capture.resume":
                m2_binding.capture_paused = False
                await browser_trust.save(mac_binding)
                await mac_m2.notify(m2_binding)
                continue
            if event_type == "agent.capture.hold":
                m2_binding.capture_paused = True
                await browser_trust.save(mac_binding)
                await mac_m2.notify(m2_binding)
                continue
            if event_type == "agent.mac.m2.invoke":
                call_id, name = payload.get("call_id"), payload.get("name")
                if (name not in MAC_M2_FUNCTIONS
                        or pending_tool_names.get(call_id) != name
                        or call_id not in pending_tool_calls
                        or payload.get("arguments") != json.loads(
                            pending_tool_arguments.get(call_id, "{}"))):
                    await send({"type": "agent.mac.result", "call_id": call_id,
                                "error": "mac_call_not_pending"})
                    continue
                if call_id in mac_requested:
                    continue
                mac_requested.add(call_id)

                async def invoke_m2(call_id, name, arguments):
                    generation = m2_binding.generation
                    try:
                        approved = name not in MAC_M2_WRITES
                        if not approved:
                            future = asyncio.get_running_loop().create_future()
                            m2_approvals[call_id] = future
                            await send({"type": "agent.mac.m2.confirmation", "call_id": call_id,
                                        "name": name, "arguments": arguments})
                            approved = await asyncio.wait_for(future, 60)
                        if not approved:
                            output = json.dumps({"status": "cancelled", "summary": "User declined",
                                                 "data": None, "error": {"code": "user_declined",
                                                 "message": "User declined", "retryable": False}})
                            m2_binding.outputs[call_id] = (generation, output)
                        else:
                            if name in MAC_M2_CALLS:
                                request_id = uuid.uuid4().hex
                                m2_binding.capture_paused = True
                                await browser_trust.save(mac_binding)
                                future = asyncio.get_running_loop().create_future()
                                capture_acks[request_id] = future
                                await send({"type": "agent.capture.pause", "request_id": request_id})
                                if not await asyncio.wait_for(future, 10):
                                    raise MacToolError("m2_capture_pause_failed")
                                if m2_binding.generation != generation:
                                    return
                                m2_binding.capture_paused = True
                                await mac_m2.notify(m2_binding)
                            if m2_binding.generation != generation:
                                return
                            output = await mac_m2.invoke_tool(
                                m2_binding, call_id, name, arguments, confirmed=approved)
                        await send({"type": "agent.mac.result", "call_id": call_id, "output": output})
                    except (MacToolError, asyncio.TimeoutError) as error:
                        if not m2_binding.closed and m2_binding.generation == generation:
                            code = str(error) or "m2_confirmation_timeout"
                            output = json.dumps({"status": "failed", "summary": code, "data": None,
                                                 "error": {"code": code, "message": code,
                                                           "retryable": False}})
                            m2_binding.outputs[call_id] = (generation, output)
                            await send({"type": "agent.mac.result", "call_id": call_id, "output": output})
                    finally:
                        m2_approvals.pop(call_id, None)
                        if name in MAC_M2_CALLS and "request_id" in locals():
                            capture_acks.pop(request_id, None)
                task = asyncio.create_task(invoke_m2(call_id, name, payload["arguments"]))
                mac_tasks.add(task)
                task.add_done_callback(mac_tasks.discard)
                continue
            if event_type == "agent.mac.bind":
                try:
                    await mac_bridge.bind(
                        mac_binding, payload.get("pairing_code"), payload.get("confirmed"))
                except MacToolError as error:
                    await send({"type": "agent.mac.error", "message": str(error)})
                continue
            if event_type == "agent.mac.revoke":
                await browser_trust.revoke(mac_binding)
                await cancel_chat("mac_authorization_revoked")
                await mac_bridge.revoke(mac_binding)
                await mac_m2.revoke(m2_binding)
                continue
            if event_type == "agent.mac.invoke":
                call_id = payload.get("call_id")
                if (not isinstance(call_id, str)
                        or pending_tool_names.get(call_id) != "demo_echo"
                        or call_id not in pending_tool_calls
                        or payload.get("arguments") != json.loads(
                            pending_tool_arguments.get(call_id, "{}"))):
                    await send({"type": "agent.mac.result", "call_id": call_id,
                                "error": "mac_call_not_pending"})
                    continue
                if call_id in mac_requested:
                    continue
                mac_requested.add(call_id)

                async def invoke_mac(call_id, arguments):
                    try:
                        output = await mac_bridge.invoke(mac_binding, call_id, arguments)
                        await send({"type": "agent.mac.result", "call_id": call_id,
                                    "output": output})
                    except (MacToolError, OSError) as error:
                        await send({"type": "agent.mac.result", "call_id": call_id,
                                    "error": str(error) if isinstance(error, MacToolError)
                                    else "mac_audit_unavailable"})
                task = asyncio.create_task(invoke_mac(call_id, payload.get("arguments")))
                mac_tasks.add(task)
                task.add_done_callback(mac_tasks.discard)
                continue
            if event_type == "agent.session.update":
                instructions = payload.get("instructions")
                tools = payload.get("tools", [])
                if not isinstance(instructions, str) or not instructions.strip():
                    raise ValueError("agent.session.update requires instructions")
                if not isinstance(tools, list):
                    raise ValueError("agent.session.update tools must be an array")
                if any(not isinstance(item, dict)
                       or not isinstance(item.get("function"), dict) for item in tools):
                    raise ValueError("agent.session.update requires function tools")
                tools = [
                    item for item in tools
                    if not isinstance(item, dict)
                    or item.get("function", {}).get("name") not in {*MAC_M2_FUNCTIONS, "demo_echo"}
                ] + ([MAC_ECHO_TOOL] if mac_bridge.ready(mac_binding) else []) + [
                    MAC_M2_FUNCTIONS[name] for name in mac_m2.available(m2_binding)]
                agent_config.clear()
                agent_config.update({"instructions": instructions, "tools": tools})
                LOG.info(
                    "agent_session_updated session=%s tools=%s",
                    session_id,
                    [
                        item.get("function", {}).get("name")
                        for item in tools if isinstance(item, dict)
                    ],
                )
                await send({"type": "agent.session.updated"})
                continue
            if event_type == "agent.function_call_output":
                call_id = payload.get("call_id")
                output = payload.get("output")
                future = pending_tool_calls.get(call_id)
                if future is None or future.done():
                    if call_id in background_calls:
                        continue
                    raise ValueError(f"Unknown agent tool call: {call_id!r}")
                if not isinstance(output, str):
                    raise ValueError("agent tool output must be a string")
                if (pending_tool_names.get(call_id) == "demo_echo"
                        and not mac_bridge.verified_output(mac_binding, call_id, output)):
                    raise ValueError("Unverified Mac tool output")
                if (pending_tool_names.get(call_id) in MAC_M2_FUNCTIONS
                        and not mac_m2.verified_output(m2_binding, call_id, output)):
                    raise ValueError("Unverified Mac M2 tool output")
                future.set_result(output)
                continue
            if event_type == "response.cancel":
                await cancel_chat("agent_interrupt")
                continue
            if event_type == "playback.state":
                tts_playback_active = bool(payload.get("active"))
                if not tts_playback_active:
                    await maybe_start_pending()
                continue
            if event_type == "reset":
                await background.close()
                await cancel_chat("fsm_reset")
                if adapter is not None:
                    adapter.reset()
                sequence = 0
                history.clear()
                agent_config.clear()
                pending_decode = None
                tts_playback_active = False
                await send({"type": "reset", "session_id": session_id})
                continue
            if event_type != "audio":
                raise ValueError(f"Unknown event: {event_type!r}")
            if m2_binding.capture_paused:
                continue
            if adapter is None:
                raise ValueError("Configure the session before sending audio")
            sequence += 1
            append = {
                "type": "input_audio_buffer.append",
                "audio": payload.get("audio"),
                "format": payload.get("format", "pcm16"),
                "sample_rate_hz": payload.get("sample_rate_hz", 16000),
            }
            if "video_frame" in payload:
                append["video_frame"] = payload["video_frame"]
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
            elif (background.ready() and output.reject
                  and not (chat_task and not chat_task.done()) and not tts_playback_active):
                start_chat(sequence, ())
    except (ValueError, TypeError, KeyError, RuntimeError, OverflowError) as error:
        LOG.exception("SVAD debug session %s failed", session_id)
        if not ws.closed:
            await ws.send_json({"type": "error", "message": str(error)[:500]})
    finally:
        await background.close()
        await mac_bridge.close_session(mac_binding)
        await mac_m2.close_session(m2_binding)
        for task in mac_tasks:
            task.cancel()
        await asyncio.gather(*mac_tasks, return_exceptions=True)
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
        if not app["agentic"]:
            app["chat_provider"] = MiMoChatProvider(client, app["mimo_url"])
        else:
            app["chat_provider"] = AgenticMiMoChatProvider(
                client, app["mimo_url"], native_tool_calls=True)
        app["tts_provider"] = WeChatStreamingTTSProvider(client, app["tts_url"])
        yield


def create_app(
    *,
    mimo_url="http://127.0.0.1:8090",
    tts_url="http://29.213.195.135:8100",
    config_path=DEFAULT_CONFIG_PATH,
    agentic=False,
    agent_frontend_url="http://127.0.0.1:3000",
    agent_backend_url="http://127.0.0.1:8081",
    mac_auth_file=None,
    mac_audit_file=None,
    mac_m2_policy_file=None,
):
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app["mimo_url"] = mimo_url.rstrip("/")
    app["tts_url"] = tts_url.rstrip("/")
    app["config_path"] = Path(config_path)
    app["agentic"] = bool(agentic)
    app["mac_bridge"] = EchoBridge(mac_auth_file, mac_audit_file)
    app["mac_m2"] = M2Bridge(app["mac_bridge"], mac_m2_policy_file)
    app["browser_trust"] = BrowserTrust(app["mac_bridge"], app["mac_m2"])
    app["agent_frontend_url"] = agent_frontend_url.rstrip("/")
    app["agent_backend_url"] = agent_backend_url.rstrip("/")
    app["adapter_factory"] = SemanticRealtimeAdapter
    app.cleanup_ctx.append(context)
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/defaults", defaults)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/capture_worklet.js", lambda _request: web.FileResponse(
        Path(__file__).parents[3] / "vllm-omni/examples/online_serving/realtime_web/app/static/pcm_worklet.js"))
    app.router.add_route("*", "/agent", agent_frontend_proxy)
    app.router.add_route("*", "/_next/{tail:.*}", agent_frontend_proxy)
    app.router.add_route("*", "/duplex_pcm_capture.js", agent_frontend_proxy)
    if agentic:
        app["mac_bridge"].routes(app)
        app["mac_m2"].routes(app)
        app["browser_trust"].routes(app)
    else:
        app.router.add_route("*", "/api/tools/capabilities", mac_http_proxy)
        app.router.add_route("*", "/api/tools/pairing", mac_http_proxy)
        app.router.add_route("*", "/api/tools/device/binding", mac_http_proxy)
        app.router.add_get("/api/tools/bridge", mac_websocket_proxy)
        app.router.add_get("/api/tools/m2/bridge", mac_websocket_proxy)
        app.router.add_route("*", "/api/tools/m2/{tail:.*}", mac_http_proxy)
        app.router.add_route("*", "/api/tools/browser/{tail:.*}", mac_http_proxy)
    app.router.add_route("*", "/api/tools/{tail:.*}", agent_frontend_proxy)
    app.router.add_get("/agent-ws", agent_websocket_proxy)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--mimo-url", default="http://127.0.0.1:8090")
    parser.add_argument("--tts-url", default="http://29.213.195.135:8100")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--agentic", action="store_true",
                        help="Enable the OpenAI Agents SDK bridge protocol")
    parser.add_argument("--mac-auth-file", type=Path)
    parser.add_argument("--mac-audit-file", type=Path)
    parser.add_argument("--mac-m2-policy-file", type=Path)
    parser.add_argument("--agent-frontend-url", default="http://127.0.0.1:3000")
    parser.add_argument("--agent-backend-url", default="http://127.0.0.1:8081")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    web.run_app(create_app(
        mimo_url=args.mimo_url,
        tts_url=args.tts_url,
        config_path=args.config,
        agentic=args.agentic,
        mac_auth_file=args.mac_auth_file,
        mac_audit_file=args.mac_audit_file,
        mac_m2_policy_file=args.mac_m2_policy_file,
        agent_frontend_url=args.agent_frontend_url,
        agent_backend_url=args.agent_backend_url,
    ), host=args.host, port=args.port,
                handler_cancellation=True)


if __name__ == "__main__":
    main()
