"""Create a no-clobber current-source runtime with existing native binaries."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import uuid


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def merge_generated(current, donor, target, generated):
    target.mkdir()
    names = set()
    if current.is_dir():
        names.update(item.name for item in current.iterdir())
    if donor.is_dir():
        names.update(item.name for item in donor.iterdir())
    for name in sorted(names - {"__pycache__"}):
        src, extra, dest = current / name, donor / name, target / name
        if src.is_dir() and extra.is_dir():
            merge_generated(src, extra, dest, generated)
        else:
            selected = src if src.exists() else extra
            dest.symlink_to(selected, target_is_directory=selected.is_dir())
            if selected == extra:
                generated.append(str(extra))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary-source", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    current = root / "vllm-src"
    binary = args.binary_source.resolve()
    changed = git(current, "diff", "--name-only", git(binary, "rev-parse", "HEAD"), "HEAD").splitlines()
    allowed = {"pyproject.toml", "vllm/model_executor/models/mimo_v2.py",
               "vllm/model_executor/models/mimo_v2_mtp.py"}
    if any(not (name in allowed or name.startswith("requirements/")) for name in changed):
        raise RuntimeError(f"Binary compatibility requires review: {changed}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run = root / "workspace/logs" / f"{stamp}_mimo_single_phase2_{uuid.uuid4().hex[:8]}"
    run.mkdir(parents=True, exist_ok=False)
    overlay = run / "runtime/vllm"
    overlay.mkdir(parents=True)
    special = {"vllm_flash_attn", "third_party"}
    for item in (current / "vllm").iterdir():
        if item.name not in special and item.name != "__pycache__":
            (overlay / item.name).symlink_to(item, target_is_directory=item.is_dir())
    generated = []
    for name in special:
        merge_generated(current / "vllm" / name, binary / "vllm" / name,
                        overlay / name, generated)
    binaries = []
    for src in sorted((binary / "vllm").rglob("*.so")):
        relative = src.relative_to(binary / "vllm")
        dest = overlay / relative
        if dest.exists() and dest.resolve() != src.resolve():
            raise FileExistsError(dest)
        if not dest.exists():
            dest.symlink_to(src)
        with src.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        binaries.append({"path": str(src), "relative": str(relative), "sha256": digest})
    manifest = {
        "created_utc": stamp, "run": str(run), "parent_head": git(root, "rev-parse", "HEAD"),
        "vllm_head": git(current, "rev-parse", "HEAD"),
        "omni_head": git(root / "vllm-omni", "rev-parse", "HEAD"),
        "binary_source": str(binary), "binary_head": git(binary, "rev-parse", "HEAD"),
        "source_diff": changed, "binaries": binaries, "generated_dependencies": generated,
        "pythonpath": [str(run / "runtime"), str(root / "vllm-omni")],
    }
    with (run / "runtime_manifest.json").open("x") as output:
        json.dump(manifest, output, indent=2)
    print(run, flush=True)


if __name__ == "__main__":
    main()
