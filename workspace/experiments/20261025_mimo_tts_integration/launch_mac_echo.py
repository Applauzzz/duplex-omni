"""Launch owned echo app services with exclusive logs and private credentials."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import uuid


def write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--reuse-private-dir", type=Path,
                        help="Preserve existing device identity and audit during reload")
    parser.add_argument("--m2-policy-file", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    runtime = args.runtime.resolve()
    if not (runtime / "vllm/__init__.py").exists():
        parser.error("runtime must contain the verified vllm overlay")
    for port in (8080, 8081):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = root / "workspace/logs" / f"{stamp}_mac_echo_{uuid.uuid4().hex[:8]}"
    run.mkdir(mode=0o700)
    if args.reuse_private_dir:
        private = args.reuse_private_dir.resolve()
        for name in ("device-auth.json", "mac-client.private.json"):
            path = private / name
            if not path.is_file() or path.stat().st_mode & 0o077:
                parser.error("reuse-private-dir requires existing private configuration files")
    else:
        private = run / "private"
        create_identity(private)
    serve(root, runtime, run, private, stamp, args.m2_policy_file)


def create_identity(private):
    private.mkdir(mode=0o700)
    token = secrets.token_urlsafe(48)
    device = "duplex-mimo-mac-m5"
    write_private(private / "device-auth.json", {
        "version": 1, "devices": [{
            "device_id": device, "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            "scope": ["demo_echo"],
        }],
    })
    write_private(private / "mac-client.private.json", {
        "protocol": "duplex-mac-tools/v1", "mode": "h20", "device_id": device,
        "http_base_url": "http://127.0.0.1:8080",
        "pairing_url": "http://127.0.0.1:8080/api/tools/pairing",
        "bridge_url": "ws://127.0.0.1:8080/api/tools/bridge",
        "token": token, "scope": ["demo_echo"],
    })


def serve(root, runtime, run, private, stamp, m2_policy_file=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{runtime}:{root / 'vllm-omni'}"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    server = Path(__file__).with_name("svad_debug_server.py")
    children = []
    logs = []
    stopping = False

    def stop(_signum=None, _frame=None):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print(f"RUN={run}", flush=True)
    try:
        for role, port, extra in [
            ("agent", 8081, ["--agentic", "--mac-auth-file",
                             str(private / "device-auth.json"), "--mac-audit-file",
                             str(private / "echo-audit.sqlite")]),
            ("entry", 8080, []),
        ]:
            if role == "agent" and m2_policy_file:
                extra.extend(["--mac-m2-policy-file", str(m2_policy_file.resolve())])
            command = [sys.executable, "-B", str(server), "--host", "127.0.0.1",
                       "--port", str(port), *extra]
            log = (run / f"{role}.log").open("x")
            logs.append(log)
            child = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            children.append(child)
            with (run / f"{role}_launch.json").open("x") as stream:
                json.dump({
                    "utc": stamp, "pid": child.pid, "supervisor": os.getpid(),
                    "command": command, "python": sys.executable,
                    "pythonpath": env["PYTHONPATH"],
                    "parent_head": subprocess.check_output(
                        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
                }, stream, indent=2)
            print(f"{role}: pid={child.pid} port={port}", flush=True)
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(1)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=30)
        with (run / "exit.json").open("x") as stream:
            json.dump({"codes": [child.returncode for child in children]}, stream)
        for log in logs:
            log.close()


if __name__ == "__main__":
    main()
