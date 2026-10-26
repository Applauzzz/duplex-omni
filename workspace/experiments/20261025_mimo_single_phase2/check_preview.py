"""Check the live preview proxy using GPU synthesis and exclusive artifacts."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import wave

from aiohttp import ClientSession, ClientTimeout
import numpy as np


async def main(run, base_url="http://127.0.0.1:7866"):
    base_url = base_url.rstrip("/")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = run / f"preview_check_{stamp}"
    output.mkdir(exist_ok=False)
    results = {"utc": stamp, "base_url": base_url, "tests": [], "status": "running"}
    try:
        async with ClientSession(trust_env=False, timeout=ClientTimeout(total=180)) as client:
            async with client.get(f"{base_url}/") as response:
                html = await response.text()
                assert response.status == 200
                assert "Qwen3-TTS" in html and 'id="stop"' in html
                results["tests"].append({"case": "page", "status": response.status})
            async with client.get(f"{base_url}/api/status") as response:
                health = await response.json()
                assert response.status == 200 and health["tts"] is True, health
                results["health"] = health
            for label, body in (
                ("empty", {"input": ""}),
                ("non_object", []),
                ("too_long", {"input": "a" * 1601}),
            ):
                async with client.post(
                    f"{base_url}/api/speech", json=body
                ) as response:
                    await response.read()
                    assert response.status == 400, (label, response.status)
                    results["tests"].append({"case": label, "status": response.status})
            async with client.post(
                f"{base_url}/api/speech",
                data="{invalid", headers={"Content-Type": "application/json"},
            ) as response:
                await response.read()
                assert response.status == 400
                results["tests"].append({"case": "invalid_json", "status": response.status})
            started = time.monotonic()
            chunks = []
            first_byte = None
            text = "\u4f60\u597d\uff0c\u6b22\u8fce\u4f53\u9a8c\u8bed\u97f3\u5408\u6210\u3002"
            async with client.post(
                f"{base_url}/api/speech",
                json={"input": text, "voice": "vivian", "language": "Chinese"},
            ) as response:
                assert response.status == 200, await response.text() if response.status != 200 else ""
                assert response.headers["Content-Type"].startswith("audio/pcm")
                async for chunk in response.content.iter_any():
                    if first_byte is None:
                        first_byte = time.monotonic() - started
                    chunks.append(chunk)
            elapsed = time.monotonic() - started
            pcm = b"".join(chunks)
            with (output / "preview.pcm").open("xb") as file:
                file.write(pcm)
            assert pcm and len(pcm) % 2 == 0
            samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
            rms = float(np.sqrt(np.mean(samples * samples)))
            assert rms > .002, rms
            with (output / "preview.wav").open("xb") as file:
                with wave.open(file, "wb") as audio:
                    audio.setnchannels(1)
                    audio.setsampwidth(2)
                    audio.setframerate(24000)
                    audio.writeframes(pcm)
            results["tests"].append({
                "case": "real_gpu_pcm_proxy", "status": 200, "text": text,
                "chunks": len(chunks), "bytes": len(pcm), "rms": rms,
                "duration_s": len(samples) / 24000,
                "first_byte_s": first_byte, "elapsed_s": elapsed,
                "sha256": hashlib.sha256(pcm).hexdigest(),
            })
            results["status"] = "pass"
    except BaseException as error:
        results["status"] = "fail"
        results["error"] = repr(error)
        raise
    finally:
        with (output / "results.json").open("x") as file:
            json.dump(results, file, indent=2, ensure_ascii=True)
        print(json.dumps({"output": str(output), **results}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:7866")
    args = parser.parse_args()
    asyncio.run(main(args.run.resolve(), args.base_url))
