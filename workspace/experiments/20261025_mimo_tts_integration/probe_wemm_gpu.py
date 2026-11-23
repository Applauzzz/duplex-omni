"""Isolated WeMM serving acceptance; always stop the process started here."""

import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import wave

import aiohttp
import numpy as np
import soundfile as sf


MODEL = "/mnt/zehaoliu/user_whynotzhliu/modelbase/Omni/WeMM-Video-35BA3B"


async def verify(run, port, process, timeout):
    url = f"http://127.0.0.1:{port}"
    async with aiohttp.ClientSession(
        trust_env=False, timeout=aiohttp.ClientTimeout(total=180)
    ) as session:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Server exited {process.returncode}; see model.log")
            try:
                async with session.get(url + "/health") as response:
                    if response.status == 200:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(5)
        else:
            raise TimeoutError("WeMM readiness deadline exceeded")

        audio_path = Path(
            "/mnt/geminihzceph/user_whynotzhliu/Omni/duplex_proxy_tt/my_question.wav"
        )
        samples, rate = sf.read(audio_path, dtype="float32")
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        samples = samples[:rate * 3]
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(2)
            writer.setframerate(rate)
            writer.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
        part = {
            "type": "input_audio",
            "input_audio": {
                "format": "wav",
                "data": base64.b64encode(buffer.getvalue()).decode(),
            },
        }
        requests = {
            "text": [{"role": "user", "content": "请用中文回答，一加一等于多少？"}],
            "audio": [{"role": "user", "content": [part]}],
        }
        summary = {}
        for label, messages in requests.items():
            payload = {
                "model": "wemm-port", "messages": messages,
                "max_tokens": 128, "temperature": 0, "stream": True,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            started = time.monotonic()
            chunks = []
            received = []
            async with session.post(url + "/v1/chat/completions", json=payload) as response:
                async for chunk in response.content.iter_any():
                    chunks.append(chunk)
                    received.append(time.monotonic() - started)
                raw = b"".join(chunks)
                (run / f"{label}.sse").write_bytes(raw)
                if response.status != 200:
                    raise RuntimeError(f"{label} HTTP{response.status}: {raw[:1000]!r}")
            deltas = []
            for line in raw.decode().splitlines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    value = json.loads(line[6:])
                    deltas.append(value["choices"][0]["delta"].get("content") or "")
            text = "".join(deltas)
            assert text and b"[DONE]" in raw, label
            summary[label] = {
                "text": text, "content_deltas": sum(bool(value) for value in deltas),
                "transport_chunks": len(chunks), "receive_seconds": received,
                "elapsed_seconds": time.monotonic() - started,
            }
            (run / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2)
            )
        payload = {
            "model": "wemm-port",
            "messages": [
                {"role": "system", "content": "判断用户语音是否有有效语义，只输出有或无。"},
                {"role": "user", "content": [part]},
            ],
            "max_tokens": 1, "temperature": 0,
            "allowed_token_ids": [95762, 95979],
            "logprob_token_ids": [95762, 95979],
            "logprobs": True, "top_logprobs": 2,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        async with session.post(url + "/v1/chat/completions", json=payload) as response:
            body = await response.json()
            (run / "decision.json").write_text(
                json.dumps(body, ensure_ascii=False, indent=2)
            )
            assert response.status == 200, body
        assert body["choices"][0]["message"]["content"] in ("有", "无"), body
        assert body["choices"][0]["logprobs"]["content"], body
        summary["decision"] = body["choices"][0]
        (run / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8094)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    with socket.socket() as check:
        check.bind(("127.0.0.1", args.port))
    run = Path(tempfile.mkdtemp(
        prefix=time.strftime("%Y%m%dT%H%M%SZ_wemm_port_"),
        dir=Path(__file__).resolve().parents[2] / "logs",
    ))
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="4,5", VLLM_PLUGINS="",
               HF_MODULES_CACHE=str(run / "hf_modules"), OMP_NUM_THREADS="4")
    command = [
        sys.executable, "-B", "-m", "vllm.entrypoints.cli.main", "serve", MODEL,
        "--served-model-name", "wemm-port", "--trust-remote-code",
        "--dtype", "bfloat16", "--host", "127.0.0.1", "--port", str(args.port),
        "--tensor-parallel-size", "2", "--max-model-len", "2048",
        "--gpu-memory-utilization", "0.65", "--max-num-seqs", "1",
        "--enforce-eager", "--no-enable-prefix-caching",
        "--mamba-ssm-cache-dtype", "float32",
        "--limit-mm-per-prompt", '{"audio":2,"image":0,"video":0}',
    ]
    (run / "launch.json").write_text(json.dumps({
        "command": command, "python": sys.executable,
        "pythonpath": env.get("PYTHONPATH"), "gpus": "4,5",
        "source": "local vllm-src with WeMM port; no application backbone rollout",
    }, indent=2))
    print(f"RUN={run}", flush=True)
    with (run / "model.log").open("xb") as log:
        process = subprocess.Popen(command, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            asyncio.run(verify(run, args.port, process, args.timeout))
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=30)
            (run / "exit.json").write_text(json.dumps({"returncode": process.returncode}))


if __name__ == "__main__":
    main()
