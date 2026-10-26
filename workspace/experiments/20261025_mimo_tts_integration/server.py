"""MiMo-to-TTS manual-turn UI, preserving the standalone preview routes."""

import argparse
import asyncio
from collections import deque
import importlib.util
import json
import logging
from pathlib import Path
import uuid

from aiohttp import ClientError, ClientSession, web

from backend import Backend, client_timeout, validate_request


PREVIEW_PATH = Path(__file__).parents[1] / "20261025_mimo_single_phase2/preview_server.py"
_spec = importlib.util.spec_from_file_location("mimo_tts_preview", PREVIEW_PATH)
preview = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preview)
LOG = logging.getLogger("mimo_tts")


async def index(request):
    return web.FileResponse(Path(__file__).with_name("chat.html"),
                            headers={"Cache-Control": "no-store"})


async def capture_worklet(request):
    path = Path(__file__).resolve().parents[3] / (
        "vllm-omni/examples/online_serving/realtime_web/app/static/pcm_worklet.js"
    )
    return web.FileResponse(path)


async def chat(request):
    try:
        body = await request.json()
        validated = validate_request(body)
    except (ValueError, TypeError) as error:
        raise web.HTTPBadRequest(text=str(error)) from None
    gate = request.app["gate"]
    if gate.locked():
        raise web.HTTPTooManyRequests(text="Two replies are already active.")
    async with gate:
        response_id = uuid.uuid4().hex
        outcome = {"response_id": response_id, "status": "running"}
        request.app["outcomes"].append(outcome)
        response = web.StreamResponse(headers={
            "Content-Type": "application/x-ndjson", "Cache-Control": "no-store",
            "X-Accel-Buffering": "no", "X-Response-Id": response_id,
        })
        write_lock = asyncio.Lock()

        async def emit(event):
            async with write_lock:
                await response.write((json.dumps(
                    {"response_id": response_id, **event}, ensure_ascii=True
                ) + "\n").encode())

        try:
            await response.prepare(request)
            await emit({"type": "start", "sample_rate": 24000})
            await request.app["backend"].run(response_id, *validated, emit)
            await response.write_eof()
            outcome["status"] = "complete"
        except asyncio.CancelledError:
            outcome["status"] = "cancelled"
            LOG.info("%s request cancelled", response_id)
            raise
        except (ConnectionResetError, BrokenPipeError):
            outcome["status"] = "disconnected"
            LOG.info("%s client disconnected", response_id)
        except (ClientError, OSError, ValueError, RuntimeError, asyncio.TimeoutError) as error:
            outcome["status"] = "error"
            outcome["error"] = type(error).__name__
            LOG.exception("%s pipeline failed", response_id)
            try:
                await emit({"type": "error", "message": str(error)[:300]})
                await response.write_eof()
            except (ConnectionResetError, BrokenPipeError):
                pass
        return response


async def context(app):
    async with ClientSession(trust_env=False, timeout=client_timeout()) as client:
        app["client"] = client
        app["backend"] = Backend(client, app["mimo_url"], app["tts_url"])
        yield


def create_app(mimo_url="http://127.0.0.1:8090", tts_url="http://127.0.0.1:8093"):
    app = web.Application(client_max_size=5 * 1024 * 1024)
    app["mimo_url"] = mimo_url
    app["tts_url"] = tts_url
    app["gate"] = asyncio.Semaphore(2)
    app["outcomes"] = deque(maxlen=32)
    app.cleanup_ctx.append(context)
    app.router.add_get("/", index)
    app.router.add_get("/capture_worklet.js", capture_worklet)
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
