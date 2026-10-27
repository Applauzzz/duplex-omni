"""Standalone browser acceptance service for AVAD + MiMo semantic VAD + FSM."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
from pathlib import Path
import time
import uuid

from aiohttp import ClientSession, WSMsgType, web

from backend import client_timeout
from semantic_vad import (
    DEFAULT_CHAT_PROMPT,
    DEFAULT_VAED_PROMPT,
    DEFAULT_VASD_PROMPT,
    InvalidSemanticCommand,
    InputEvent,
    MiMoChatProvider,
    MiMoSemanticVADProvider,
    SemanticRealtimeAdapter,
    SemanticVADConfig,
    audio_chunks_to_wav,
)


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
    semantic_config = {key: value for key, value in raw_config.items() if key != "audio_chunk_ms"}
    config = SemanticVADConfig.from_mapping({"type": "semantic_vad", **semantic_config})
    prompts = {}
    for name in ("vasd_prompt", "vaed_prompt", "chat_prompt"):
        value = raw_prompts.get(name)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise ValueError(f"SVAD config prompts.{name} must be a non-empty string of at most 4096 characters")
        prompts[name] = value
    return {
        "config": {
            "audio_chunk_ms": int(audio_chunk_ms),
            "threshold": config.threshold,
            "prefix_padding_ms": config.prefix_padding_ms,
            "silence_duration_ms": config.silence_duration_ms,
            "min_speech_duration_ms": config.min_speech_duration_ms,
            "max_buffered_chunks": config.max_buffered_chunks,
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
    return web.json_response({
        "mimo": healthy,
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
    send_lock = asyncio.Lock()

    async def send(payload):
        async with send_lock:
            await ws.send_json(payload)

    async def cancel_chat(reason):
        nonlocal chat_task, chat_turn_id
        task = chat_task
        if task is None or task.done():
            chat_task = None
            chat_turn_id = None
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        chat_task = None
        await send({"type": "chat.cancelled", "turn_id": chat_turn_id, "reason": reason})
        chat_turn_id = None

    async def run_chat(turn_id, audio_chunks):
        text = ""
        audio_wav = base64.b64encode(audio_chunks_to_wav(audio_chunks)).decode("ascii")
        await send({
            "type": "chat.started",
            "turn_id": turn_id,
            "audio_chunk_count": len(audio_chunks),
        })
        try:
            async for delta in request.app["chat_provider"].stream_reply(
                audio_chunks,
                history=history,
                prompt=prompts["chat_prompt"],
                context={"request_id": f"{session_id}-{turn_id}"},
            ):
                text += delta
                await send({"type": "chat.delta", "turn_id": turn_id, "delta": delta})
            history.append({"audio_wav": audio_wav, "assistant": text})
            del history[:-4]
            await send({"type": "chat.done", "turn_id": turn_id, "text": text})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOG.exception("MiMo Chat failed session=%s turn=%s", session_id, turn_id)
            await send({"type": "chat.error", "turn_id": turn_id, "message": str(error)[:500]})

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
                        "threshold": config.threshold,
                        "prefix_padding_ms": config.prefix_padding_ms,
                        "silence_duration_ms": config.silence_duration_ms,
                        "min_speech_duration_ms": config.min_speech_duration_ms,
                        "max_buffered_chunks": config.max_buffered_chunks,
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
            if event_type == "reset":
                await cancel_chat("fsm_reset")
                if adapter is not None:
                    adapter.reset()
                sequence = 0
                history.clear()
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
                    context={"request_id": f"{session_id}-{sequence}", **prompts},
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
                await cancel_chat("new_decode")
                chat_turn_id = sequence
                chat_task = asyncio.create_task(
                    run_chat(sequence, output.decode_audio),
                    name=f"chat-{session_id}-{sequence}",
                )
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
        yield


def create_app(*, mimo_url="http://127.0.0.1:8090", config_path=DEFAULT_CONFIG_PATH):
    app = web.Application(client_max_size=2 * 1024 * 1024)
    app["mimo_url"] = mimo_url.rstrip("/")
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
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    web.run_app(create_app(mimo_url=args.mimo_url, config_path=args.config), host=args.host, port=args.port,
                handler_cancellation=True)


if __name__ == "__main__":
    main()
