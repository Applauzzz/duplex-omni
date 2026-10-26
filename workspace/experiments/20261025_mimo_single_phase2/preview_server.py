"""TTS preview with an explicit bind address and fixed loopback upstream."""

import argparse
import asyncio
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout, web


async def index(request):
    return web.FileResponse(Path(__file__).with_name("preview.html"))


async def status(request):
    result = {}
    for role, port in (("tts", 8093), ("mimo", 8090)):
        try:
            async with request.app["client"].get(
                f"http://127.0.0.1:{port}/health", timeout=ClientTimeout(total=3)
            ) as response:
                result[role] = response.status == 200
        except (ClientError, OSError, asyncio.TimeoutError):
            result[role] = False
    return web.json_response(result)


async def speech(request):
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(text="Invalid JSON.") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="Expected a JSON object.")
    text = body.get("input")
    if not isinstance(text, str) or not text.strip() or len(text) > 1600:
        raise web.HTTPBadRequest(text="Text must contain 1-1600 characters.")
    payload = {
        "model": "qwen3-tts-customvoice", "input": text,
        "voice": body.get("voice", "vivian"),
        "language": body.get("language", "Auto"),
        "task_type": "CustomVoice", "stream": True, "stream_format": "audio",
        "response_format": "pcm", "sample_rate": 24000, "max_new_tokens": 1024,
        "seed": 42, "initial_codec_chunk_frames": 1,
    }
    try:
        upstream = await request.app["client"].post(
            "http://127.0.0.1:8093/v1/audio/speech", json=payload
        )
    except (ClientError, OSError, asyncio.TimeoutError):
        raise web.HTTPBadGateway(text="TTS backend unavailable.") from None
    async with upstream:
        if upstream.status != 200:
            return web.Response(status=upstream.status, body=await upstream.read())
        output = web.StreamResponse(headers={
            "Content-Type": "audio/pcm", "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        })
        await output.prepare(request)
        try:
            async for chunk in upstream.content.iter_any():
                await output.write(chunk)
            await output.write_eof()
        except (ConnectionResetError, BrokenPipeError):
            pass
        return output


async def client_context(app):
    async with ClientSession(trust_env=False, timeout=ClientTimeout(total=300)) as client:
        app["client"] = client
        yield


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7866)
    args = parser.parse_args()
    app = web.Application(client_max_size=64 * 1024)
    app.cleanup_ctx.append(client_context)
    app.router.add_get("/", index)
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/speech", speech)
    web.run_app(app, host=args.host, port=args.port, handler_cancellation=True)


if __name__ == "__main__":
    main()
