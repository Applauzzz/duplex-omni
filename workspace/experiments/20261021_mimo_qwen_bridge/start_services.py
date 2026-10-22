"""Start explicitly assigned bridge services and await readiness."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

root = Path(__file__).resolve().parents[3]
logs = root / "workspace/logs/20261021_mimo_qwen_bridge"
parser = argparse.ArgumentParser()
parser.add_argument("--qwen-only", action="store_true")
parser.add_argument("--bin-dir", type=Path, default=os.environ.get("OMNI_BIN_DIR", root.parent / "my_envs/miniconda3/envs/omni/bin"))
parser.add_argument("--model-dir", type=Path, default=os.environ.get("OMNI_MODEL_DIR", root.parent / "modelbase/Omni"))
args = parser.parse_args()
bin_dir = args.bin_dir.resolve()
model_dir = args.model_dir.resolve()
logs.mkdir(parents=True, exist_ok=True)
processes = {}
handles = []
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def ready(port, path):
    try:
        with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError):
        return False

for port in ((8092, 26100) if args.qwen_only else (8090, 8092, 26100)):
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is already occupied; refusing duplicate services")

usage = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True)
requested_usage = usage.splitlines()[4:7] if args.qwen_only else usage.splitlines()[:7]
if any(int(value) > 1000 for value in requested_usage):
    raise RuntimeError("Requested GPU 0–6 is not idle")

commands = {
    "mimo": ("0,1,2,3", [str(bin_dir / "vllm"), "serve", str(model_dir / "MiMo-V2.6-Flash-RL"),
        "--served-model-name", "mimo-v2.6-flash", "--tensor-parallel-size", "4", "--enable-expert-parallel",
        "--trust-remote-code", "--gpu-memory-utilization", "0.90", "--max-model-len", "32768",
        "--reasoning-parser", "mimo", "--host", "127.0.0.1", "--port", "8090"]),
}
if args.qwen_only:
    commands.clear()
for stage in range(3):
    command = [str(bin_dir / "vllm"), "serve", str(model_dir / "Qwen3-Omni-30B-A3B-Instruct"), "--omni",
        "--stage-id", str(stage), "--omni-master-address", "127.0.0.1", "--omni-master-port", "26100",
        "--deploy-config", "workspace/configs/mimo_qwen_duplex.json", "--stage-init-timeout", "1800"]
    command += ["--port", "8092", "--init-timeout", "1800"] if stage == 0 else ["--headless"]
    commands[f"qwen{stage}"] = (str(stage + 4), command)

try:
    for name, (gpu, command) in commands.items():
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": gpu,
               "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
               "NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"}
        handle = (logs / f"{name}_serve.log").open("w")
        handles.append(handle)
        processes[name] = subprocess.Popen(command, cwd=root, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                           stdin=subprocess.DEVNULL, start_new_session=True)
    pid_file = logs / "service_pids.json"
    saved_pids = json.loads(pid_file.read_text()) if args.qwen_only and pid_file.exists() else {}
    saved_pids.update({name: process.pid for name, process in processes.items()})
    (logs / "service_pids.json").write_text(json.dumps(saved_pids, indent=2))
    deadline = time.monotonic() + 3000
    while time.monotonic() < deadline:
        for name, process in processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{name} exited with {process.returncode}; inspect {name}_serve.log")
        if ready(8090, "/health") and ready(8092, "/v1/models"):
            print("MiMo TP4 and Qwen three-stage bridge services READY", flush=True)
            break
        time.sleep(3)
    else:
        raise TimeoutError("Bridge services did not become ready")
except BaseException:
    for process in processes.values():
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
    raise
finally:
    for handle in handles:
        handle.close()
