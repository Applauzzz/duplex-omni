"""Replay continuous PCM through real Silero, MiMo, TTS and duplex ledger."""

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

from aiohttp import ClientSession, ClientTimeout, WSMsgType
import numpy as np


def save(path, value):
    with path.open("x") as file:
        json.dump(value, file, indent=2, ensure_ascii=True)


async def main(args):
    output = args.run / (
        datetime.now(timezone.utc).strftime("realtime_check_%Y%m%dT%H%M%SZ")
        + "_" + uuid.uuid4().hex[:8]
    )
    output.mkdir(exist_ok=False)
    started = time.monotonic()
    events, audio, texts = [], {}, {}
    report = {"status": "running", "base_url": args.base_url,
              "fixture": str(args.fixture), "cases": []}
    with wave.open(str(args.fixture), "rb") as recording:
        assert recording.getframerate() == 24000
        assert recording.getnchannels() == 1 and recording.getsampwidth() == 2
        fixture = recording.readframes(recording.getnframes())
    report["fixture_sha256"] = hashlib.sha256(fixture).hexdigest()
    async with ClientSession(trust_env=False, timeout=ClientTimeout(total=300)) as client:
        async def wait(kind, since=0, predicate=lambda event: True):
            async with asyncio.timeout(120):
                while True:
                    for row in events[since:]:
                        event = row["event"]
                        if event["type"] == "error":
                            raise AssertionError(event)
                        if event["type"] == kind and predicate(event):
                            return event
                    await asyncio.sleep(.01)

        try:
            async with asyncio.timeout(600):
                while True:
                    try:
                        async with client.get(args.base_url + "/") as response:
                            html = await response.text()
                            if response.status == 200 and '"profile": "mimo-tts"' in html:
                                break
                    except (ConnectionError, OSError):
                        pass
                    await asyncio.sleep(1)
            for asset in ("/static/app.js", "/static/pcm_worklet.js",
                          "/static/playback_worklet.js", "/mimo_profile.js", "/tts"):
                async with client.get(args.base_url + asset) as response:
                    assert response.status == 200, asset
                    assert await response.read(), asset
            async with client.get(args.base_url + "/api/status") as response:
                status = await response.json()
                assert status["mimo"] and status["tts"], status
            async with client.ws_connect(args.base_url + "/v1/realtime?duplex=1") as ws:
                async def receive():
                    async for frame in ws:
                        if frame.type != WSMsgType.TEXT:
                            continue
                        event = json.loads(frame.data)
                        rid = event.get("response_id") or event.get("response", {}).get("id")
                        recorded = dict(event)
                        if event["type"] == "response.output_audio.delta":
                            raw = base64.b64decode(event["delta"], validate=True)
                            assert len(raw) % 2 == 0
                            audio.setdefault(rid, bytearray()).extend(raw)
                            recorded["delta"] = f"<{len(raw)} PCM bytes>"
                        elif event["type"] in ("response.output_text.delta",
                                               "response.output_audio_transcript.delta"):
                            texts[rid] = texts.get(rid, "") + event["delta"]
                        events.append({"s": time.monotonic() - started, "event": recorded})

                receiver = asyncio.create_task(receive())

                async def stream(speech):
                    pcm = speech + b"\0\0" * 24000
                    for offset in range(0, len(pcm), 9600):
                        await ws.send_json({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(pcm[offset:offset + 9600]).decode(),
                        })
                        await asyncio.sleep(.2)

                async def text(value):
                    await ws.send_json({"type": "conversation.item.create", "item": {
                        "type": "message", "role": "user",
                        "content": [{"type": "input_text", "text": value}],
                    }})
                    await ws.send_json({"type": "response.create"})

                async def ack(rid):
                    duration = len(audio[rid]) * 1000 // 48000
                    since = len(events)
                    await ws.send_json({"type": "playback.ack", "response_id": rid,
                                        "played_ms": duration, "committed_ms": duration})
                    await wait("playback.acknowledged", since)

                try:
                    await ws.send_json({"type": "session.update", "session": {
                        "model": "mimo-v2.6-flash", "overlap_policy": "barge_in_on_speech",
                        "instructions": "\u4f60\u662f\u8bed\u97f3\u52a9\u624b\u3002\u7528\u6237\u7684\u95ee\u9898\u76f4\u63a5\u7528\u4e00\u53e5\u8bdd\u56de\u7b54\uff0c\u4e0d\u4f7f\u7528Markdown\u3002",
                        "max_tokens": 1024,
                        "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000},
                                           "turn_detection": {"type": "server_vad",
                                               "threshold": .5, "prefix_padding_ms": 300,
                                               "silence_duration_ms": 500,
                                               "create_response": True,
                                               "interrupt_response": True}}},
                    }})
                    opened = await wait("session.updated")
                    assert opened["session"]["audio"]["input"]["turn_detection"]["type"] == "server_vad"
                    since = len(events)
                    await stream(fixture)
                    done = await wait("response.done", since)
                    rid = done["response"]["id"]
                    assert done["response"]["status"] == "completed", done
                    kinds = {row["event"]["type"] for row in events[since:]}
                    for kind in ("input_audio_buffer.speech_started",
                                 "input_audio_buffer.speech_stopped",
                                 "input_audio_buffer.committed"):
                        assert kind in kinds, kinds
                    assert "\u4e03" in texts[rid] or "7" in texts[rid], texts
                    await ack(rid)
                    report["cases"].append({"case": "automatic_voice_turn", "response_id": rid,
                                            "text": texts[rid], "pcm_bytes": len(audio[rid])})
                    since = len(events)
                    await text("\u6211\u521a\u624d\u95ee\u4e86\u4ec0\u4e48\u95ee\u9898\uff1f")
                    done = await wait("response.done", since)
                    history_rid = done["response"]["id"]
                    assert any(token in texts[history_rid] for token in
                               ("\u4e09", "\u56db", "\u52a0", "3", "4")), texts
                    await ack(history_rid)
                    report["cases"].append({"case": "history_followup",
                                            "text": texts[history_rid], "response_id": history_rid})
                    since = len(events)
                    await text("\u8bf7\u4ecb\u7ecd\u4e8c\u5341\u4e2a\u57ce\u5e02\uff0c\u6bcf\u4e2a\u57ce\u5e02\u4e09\u53e5\u8bdd\uff0c\u8bf7\u5c3d\u53ef\u80fd\u8be6\u7ec6\u3002")
                    first = await wait("response.output_audio.delta", since)
                    interrupted_rid = first["response_id"]
                    since = len(events)
                    await stream(fixture)
                    cancelled = await wait("response.done", since, lambda event:
                        event["response"]["id"] == interrupted_rid
                        and event["response"]["status"] == "cancelled")
                    recovered = await wait("response.done", since, lambda event:
                        event["response"]["id"] != interrupted_rid)
                    recovered_rid = recovered["response"]["id"]
                    assert recovered["response"]["status"] == "completed", recovered
                    assert "\u4e03" in texts[recovered_rid] or "7" in texts[recovered_rid], texts
                    cancel_index = next(index for index, row in enumerate(events)
                                        if row["event"] == cancelled)
                    assert not any(row["event"]["type"] == "response.output_audio.delta"
                                   and row["event"].get("response_id") == interrupted_rid
                                   for row in events[cancel_index + 1:])
                    await ack(recovered_rid)
                    report["cases"].append({"case": "speech_barge_in_and_recovery",
                        "cancelled_response_id": interrupted_rid,
                        "recovered_response_id": recovered_rid, "text": texts[recovered_rid]})
                finally:
                    receiver.cancel()
                    await asyncio.gather(receiver, return_exceptions=True)
            report["status"] = "pass"
        except BaseException as error:
            report["status"] = "fail"
            report["error"] = repr(error)
            raise
        finally:
            for index, (rid, pcm) in enumerate(audio.items()):
                with (output / f"response_{index}.wav").open("xb") as file:
                    with wave.open(file, "wb") as recording:
                        recording.setparams((1, 2, 24000, 0, "NONE", ""))
                        recording.writeframes(pcm)
                samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
                report.setdefault("audio", []).append({
                    "response_id": rid, "file": f"response_{index}.wav",
                    "duration_s": len(samples) / 24000,
                    "rms": float(np.sqrt(np.mean(samples * samples))),
                })
            save(output / "events.json", events)
            save(output / "summary.json", report)
            print(json.dumps({"output": str(output), **report}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
