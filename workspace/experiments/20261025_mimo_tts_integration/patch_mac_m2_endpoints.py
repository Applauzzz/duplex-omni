"""Run on Mac inside the user's copied source tree, not the sibling reference."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    resources = args.source / "Sources/HostRuntime"
    patches = {
        "H20Configuration.swift": [
            ('http://29.213.201.220:8080', 'http://127.0.0.1:8080'),
            ('ws://29.213.201.220:8080', 'ws://127.0.0.1:8080'),
        ],
        "M2Protocol.swift": [
            ('ws://29.213.201.220:8080/api/tools/m2/bridge',
             'ws://127.0.0.1:8080/api/tools/m2/bridge'),
        ],
    }
    for filename, replacements in patches.items():
        path = resources / filename
        text = path.read_text()
        updated = text
        for old, new in replacements:
            if old not in updated and new not in updated:
                raise RuntimeError("Unexpected source version: " + filename)
            updated = updated.replace(old, new)
        if text == updated:
            print(filename + ": already configured")
            continue
        backup = path.with_suffix(path.suffix + ".pre-duplex-m2")
        with backup.open("x") as stream:
            stream.write(text)
        path.write_text(updated)
        print(filename + ": loopback endpoints configured; original preserved")


if __name__ == "__main__":
    main()
