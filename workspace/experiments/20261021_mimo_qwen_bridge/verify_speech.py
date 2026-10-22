"""Transcribe produced WAVs with MiMo; keep reference text for manual review."""
import argparse
import asyncio
import base64
import json
from pathlib import Path

import aiohttp

root = Path(__file__).resolve().parents[3]
outputs = root / "workspace/experiments/20261021_mimo_qwen_bridge"


async def main(names):
    results = []
    async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=180)) as client:
        for name in names:
            wav = outputs / f"turn_{name}.wav"
            reference = json.loads((outputs / f"turn_{name}.json").read_text())["result"]["text"]
            body = {"model": "mimo-v2.6-flash", "messages": [
                {"role": "system", "content": "你是语音转写工具，只转写音频内容，不回答，不补充，保持原语言。"},
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav.read_bytes()).decode(), "format": "wav"}},
                    {"type": "text", "text": "Transcribe exactly the speech in this recording. Do not answer it."},
                ]},
            ], "max_tokens": 300, "temperature": 0.0, "chat_template_kwargs": {"enable_thinking": False}}
            async with client.post("http://127.0.0.1:8090/v1/chat/completions", json=body) as response:
                if response.status != 200:
                    raise RuntimeError((await response.text())[:500])
                data = await response.json()
            result = {"sample": name, "reference": reference, "asr": data["choices"][0]["message"]["content"]}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    (outputs / "speech_transcription.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="+", default=["audio1", "english", "numbers", "mixed"])
    asyncio.run(main(parser.parse_args().names))
