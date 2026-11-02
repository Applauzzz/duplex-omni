"""Create a new private selected-tool policy; never modify existing credentials."""

import argparse
import json
from pathlib import Path

from mac_m2 import FUNCTIONS, EVENT_SCOPE
from mac_tools import valid_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--context-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not all(valid_id(value) and not value.startswith("CHANGE_ME") for value in
               (args.device_id, args.workspace_id, args.context_id)):
        parser.error("IDs must match the confirmed Mac mapping")
    value = {"version": 1, "devices": [{
        "device_id": args.device_id, "workspace_id": args.workspace_id,
        "context_id": args.context_id, "scope": sorted([*FUNCTIONS, EVENT_SCOPE]),
    }]}
    args.output.touch(mode=0o600, exist_ok=False)
    args.output.write_text(json.dumps(value, indent=2) + "\n")
    print("Created private M2 policy; device credentials unchanged")


if __name__ == "__main__":
    main()
