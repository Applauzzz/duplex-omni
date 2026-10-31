"""Generate one no-clobber WAV fixture through the configured streaming TTS API."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import wave

from aiohttp import ClientSession, ClientTimeout

from streaming_tts import WeChatStreamingTTSProvider


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tts-url", default="http://29.213.195.135:8100")
    parser.add_argument("--text", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--reg-id", default="bench_spk")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_root / f"tts_fixture_{stamp}_{uuid.uuid4().hex[:8]}"
    output.mkdir(parents=True, exist_ok=False)
    timeout = ClientTimeout(total=240, connect=10, sock_read=180)
    async with ClientSession(timeout=timeout, trust_env=False) as client:
        session = WeChatStreamingTTSProvider(client, args.tts_url).create_stream(
            reg_id=args.reg_id,
            speed=1.0,
            target_rms=-25,
            context={"request_id": f"fixture-{uuid.uuid4().hex}"},
        )
        await session.submit_text(args.text, final=True)
        chunks = [chunk async for chunk in session.stream_pcm()]
    rates = {chunk.sample_rate_hz for chunk in chunks}
    if len(rates) != 1:
        raise RuntimeError(f"TTS fixture sample rates differ: {sorted(rates)}")
    sample_rate = rates.pop()
    pcm = b"".join(chunk.pcm for chunk in chunks)
    wav_path = output / "input.wav"
    with wave.open(str(wav_path), "wb") as recording:
        recording.setparams((1, 2, sample_rate, 0, "NONE", ""))
        recording.writeframes(pcm)
    summary = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "tts_url": args.tts_url,
        "reg_id": args.reg_id,
        "text": args.text,
        "wav": str(wav_path),
        "sample_rate_hz": sample_rate,
        "samples": len(pcm) // 2,
        "chunks": len(chunks),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
