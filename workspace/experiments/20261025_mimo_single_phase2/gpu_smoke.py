"""Real-service PCM/SSE probes. All artifacts are exclusively created."""

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import wave

import aiohttp
import numpy as np


SAMPLES = [
    ("chinese", "\u4f60\u597d\uff0c\u6211\u662f\u8bed\u97f3\u52a9\u624b\u3002\u6211\u4eec\u53ef\u4ee5\u4e00\u8fb9\u4ea4\u6d41\uff0c\u4e00\u8fb9\u5904\u7406\u65b0\u7684\u95ee\u9898\u3002", "Chinese"),
    ("english", "Hello. The meeting starts at nine tomorrow morning. Please bring your notes.", "English"),
    ("numbers", "\u8ba2\u5355\u53f7\u662f12345\uff0c\u603b\u4ef7\u662f89.50\u5143\uff0c\u65e5\u671f\u662f2026\u5e7410\u670825\u65e5\u3002", "Chinese"),
    ("mixed", "\u4eca\u5929\u6d4b\u8bd5MiMo\u548cQwen TTS\u3002\u7248\u672c\u662f2.6\uff0c\u8bf7\u8bf4hello world\uff0c\u7136\u540e\u7ee7\u7eed\u4e2d\u6587\u3002", "Auto"),
    ("long", "This is a streaming speech test. We will read several sentences in order. "
     "Every sentence must be delivered exactly once. The final sentence says that "
     "the experiment has now finished.", "English"),
]
ENERGY_RMS = 0.002
ENERGY_FRAME_SAMPLES = 480


def first_energy_offset(payload):
    size = len(payload) // 2
    pcm = np.frombuffer(payload, dtype="<i2", count=size).astype(np.float32) / 32768
    for offset in range(0, size - ENERGY_FRAME_SAMPLES + 1, ENERGY_FRAME_SAMPLES):
        frame = pcm[offset:offset + ENERGY_FRAME_SAMPLES]
        if float(np.sqrt(np.mean(frame * frame))) >= ENERGY_RMS:
            return offset / 24000
    return None


def save_json(path, data):
    with path.open("x", encoding="utf-8") as output:
        json.dump(data, output, indent=2, ensure_ascii=False)


async def ready(client, url, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            async with client.get(url + "/health", timeout=aiohttp.ClientTimeout(total=3)) as response:
                if response.status == 200:
                    return
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(5)
    raise TimeoutError(f"Service not ready: {url}")


async def metrics(client, url, path):
    async with client.get(url + "/metrics") as response:
        text = await response.text()
        if response.status != 200:
            raise RuntimeError(f"Metrics HTTP {response.status}: {text[:300]}")
    with path.open("x") as output:
        output.write(text)
    return text


def speech_body(text, language):
    return {"model": "qwen3-tts-customvoice", "input": text, "voice": "vivian",
            "task_type": "CustomVoice", "language": language, "stream": True,
            "stream_format": "audio", "response_format": "pcm", "sample_rate": 24000,
            "max_new_tokens": 1024, "seed": 42, "initial_codec_chunk_frames": 1}


async def speech(client, url, out, name, text, language, cancel=None):
    request = speech_body(text, language)
    save_json(out / f"{name}_request.json", request)
    started = time.monotonic()
    result = {"name": name, "reference": text, "cancel_mode": cancel, "chunks": [],
              "energy_threshold_rms": ENERGY_RMS, "energy_frame_ms": 20,
              "first_energy_received_s": None, "first_energy_audio_offset_s": None,
              "utc": datetime.now(timezone.utc).isoformat()}
    payload = bytearray()
    try:
        async with client.post(url + "/v1/audio/speech", json=request) as response:
            result["status"] = response.status
            result["headers_s"] = time.monotonic() - started
            result["headers"] = dict(response.headers)
            if response.status != 200:
                raise RuntimeError((await response.text())[:1000])
            if cancel == "before_audio":
                await asyncio.sleep(0.02)
                response.close()
            else:
                async for chunk, end_of_http_chunk in response.content.iter_chunks():
                    if not chunk:
                        continue
                    payload.extend(chunk)
                    arrival = time.monotonic() - started
                    result["chunks"].append({"s": arrival, "bytes": len(chunk),
                                             "http_chunk_end": end_of_http_chunk})
                    if result["first_energy_received_s"] is None:
                        offset = first_energy_offset(payload)
                        if offset is not None:
                            result["first_energy_received_s"] = arrival
                            result["first_energy_audio_offset_s"] = offset
                    if cancel == "during_audio" and result["first_energy_received_s"] is not None:
                        response.close()
                        break
            result["client_closed_s"] = time.monotonic() - started if cancel else None
        result["total_s"] = time.monotonic() - started
        if payload:
            if len(payload) % 2:
                raise ValueError("PCM16 byte count is not even")
            pcm = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768
            result.update(bytes=len(payload), sample_rate=24000, channels=1,
                          duration_s=len(pcm) / 24000, rms=float(np.sqrt(np.mean(pcm * pcm))),
                          peak=float(np.max(np.abs(pcm))),
                          sha256=hashlib.sha256(payload).hexdigest(),
                          ttfa_s=result["chunks"][0]["s"],
                          rtf=result["total_s"] / (len(pcm) / 24000))
            with (out / f"{name}.pcm").open("xb") as output:
                output.write(payload)
            with (out / f"{name}.wav").open("xb") as output:
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(payload)
            if not cancel and result["first_energy_received_s"] is None:
                raise ValueError("PCM is silent")
        elif not cancel:
            raise ValueError("No PCM bytes")
        result["transport_complete"] = not cancel
        if cancel == "during_audio" and result["first_energy_received_s"] is None:
            raise ValueError("No effective speech before cancellation")
    except Exception as error:
        result["error"] = repr(error)
        raise
    finally:
        save_json(out / f"{name}_result.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def tts(client, args, out):
    url = args.tts_url
    await ready(client, url, args.wait)
    await metrics(client, url, out / "tts_metrics_before.txt")
    if args.mode != "tts-cancel":
        for name, text, language in SAMPLES:
            await speech(client, url, out, name, text, language)
    long_text = ("We are testing cancellation of a very long utterance. "
                 "The backend must stop generating when this request disconnects. ") * 12
    for mode in ("before_audio", "during_audio"):
        await metrics(client, url, out / f"cancel_{mode}_metrics_before.txt")
        await speech(client, url, out, f"cancel_{mode}", long_text, "English", mode)
        await asyncio.sleep(6)
        await metrics(client, url, out / f"cancel_{mode}_metrics_after.txt")
        await asyncio.sleep(12)
        await metrics(client, url, out / f"cancel_{mode}_metrics_settled.txt")
        await speech(client, url, out, f"recover_{mode}", "The next request works.", "English")
    await metrics(client, url, out / "tts_metrics_final.txt")


async def mimo_text(client, args, out):
    url = args.mimo_url
    await ready(client, url, args.wait)
    request = {"model": "mimo-v2.6-flash", "messages": [
        {"role": "user", "content": "Reply with one short sentence containing the word ready."}],
        "max_tokens": 128, "temperature": 0.0, "stream": True,
        "chat_template_kwargs": {"enable_thinking": False}}
    save_json(out / "mimo_text_request.json", request)
    started = time.monotonic()
    events, content, reasoning, done = [], [], [], False
    async with client.post(url + "/v1/chat/completions", json=request) as response:
        if response.status != 200:
            raise RuntimeError((await response.text())[:1000])
        async for line in response.content:
            line = line.decode().strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                done = True
                break
            event = json.loads(data)
            events.append({"s": time.monotonic() - started, "event": event})
            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                if delta.get("content"):
                    content.append(delta["content"])
                if delta.get("reasoning") or delta.get("reasoning_content"):
                    reasoning.append(delta.get("reasoning") or delta["reasoning_content"])
    result = {"events": events, "content": "".join(content), "reasoning": "".join(reasoning),
              "done": done, "total_s": time.monotonic() - started}
    save_json(out / "mimo_text_result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if not done or "ready" not in result["content"].lower() or reasoning:
        raise AssertionError("MiMo SSE content/thinking separation failed")
    await metrics(client, url, out / "mimo_cancel_metrics_before.txt")
    request["messages"] = [{"role": "user", "content": "List the numbers from one to two thousand, one per line, without skipping any."}]
    request["max_tokens"] = 4096
    save_json(out / "mimo_cancel_request.json", request)
    started = time.monotonic()
    cancel_events = []
    async with client.post(url + "/v1/chat/completions", json=request) as response:
        if response.status != 200:
            raise RuntimeError((await response.text())[:1000])
        async for line in response.content:
            line = line.decode().strip()
            if line.startswith("data:") and line[5:].strip() != "[DONE]":
                event = json.loads(line[5:])
                cancel_events.append(event)
                if any(choice.get("delta", {}).get("content") for choice in event.get("choices", [])):
                    response.close()
                    break
    save_json(out / "mimo_cancel_result.json", {
        "client_closed_s": time.monotonic() - started, "events": cancel_events})
    await asyncio.sleep(6)
    await metrics(client, url, out / "mimo_cancel_metrics_after.txt")
    recovery = {"model": "mimo-v2.6-flash", "messages": [
        {"role": "user", "content": "Reply only with recovered."}], "max_tokens": 32,
        "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False}}
    async with client.post(url + "/v1/chat/completions", json=recovery) as response:
        data = await response.json()
        save_json(out / "mimo_recovery.json", {"status": response.status, "response": data})
        if response.status != 200 or "recovered" not in data["choices"][0]["message"]["content"].lower():
            raise AssertionError("MiMo post-cancel recovery failed")


async def mimo_audio(client, args, out):
    url = args.mimo_url
    await ready(client, url, args.wait)
    samples = args.samples or out
    for name, reference, _language in SAMPLES:
        wav = samples / f"{name}.wav"
        request = {"model": "mimo-v2.6-flash", "messages": [
            {"role": "system", "content": "You are a speech transcription tool. Transcribe only what is audible, in the original language. Do not answer, correct or add content."},
            {"role": "user", "content": [
                {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(wav.read_bytes()).decode(), "format": "wav"}},
                {"type": "text", "text": "Transcribe this recording exactly."}]}],
            "max_tokens": 400, "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False}}
        started = time.monotonic()
        async with client.post(url + "/v1/chat/completions", json=request) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError(json.dumps(data)[:1000])
        result = {"reference": reference, "asr": data["choices"][0]["message"]["content"],
                  "total_s": time.monotonic() - started, "response": data,
                  "note": "Auxiliary MiMo ASR, not independent listening acceptance"}
        save_json(out / f"{name}_mimo_asr.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


async def drain_check(client, args, out):
    for role, url in (("tts", args.tts_url), ("mimo", args.mimo_url)):
        await ready(client, url, args.wait)
        started = time.monotonic()
        result = {"role": role, "mode": "wait", "clear_cache": False}
        try:
            async with client.post(url + "/pause?mode=wait&clear_cache=false",
                                   timeout=aiohttp.ClientTimeout(total=5)) as response:
                result.update(status=response.status, body=await response.text(),
                              pause_s=time.monotonic() - started)
        except Exception as error:
            result["error"] = repr(error)
        finally:
            async with client.post(url + "/resume",
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                result.update(resume_status=response.status, resume_body=await response.text())
            save_json(out / f"{role}_drain.json", result)
            print(json.dumps(result), flush=True)
        await metrics(client, url, out / f"{role}_drain_metrics.txt")
        if result.get("status") != 200 or result.get("resume_status") != 200:
            raise RuntimeError(f"{role} drain unavailable: {result}")


async def main(args):
    out = args.run / f"smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{args.mode}"
    out.mkdir(exist_ok=False)
    print(f"ARTIFACTS={out}", flush=True)
    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=300)) as client:
        if args.mode == "drain":
            await drain_check(client, args, out)
        if args.mode in ("tts", "tts-cancel", "all"):
            await tts(client, args, out)
        if args.mode in ("mimo", "mimo-text", "all"):
            await mimo_text(client, args, out)
        if args.mode in ("mimo", "mimo-audio", "all"):
            await mimo_audio(client, args, out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--mode", choices=["tts", "tts-cancel", "mimo", "mimo-text", "mimo-audio", "drain", "all"], default="all")
    parser.add_argument("--samples", type=Path)
    parser.add_argument("--tts-url", default="http://127.0.0.1:8093")
    parser.add_argument("--mimo-url", default="http://127.0.0.1:8090")
    parser.add_argument("--wait", type=float, default=1800)
    asyncio.run(main(parser.parse_args()))
