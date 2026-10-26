"""Compare immutable failed MiMo input variants against the running GPU model."""

import argparse
import asyncio
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from aiohttp import ClientSession, ClientTimeout


async def main(args):
    messages = json.loads(args.prompt.read_text())
    output = args.run / (
        datetime.now(timezone.utc).strftime("recovery_probe_%Y%m%dT%H%M%SZ")
        + "_" + uuid.uuid4().hex[:8])
    output.mkdir(exist_ok=False)
    latest = copy.deepcopy(messages)
    latest[-1]["content"][-1]["text"] = (
        "This is the latest spoken user question, after interrupting the previous "
        "response. Answer this audio question now; earlier requests are history. "
        "Do not transcribe the audio or answer an earlier question.")
    merged = copy.deepcopy(messages[:-2])
    merged.append({"role": "user", "content": [
        {"type": "text", "text": messages[-2]["content"]},
        *copy.deepcopy(messages[-1]["content"]),
    ]})
    cases = {
        "current_audio_only": [messages[0], messages[-1]],
        "chronological": messages,
        "explicit_latest": latest,
        "merged_chronological": merged,
    }
    async with ClientSession(trust_env=False, timeout=ClientTimeout(total=90)) as client:
        for name, value in cases.items():
            payload = {
                "model": "mimo-v2.6-flash", "messages": value,
                "temperature": 0.0, "max_tokens": 128,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            async with client.post("http://127.0.0.1:8090/v1/chat/completions",
                                   json=payload) as response:
                result = await response.json()
                with (output / f"{name}.json").open("x") as file:
                    json.dump({"status": response.status, "request": payload,
                               "result": result}, file, ensure_ascii=True, indent=2)
                print(name, response.status,
                      result.get("choices", [{}])[0].get("message"), flush=True)
    print("Artifacts:", output, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
