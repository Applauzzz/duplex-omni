"""Archive source/config digests and summarize existing GPU artifacts, no model loads."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from gpu_smoke import SAMPLES, save_json


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main(args):
    root = Path(__file__).resolve().parents[3]
    run = args.run.resolve()
    sources = [
        run / "runtime/vllm/__init__.py",
        run / "runtime/vllm/model_executor/models/mimo_v2.py",
        run / "runtime/vllm/model_executor/models/mimo_v2_omni.py",
        root / "vllm-omni/vllm_omni/entrypoints/async_omni.py",
        root / "vllm-omni/vllm_omni/model_executor/models/qwen3_tts/pipeline.py",
    ]
    files = list(Path(__file__).parent.glob("*.py")) + [
        Path(__file__).with_name("qwen3_tts_h20.yaml"),
        root / "vllm-omni/vllm_omni/deploy/qwen3_tts.yaml",
    ]
    models = [
        Path("/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/MiMo-V2.6-Flash-RL"),
        Path("/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
    ]
    for model in models:
        files.extend(path for path in sorted(model.glob("*.json")) if path.is_file())
    report = {
        "utc": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
        "run": str(run),
        "source_files": [{"path": str(path), "resolved": str(path.resolve()),
                          "sha256": digest(path)} for path in sources],
        "config_and_scripts": {str(path): digest(path) for path in files},
        "gpu_final": subprocess.check_output([
            "nvidia-smi", "--query-gpu=index,uuid,name,memory.used,utilization.gpu",
            "--format=csv,noheader"], text=True),
        "git_status": subprocess.check_output(["git", "status", "--short"], cwd=root, text=True),
        "gates": {"runtime_gpu": "pass", "tts_pcm_stream": "pass",
                  "mimo_audio_sse": "pass", "mixed_proper_noun_content": "unresolved",
                  "orchestrator_abort_ack": "pass",
                  "fresh_stage_idle_snapshot": "unresolved", "phase2": "in_progress"},
        "samples": {},
        "launches": {name: json.loads((run / name).read_text())
                     for name in ("mimo_02_launch.json", "tts_03_launch.json")},
    }
    for name, _text, _language in SAMPLES:
        cold = json.loads((run / "smoke_20261025T101119Z_all" / f"{name}_result.json").read_text())
        warm = json.loads((run / "smoke_20261025T110131Z_tts" / f"{name}_result.json").read_text())
        report["samples"][name] = {
            "cold": cold, "warm": warm,
            "identical_pcm": cold["sha256"] == warm["sha256"],
            "independent_asr": json.loads((run / "whisper_20261025T105722Z" / f"{name}.json").read_text()),
            "mimo_asr": json.loads((run / "smoke_20261025T110115Z_mimo-audio" / f"{name}_mimo_asr.json").read_text()),
        }
    output = run / f"evidence_archive_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    save_json(output, report)
    print(f"ARCHIVE={output}", flush=True)
    print(json.dumps(report["gates"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    main(parser.parse_args())
