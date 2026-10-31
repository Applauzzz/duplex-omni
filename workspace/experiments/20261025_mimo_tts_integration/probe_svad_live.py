"""Run one no-clobber live SVAD WebSocket probe against a WAV fixture."""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import wave

import cv2
import numpy as np
from aiohttp import ClientSession, ClientTimeout


VIDEO_COLORS = (
    ("red", (0, 0, 255)),
    ("green", (0, 255, 0)),
    ("blue", (255, 0, 0)),
)


def color_frame(index: int) -> dict[str, str]:
    name, bgr = VIDEO_COLORS[min(index, len(VIDEO_COLORS) - 1)]
    image = np.full((224, 224, 3), bgr, dtype=np.uint8)
    cv2.putText(
        image, name.upper(), (22, 112), cv2.FONT_HERSHEY_SIMPLEX,
        1.0, (255, 255, 255), 2, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("JPEG probe frame encoding failed")
    return {"format": "jpeg", "data": base64.b64encode(encoded.tobytes()).decode()}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--wav", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--playback-active", action="store_true")
    parser.add_argument("--stop-after-semantic", action="store_true")
    parser.add_argument("--video-colors", action="store_true")
    parser.add_argument("--video-frame-limit", type=int, default=0)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_root / f"live_svad_probe_{stamp}_{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    with wave.open(str(args.wav), "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2:
            raise ValueError(f"Expected mono PCM16 WAV, got {source.getparams()}")
        sample_rate_hz = source.getframerate()
        pcm = source.readframes(source.getnframes())

    chunk_bytes = sample_rate_hz
    chunks = [pcm[index:index + chunk_bytes]
              for index in range(0, len(pcm), chunk_bytes)]
    silence = bytes(chunk_bytes)
    events: list[dict[str, object]] = []
    timeout = ClientTimeout(total=120)
    async with ClientSession(timeout=timeout, trust_env=False) as client:
        async with client.ws_connect(args.base_url.rstrip("/") + "/ws") as ws:
            await ws.send_json({
                "type": "configure",
                "tts_enabled": False,
                "audio_chunk_ms": 500,
                "min_speech_duration_ms": 96,
                "retain_interrupted_context": True,
            })
            configured = await ws.receive_json()
            events.append(configured)
            if configured.get("type") != "configured":
                raise RuntimeError(f"Configure failed: {configured}")
            if args.playback_active:
                await ws.send_json({"type": "playback.state", "active": True})

            sent_video_frames = 0

            async def send_audio(data: bytes, *, frame_index: int | None = None) -> bool:
                nonlocal sent_video_frames
                payload = {
                    "type": "audio",
                    "audio": base64.b64encode(data).decode("ascii"),
                    "format": "pcm16",
                    "sample_rate_hz": sample_rate_hz,
                }
                if (
                    args.video_colors
                    and frame_index is not None
                    and (args.video_frame_limit <= 0
                         or sent_video_frames < args.video_frame_limit)
                ):
                    payload["video_frame"] = color_frame(frame_index)
                    sent_video_frames += 1
                await ws.send_json(payload)
                while True:
                    event = await ws.receive_json()
                    events.append(event)
                    if event.get("type") in {"transition", "semantic_error", "error"}:
                        transition = event.get("transition")
                        return bool(isinstance(transition, dict)
                                    and transition.get("request_kind") == "VASD_SEM")

            stopped_after_semantic = False
            for index, chunk in enumerate(chunks):
                if await send_audio(chunk, frame_index=index) and args.stop_after_semantic:
                    stopped_after_semantic = True
                    break
            if not stopped_after_semantic:
                for _ in range(4):
                    if await send_audio(silence) and args.stop_after_semantic:
                        stopped_after_semantic = True
                        break

            try:
                if stopped_after_semantic:
                    raise TimeoutError
                async with asyncio.timeout(45):
                    while True:
                        event = await ws.receive_json()
                        events.append(event)
                        if event.get("type") in {"chat.done", "chat.error", "error"}:
                            break
            except TimeoutError:
                if stopped_after_semantic:
                    pass
                else:
                    events.append({"type": "probe.timeout"})

    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "wav": str(args.wav.resolve()),
        "playback_active": args.playback_active,
        "sample_rate_hz": sample_rate_hz,
        "audio_chunks": len(chunks),
        "video_colors": args.video_colors,
        "video_frame_limit": args.video_frame_limit,
        "sent_video_frames": sent_video_frames,
        "stopped_after_semantic": stopped_after_semantic,
        "event_types": [event.get("type") for event in events],
        "transitions": [event.get("transition") for event in events
                        if event.get("type") == "transition"],
        "terminal": events[-1] if events else None,
    }
    (output / "events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
