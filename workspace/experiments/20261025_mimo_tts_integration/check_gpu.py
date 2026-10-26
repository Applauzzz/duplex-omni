"""Verify actual MiMo replies reach GPU TTS; retain exclusive audio/evidence."""

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid
import wave

from aiohttp import ClientSession, ClientTimeout
import numpy as np

from backend import Backend, validate_request
from test_integration import serve
from aiohttp import web


def save(path, obj):
    with path.open("x") as file:
        json.dump(obj, file, indent=2, ensure_ascii=True)


async def main(args):
    output = args.run / (
        datetime.now(timezone.utc).strftime("integration_check_%Y%m%dT%H%M%SZ")
        + "_" + uuid.uuid4().hex[:8]
    )
    output.mkdir(exist_ok=False)
    results = {"status": "running", "base_url": args.base_url, "cases": []}
    async with ClientSession(trust_env=False, timeout=ClientTimeout(total=300)) as client:
        async def turn(label, body):
            save(output / f"{label}_request.json", body)
            started = time.monotonic()
            events, chunks = [], []
            async with client.post(args.base_url + "/api/chat", json=body) as response:
                assert response.status == 200, await response.text()
                async for line in response.content:
                    event = json.loads(line)
                    events.append({"s": time.monotonic() - started, "event": {
                        k: v for k, v in event.items() if k != "pcm"
                    }})
                    if event["type"] == "audio":
                        chunks.append(base64.b64decode(event["pcm"]))
                    if event["type"] == "error":
                        raise AssertionError(event)
            assert events[-1]["event"]["type"] == "done", events[-1]
            text = "".join(x["event"]["delta"] for x in events if x["event"]["type"] == "text")
            assert text == events[-1]["event"]["text"]
            pcm = b"".join(chunks)
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(samples * samples)))
            assert rms > .002
            segments = [x["event"] for x in events if x["event"]["type"] == "segment"]
            for segment in segments:
                assert segment["text"] == text[segment["start"]:segment["end"]]
            with (output / f"{label}.wav").open("xb") as file:
                with wave.open(file, "wb") as recording:
                    recording.setparams((1, 2, 24000, 0, "NONE", ""))
                    recording.writeframes(pcm)
            item = {
                "case": label, "text": text, "rms": rms, "bytes": len(pcm),
                "duration_s": len(samples) / 24000, "segments": len(segments),
                "first_audio_s": next(x["s"] for x in events if x["event"]["type"] == "audio"),
                "model_done_s": next(x["s"] for x in events if x["event"]["type"] == "model_done"),
                "elapsed_s": time.monotonic() - started,
                "sha256": hashlib.sha256(pcm).hexdigest(), "events": events,
            }
            save(output / f"{label}_result.json", item)
            results["cases"].append({k: v for k, v in item.items() if k != "events"})
            return text
        try:
            async with client.get(args.base_url + "/") as response:
                assert response.status == 200 and "MiMo + Qwen3-TTS" in await response.text()
            async with client.get(args.base_url + "/tts") as response:
                assert response.status == 200 and "Qwen3-TTS" in await response.text()
            prompt = "\u8bf7\u53ea\u7528\u4e00\u53e5\u8bdd\u56de\u7b54\uff1a\u4e24\u52a0\u4e24\u7b49\u4e8e\u51e0\uff1f"
            text = await turn("text", {"input": prompt, "voice": "vivian", "language": "Chinese"})
            assert "\u56db" in text or "4" in text, text
            followup = await turn("history", {"input": "\u6211\u521a\u624d\u95ee\u4e86\u4ec0\u4e48\uff1f\u4e00\u53e5\u8bdd\u56de\u7b54\u3002",
                "history": [{"role": "user", "input": prompt}, {"role": "assistant", "input": text}]})
            assert any(token in followup for token in ("\u4e24", "\u52a0", "2", "\u56db", "4")), followup
            async with client.post(args.base_url + "/api/speech", json={
                "input": "\u8bf7\u544a\u8bc9\u6211\uff0c\u4e09\u52a0\u56db\u7b49\u4e8e\u51e0\uff1f",
                "voice": "vivian", "language": "Chinese",
            }) as response:
                assert response.status == 200
                pcm = await response.read()
            with (output / "input.wav").open("xb") as file:
                with wave.open(file, "wb") as recording:
                    recording.setparams((1, 2, 24000, 0, "NONE", ""))
                    recording.writeframes(pcm)
            audio_text = await turn("audio", {"input": "", "audio": {
                "format": "wav", "data": base64.b64encode((output / "input.wav").read_bytes()).decode()
            }})
            assert "\u4e03" in audio_text or "7" in audio_text, audio_text
            for label, wait_type in (("cancel_text", "text"), ("cancel_audio", "audio")):
                async with client.post(args.base_url + "/api/chat", json={
                    "input": "\u8bf7\u8be6\u7ec6\u4ecb\u7ecd\u4e2d\u56fd\u7684\u4e8c\u5341\u4e2a\u57ce\u5e02\uff0c\u6bcf\u4e2a\u57ce\u5e02\u4e94\u53e5\u8bdd\u3002",
                    "max_tokens": 1024,
                }) as response:
                    assert response.status == 200
                    response_id = response.headers["X-Response-Id"]
                    async for line in response.content:
                        event = json.loads(line)
                        if event["type"] == wait_type:
                            response.close()
                            break
                results["cases"].append({"case": label, "response_id": response_id, "trigger": wait_type})
                await asyncio.sleep(1)
            recovered = await turn("recovery", {"input": "\u53ea\u56de\u7b54\uff1a\u6062\u590d\u6b63\u5e38\u3002"})
            assert "\u6062\u590d" in recovered, recovered
            async def slow_mimo(request):
                response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
                await response.prepare(request)
                for text_piece in ("\u4f60\u597d\u3002\u6211", "\u662f\u8bed\u97f3\u52a9\u624b\u3002"):
                    event = {"choices": [{"delta": {"content": text_piece}, "finish_reason": None}]}
                    await response.write(("data: " + json.dumps(event) + "\n\n").encode())
                    await asyncio.sleep(2)
                await response.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
                return response
            app = web.Application()
            app.router.add_post("/v1/chat/completions", slow_mimo)
            runner, url = await serve(app)
            events = []
            started = time.monotonic()
            async def emit(event):
                events.append({"s": time.monotonic() - started, "type": event["type"]})
            try:
                await Backend(client, url).run("slow-real-tts", *validate_request({"input": "hello"}), emit)
            finally:
                await runner.cleanup()
            first = next(x["s"] for x in events if x["type"] == "audio")
            done = next(x["s"] for x in events if x["type"] == "model_done")
            assert first < done, events
            save(output / "slow_real_tts.json", events)
            results["cases"].append({"case": "slow_sse_real_gpu_tts", "first_audio_s": first, "model_done_s": done})
            results["status"] = "pass"
        except BaseException as error:
            results["status"] = "fail"
            results["error"] = repr(error)
            raise
        finally:
            save(output / "summary.json", results)
            print(json.dumps({"output": str(output), **results}, ensure_ascii=True, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    asyncio.run(main(parser.parse_args()))
