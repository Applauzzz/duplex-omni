"""Generate the selected, public wire contracts from a delivered Mac package."""

import argparse
import json
from pathlib import Path


SELECTED = {
    "demo_echo", "timer_start", "timer_list", "timer_cancel",
    "weather_get", "place_search", "route_plan",
    "apple_reminder_create", "apple_reminder_list", "apple_reminder_update",
    "apple_reminder_delete", "contacts_search", "facetime_call", "facetime_call_contact",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("resources", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    catalog = json.loads((args.resources / "ContactsCatalog.json").read_text())
    catalog["tools"] = [tool for tool in catalog["tools"] if tool["name"] in SELECTED]
    for name, value in {
        "catalog.json": catalog,
        "bridge.json": json.loads((args.resources / "ContactsBridge.json").read_text()),
        "discovery.json": json.loads((args.resources / "ContactsDiscovery.json").read_text()),
        "event.json": json.loads((args.resources / "M2Event.json").read_text()),
    }.items():
        with (args.output / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2)
            stream.write("\n")


if __name__ == "__main__":
    main()
