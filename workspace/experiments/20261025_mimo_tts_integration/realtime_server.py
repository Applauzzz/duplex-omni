"""Existing realtime_web assets backed by the real duplex session runner."""

import argparse
import asyncio
import hashlib
import json
import logging
from pathlib import Path
import uuid

from aiohttp import ClientSession, WSMsgType, web

from vllm_omni.config.stage_config import DuplexSessionRuntimeConfig
from vllm_omni.engine.duplex.config import DuplexSessionConfig
from vllm_omni.engine.duplex.messages import (
    CloseDuplexSessionMessage, DuplexSessionCommandMessage, OpenDuplexSessionMessage,
)
from vllm_omni.engine.duplex.session.manager import DuplexSessionManager
from vllm_omni.entrypoints.duplex.realtime_input import RealtimeEnvelope

from backend import Backend, ROOT, client_timeout
from realtime_backend import ExternalStagePort, MiMoTTSPlugin
from server import chat, preview


ASSETS = ROOT / "vllm-omni/examples/online_serving/realtime_web/app"
LOG = logging.getLogger("mimo_tts.realtime")


async def index(request):
    digest = hashlib.sha256()
    for path in sorted((ASSETS / "static").rglob("*.js")):
        digest.update(path.read_bytes())
    digest.update(Path(__file__).with_name("mimo_profile.js").read_bytes())
    version = digest.hexdigest()[:12]
    config = json.dumps({
        "model": "mimo-v2.6-flash", "profile": "mimo-tts", "adapter": "vad",
        "realtimePath": "v1/realtime", "appVersion": version,
    }).replace("<", "\\u003c")
    html = (ASSETS / "index.html").read_text()
    html = html.replace("__FULL_DUPLEX_CONFIG__", config)
    html = html.replace("__FULL_DUPLEX_APP_VERSION__", version)
    html = html.replace(
        '<script src="static/app.js',
        f'<script src="/mimo_profile.js?v={version}"></script>\n    <script src="static/app.js',
    )
    return web.Response(text=html, content_type="text/html",
                        headers={"Cache-Control": "no-store"})


class ConnectionSink:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=512)
        self.overflow = asyncio.Event()

    def put_nowait(self, message):
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflow.set()

    async def put(self, message):
        self.put_nowait(message)


async def realtime(request):
    ws = web.WebSocketResponse(max_msg_size=1024 * 1024, heartbeat=20)
    await ws.prepare(request)
    sid = "mimo-" + uuid.uuid4().hex
    output = ConnectionSink()
    results = asyncio.Queue()
    port = ExternalStagePort(request.app["backend"])
    manager = DuplexSessionManager(
        plugin=MiMoTTSPlugin(), stage_port=port, output_sink=output,
        result_sink=results, runtime_config=request.app["runtime"], model_config=None,
    )
    manager.vad_backend_provider = request.app["vad_provider"]
    port.manager = manager
    envelope = RealtimeEnvelope.from_query_params(request.query)
    envelope.default_model = "mimo-v2.6-flash"
    opened = False
    reserved = False

    async def send():
        try:
            while True:
                message = await output.queue.get()
                payload = message.event.to_realtime()
                await ws.send_json(payload)
                if payload["type"] == "session.closed":
                    await ws.close()
                    return
        except (ConnectionError, RuntimeError):
            await ws.close()

    async def monitor():
        await output.overflow.wait()
        await ws.close(code=1013, message=b"Output backpressure")

    sender = asyncio.create_task(send())
    watcher = asyncio.create_task(monitor())
    shutdown = asyncio.Event()
    reaper = asyncio.create_task(manager.reaper_loop(shutdown))
    request.app["connections"].add((manager, port))

    async def receive():
        nonlocal opened, reserved
        async for frame in ws:
            if frame.type != WSMsgType.TEXT:
                if frame.type == WSMsgType.ERROR:
                    break
                continue
            payload = None
            try:
                payload = json.loads(frame.data)
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON event.")
                if not opened:
                    if payload.get("type") != "session.update":
                        raise ValueError("Send session.update before audio.")
                    if len(request.app["active_sessions"]) >= request.app["runtime"].max_sessions:
                        await ws.send_json(envelope.error_payload(
                            "resource_exhausted", "Realtime session capacity exhausted."))
                        await ws.close(code=1013)
                        break
                    request.app["active_sessions"].add(sid)
                    reserved = True
                    session_payload = payload.get("session")
                    if not isinstance(session_payload, dict):
                        raise ValueError("Expected session object.")
                    session_payload = dict(session_payload)
                    if session_payload.get("model", "mimo-v2.6-flash") != "mimo-v2.6-flash":
                        raise ValueError("Only mimo-v2.6-flash is available.")
                    envelope.note_session_payload(session_payload)
                    config = DuplexSessionConfig.from_realtime(
                        session_payload, model="mimo-v2.6-flash",
                        server_vad_defaults=request.app["runtime"].server_vad_defaults,
                    )
                    await manager.handle(OpenDuplexSessionMessage(
                        control_id=uuid.uuid4().hex, session_id=sid, session_config=config))
                    result = results.get_nowait()
                    if not result.ok:
                        raise ValueError(result.error_message)
                    opened = True
                    envelope.opened = True
                    continue
                if envelope.is_envelope_event(payload):
                    raise ValueError("Connection resume is not enabled.")
                command = envelope.translate(payload)
                manager.dispatch(DuplexSessionCommandMessage(session_id=sid, command=command))
            except (ValueError, TypeError, KeyError) as error:
                if reserved and not opened:
                    request.app["active_sessions"].discard(sid)
                    reserved = False
                await ws.send_json(envelope.error_payload(
                    getattr(error, "code", "bad_event"), str(error)[:300],
                    event_id=payload.get("event_id") if isinstance(payload, dict) else None))
    async def cleanup():
        shutdown.set()
        try:
            await manager.handle(CloseDuplexSessionMessage(
                control_id=uuid.uuid4().hex, session_id=sid, reason="disconnect"))
        finally:
            await port.shutdown()
            await manager.shutdown()
            request.app["active_sessions"].discard(sid)
            request.app["connections"].discard((manager, port))
            for task in (sender, watcher, reaper):
                task.cancel()
            await asyncio.gather(sender, watcher, reaper, return_exceptions=True)
            LOG.info("%s connection closed, external tasks=%d", sid, len(port.tasks))

    try:
        await receive()
    finally:
        # aiohttp cancels handlers on disconnect, including during finalization.
        # Track cleanup separately so cancellation cannot strand admission slots.
        task = asyncio.create_task(cleanup(), name=f"cleanup-{sid}")
        request.app["cleanup_tasks"].add(task)
        task.add_done_callback(request.app["cleanup_tasks"].discard)
        await asyncio.shield(task)
    return ws


async def context(app):
    from vllm_omni.engine.duplex.vad import SileroVADBackendProvider
    app["vad_provider"] = SileroVADBackendProvider()
    # Load the existing detector before admitting a call; never silently run without VAD.
    backend = await asyncio.to_thread(app["vad_provider"].get)
    LOG.info("VAD backend loaded: %s", type(backend).__name__)
    async with ClientSession(trust_env=False, timeout=client_timeout()) as client:
        app["client"] = client
        app["backend"] = Backend(client, app["mimo_url"], app["tts_url"])
        yield
        if app["cleanup_tasks"]:
            await asyncio.gather(*tuple(app["cleanup_tasks"]), return_exceptions=True)
        for manager, port in tuple(app["connections"]):
            await port.shutdown()
            await manager.shutdown()


def create_app():
    from collections import deque
    app = web.Application(client_max_size=5 * 1024 * 1024)
    app["mimo_url"] = "http://127.0.0.1:8090"
    app["tts_url"] = "http://127.0.0.1:8093"
    app["runtime"] = DuplexSessionRuntimeConfig(
        max_sessions=1, max_pending_turns_per_session=4,
        server_vad_defaults={"threshold": 0.5, "prefix_padding_ms": 300,
                             "silence_duration_ms": 500, "min_speech_duration_ms": 96,
                             "create_response": True, "interrupt_response": True},
    )
    app["connections"] = set()
    app["cleanup_tasks"] = set()
    app["active_sessions"] = set()
    app["gate"] = asyncio.Semaphore(2)
    app["outcomes"] = deque(maxlen=32)
    app.cleanup_ctx.append(context)
    app.router.add_get("/", index)
    app.router.add_get("/v1/realtime", realtime)
    app.router.add_static("/static/", ASSETS / "static")
    app.router.add_get("/mimo_profile.js", lambda request: web.FileResponse(
        Path(__file__).with_name("mimo_profile.js")))
    app.router.add_get("/manual", lambda request: web.FileResponse(
        Path(__file__).with_name("chat.html")))
    app.router.add_get("/capture_worklet.js", lambda request: web.FileResponse(
        ASSETS / "static/pcm_worklet.js"))
    app.router.add_get("/tts", preview.index)
    app.router.add_get("/api/status", preview.status)
    app.router.add_post("/api/speech", preview.speech)
    app.router.add_post("/api/chat", chat)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    web.run_app(create_app(), host=args.host, port=args.port, handler_cancellation=True)


if __name__ == "__main__":
    main()
