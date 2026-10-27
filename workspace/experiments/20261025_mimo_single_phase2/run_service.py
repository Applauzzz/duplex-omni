"""Run one owned GPU service, keeping immutable launch and exit artifacts."""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument(
        "--role",
        choices=["tts", "mimo", "tts-ui", "mimo-tts-ui", "mimo-realtime-ui", "svad-ui"],
        required=True,
    )
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--ui-host", default="127.0.0.1")
    args = parser.parse_args()
    is_ui = args.role in ("tts-ui", "mimo-tts-ui", "mimo-realtime-ui", "svad-ui")
    if not is_ui and args.ui_host != "127.0.0.1":
        parser.error("--ui-host applies only to UI roles; model APIs stay loopback.")
    run = args.run.resolve()
    root = Path(__file__).resolve().parents[3]
    host = args.ui_host if is_ui else "127.0.0.1"
    with socket.socket() as probe:
        probe.bind((host, args.port))
    if is_ui:
        script = Path(__file__).with_name("preview_server.py")
        if args.role == "mimo-tts-ui":
            script = Path(__file__).parents[1] / "20261025_mimo_tts_integration/server.py"
        elif args.role == "mimo-realtime-ui":
            script = Path(__file__).parents[1] / "20261025_mimo_tts_integration/realtime_server.py"
        elif args.role == "svad-ui":
            script = Path(__file__).parents[1] / "20261025_mimo_tts_integration/svad_debug_server.py"
        command = [
            sys.executable, "-B", str(script),
            "--host", host, "--port", str(args.port),
        ]
    elif args.role == "tts":
        command = [
            sys.executable, "-B", "-m", "vllm_omni.entrypoints.cli.main", "serve",
            "/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            "--omni", "--deploy-config", str(Path(__file__).with_name("qwen3_tts_h20.yaml")),
            "--served-model-name", "qwen3-tts-customvoice",
            "--init-timeout", "1800", "--stage-init-timeout", "1800",
            "--trust-remote-code", "--host", "127.0.0.1", "--port", str(args.port),
        ]
    else:
        command = [
            sys.executable, "-B", "-m", "vllm.entrypoints.cli.main", "serve",
            "/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/MiMo-V2.6-Flash-RL",
            "--served-model-name", "mimo-v2.6-flash", "--tensor-parallel-size", "4",
            "--enable-expert-parallel", "--trust-remote-code",
            "--gpu-memory-utilization", "0.90", "--max-model-len", "32768",
            "--reasoning-parser", "mimo", "--host", "127.0.0.1", "--port", str(args.port),
        ]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{run / 'runtime'}:{root / 'vllm-omni'}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["VLLM_WORKER_MULTIPROC_METHOD"] = "spawn"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["VLLM_NO_USAGE_STATS"] = "1"
    env.setdefault("OMP_NUM_THREADS", "4")
    env["VLLM_CACHE_ROOT"] = str(run / f"cache_{args.role}_{args.attempt}")
    stem = f"{args.role}_{args.attempt}"
    versions = {}
    for package in ("torch", "transformers", "vllm", "vllm-omni", "aiohttp", "numpy"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    with (run / f"{stem}.log").open("x") as log:
        child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        launch = {
            "utc": datetime.now(timezone.utc).isoformat(), "command": command,
            "python": sys.executable, "versions": versions, "pid": child.pid,
            "pgid": child.pid, "supervisor_pid": os.getpid(),
            "env": {key: env[key] for key in ("PYTHONPATH", "CUDA_VISIBLE_DEVICES",
                    "VLLM_WORKER_MULTIPROC_METHOD", "VLLM_CACHE_ROOT",
                    "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "OMP_NUM_THREADS")},
            "gpu_inventory": subprocess.check_output([
                "nvidia-smi", "--query-gpu=index,uuid,name,memory.used,memory.total",
                "--format=csv,noheader"], text=True),
        }
        with (run / f"{stem}_launch.json").open("x") as output:
            json.dump(launch, output, indent=2)
        print(json.dumps({"pid": child.pid, "log": str(run / f"{stem}.log")}), flush=True)
        def stop(signum, _frame):
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        started = time.monotonic()
        code = child.wait()
        with (run / f"{stem}_exit.json").open("x") as output:
            json.dump({"code": code, "elapsed_s": time.monotonic() - started,
                       "utc": datetime.now(timezone.utc).isoformat()}, output, indent=2)
        print(f"Service {stem} exited: {code}", flush=True)
        sys.exit(code)


if __name__ == "__main__":
    main()
