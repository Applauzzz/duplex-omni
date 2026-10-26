"""Check transport/cancellation evidence without equating it with listening."""

import argparse
import json
from pathlib import Path
import re


def check(args):
    results = {}
    for path in sorted(args.smoke.glob("*_result.json")):
        result = json.loads(path.read_text())
        if "cancel_mode" in result and result["cancel_mode"] is None:
            results[path.stem] = {
                "status_200": result.get("status") == 200,
                "complete": result.get("transport_complete") is True,
                "pcm16": result.get("bytes", 0) > 0 and result.get("bytes", 0) % 2 == 0,
                "audible_energy": result.get("rms", 0) > 1e-5,
                "multiple_chunks": len(result.get("chunks", [])) > 1,
                "audio_before_end": result.get("ttfa_s", 1e9) < result.get("total_s", 0),
                "content": "pending independent ASR or listening",
            }
    log = args.log.read_text()
    orch_ids = re.findall(r"\[Orchestrator\] Aborted request\(s\) \['([^']+)'\]", log)
    async_ids = re.findall(r"\[AsyncOmni\] Request (\S+) aborted\.", log)
    cancelled_ids = re.findall(r"\[SpeechE2E\] request_id=(\S+) stream=true status=cancelled", log)
    cancellation = {"orchestrator_aborted": orch_ids, "async_omni_aborted": async_ids,
                    "speech_cancelled": cancelled_ids, "metrics": {}}
    for path in sorted(args.smoke.glob("*metrics*.txt")):
        lines = [line for line in path.read_text().splitlines()
                 if not line.startswith("#") and
                 ("num_requests_running" in line or "num_requests_waiting" in line or
                  "stage_waiting_requests" in line)]
        cancellation["metrics"][path.name] = lines
    cancellation["matched_abort_ids"] = sorted(set(orch_ids) & set(async_ids))
    results["cancellation_evidence"] = cancellation
    results["acceptance"] = "Evidence only. Confirm per-request timing and stage-id metrics; content is not auto-passed."
    with args.output.open("x") as output:
        json.dump(results, output, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    check(parser.parse_args())
