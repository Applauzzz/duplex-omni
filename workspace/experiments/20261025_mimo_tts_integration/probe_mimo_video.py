"""Generate a small MP4 and probe MiMo's OpenAI video_url contract."""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import cv2
import numpy as np
from aiohttp import ClientSession, ClientTimeout


COLORS = (
    ("red", (0, 0, 255)),
    ("green", (0, 255, 0)),
    ("blue", (255, 0, 0)),
)


def generate_video(path: Path, *, width: int = 224, height: int = 224) -> None:
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 1.0, (width, height))
    if not writer.isOpened():
        raise RuntimeError("OpenCV could not open the MP4 writer")
    try:
        for name, bgr in COLORS:
            frame = np.full((height, width, 3), bgr, dtype=np.uint8)
            cv2.putText(
                frame, name.upper(), (22, height // 2), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (255, 255, 255), 2, cv2.LINE_AA)
            writer.write(frame)
    finally:
        writer.release()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_root / f"mimo_video_probe_{stamp}_{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    video_path = output / "colors.mp4"
    generate_video(video_path)
    video_bytes = video_path.read_bytes()
    video_url = "data:video/mp4;base64," + base64.b64encode(video_bytes).decode("ascii")
    payload = {
        "model": "mimo-v2.6-flash",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "video_url", "video_url": {"url": video_url}},
                {"type": "text", "text": "请按时间顺序说出视频中出现的三种主要颜色，只回答颜色。"},
            ],
        }],
        "max_tokens": 64,
        "temperature": 0.0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    timeout = ClientTimeout(total=180, connect=10, sock_read=170)
    async with ClientSession(timeout=timeout, trust_env=False) as client:
        async with client.post(
            args.base_url.rstrip("/") + "/v1/chat/completions",
            json=payload,
            headers={"X-Request-Id": f"mimo-video-probe-{uuid.uuid4().hex}"},
        ) as response:
            body = await response.read()
            status = response.status
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = {"raw_body": body[:2000].decode("utf-8", errors="replace")}
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "video": str(video_path),
        "video_bytes": len(video_bytes),
        "frames": [name for name, _ in COLORS],
        "http_status": status,
        "response": parsed,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps(summary, ensure_ascii=False))
    if status != 200:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
