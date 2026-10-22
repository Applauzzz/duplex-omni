"""Exercise real MiMo→Qwen streaming, multi-turn text/audio and cancellation."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import time
from urllib.parse import quote
import wave

import numpy as np
import soundfile as sf
import websockets

root = Path(__file__).resolve().parents[3]
model = str(root.parent / "modelbase/Omni/Qwen3-Omni-30B-A3B-Instruct")
output_dir = root / "workspace/experiments/20261021_mimo_qwen_bridge"


def audio_clip(path):
    audio, rate = sf.read(path, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != 16000:
        audio = np.interp(np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate)), np.arange(len(audio)), audio)
    return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()


async def send(ws, **event):
    await ws.send(json.dumps(event, ensure_ascii=False))


async def recv(ws, timeout=120):
    event = json.loads(await asyncio.wait_for(ws.recv(), timeout))
    if event.get("type") == "error":
        raise RuntimeError(event)
    return event


async def until(ws, kind, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        event = await recv(ws, deadline - time.monotonic())
        if event.get("type") == kind:
            return event
    raise TimeoutError(kind)


async def turn(ws, index, *, text=None, audio=None, interrupt=False):
    was_interrupted = interrupt
    if text is not None:
        await send(ws, type="conversation.item.create", item={"type": "message", "role": "user",
                   "content": [{"type": "input_text", "text": text}]})
        await until(ws, "conversation.item.created")
        await send(ws, type="response.create")
    else:
        for offset in range(0, len(audio), 6400):
            await send(ws, type="input_audio_buffer.append", audio=base64.b64encode(audio[offset:offset + 6400]).decode(),
                       format="pcm16", sample_rate_hz=16000)
        await send(ws, type="input_audio_buffer.commit", final=True, create_response=True)
    t0 = time.monotonic()
    events, pieces, pcm = [], [], bytearray()
    rid = None
    first_audio = None
    transcript_done = None
    for _ in range(10000):
        event = await recv(ws)
        dt = time.monotonic() - t0
        events.append({"time_s": dt, "event": event})
        kind = event.get("type")
        if kind == "response.created":
            rid = event.get("response_id") or event.get("response", {}).get("id")
        if kind in {"response.output_audio_transcript.delta", "response.output_text.delta"}:
            pieces.append(event.get("delta", ""))
        if kind in {"response.output_audio_transcript.done", "response.output_text.done"}:
            transcript_done = dt
        if kind == "response.output_audio.delta":
            first_audio = first_audio if first_audio is not None else dt
            pcm.extend(base64.b64decode(event.get("delta", "")))
            if interrupt:
                await send(ws, type="response.cancel")
                await send(ws, type="playback.ack", response_id=rid, item_id=f"item_{rid}", played_ms=0, committed_ms=0)
                interrupt = False
        if kind == "response.done":
            break
    else:
        raise RuntimeError("No response completion")
    event.get("response", {}).pop("metadata", None)
    assert event.get("response", {}).get("status") == ("cancelled" if was_interrupted else "completed"), event
    if was_interrupted:
        assert first_audio is not None, "Barge-in test never received audio"
    result = {"index": index, "text": "".join(pieces), "audio_bytes": len(pcm), "first_audio_s": first_audio,
              "transcript_done_s": transcript_done,
              "audio_before_text_done": first_audio is not None and transcript_done is not None and first_audio < transcript_done,
              "total_s": time.monotonic() - t0, "response": event}
    (output_dir / f"turn_{index}.json").write_text(json.dumps({"result": result, "events": events}, ensure_ascii=False, indent=2))
    if pcm:
        with wave.open(str(output_dir / f"turn_{index}.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)
    if rid and not was_interrupted:
        played_ms = len(pcm) / 48
        await send(ws, type="playback.ack", response_id=rid, item_id=f"item_{rid}", played_ms=played_ms, committed_ms=played_ms)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


async def main(args):
    model = args.model
    url = f"ws://127.0.0.1:{args.port}/v1/realtime?duplex=1&model=" + quote(model, safe="")
    async with websockets.connect(url, max_size=64 * 1024 * 1024, proxy=None) as ws:
        await send(ws, type="session.update", session={"model": model, "modalities": ["text", "audio"],
            "instructions": ("自然口语回答，不要Markdown，不限制回答长度。" if args.mode in {"samples", "streaming"} else
                             "你是语音助手，直接回应用户，不要转写。自然口语，不要Markdown。回答一到三句话。"),
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 16000}, "turn_detection": None},
                      "output": {"format": {"type": "audio/pcm", "rate": 24000}}}})
        await until(ws, "session.updated", 30)
        if args.mode == "disconnect":
            await send(ws, type="conversation.item.create", item={"type": "message", "role": "user",
                       "content": [{"type": "input_text", "text": "请长篇介绍室内园艺。"}]})
            await until(ws, "conversation.item.created")
            await send(ws, type="response.create")
            await until(ws, "response.output_audio.delta")
            await ws.close()
            print("Disconnected active audio stream", flush=True)
            return
        elif args.mode == "reset":
            result = await turn(ws, "reset", text="我叫什么名字？如果我没有告诉你，就说不知道。")
            assert "小林" not in result["text"], "A new session retained the previous session history"
        elif args.mode == "textonly":
            await send(ws, type="session.update", session={"modalities": ["text"]})
            await until(ws, "session.updated", 30)
            await turn(ws, "textonly", text="请只说：文字模式正常。")
        elif args.mode == "text":
            await turn(ws, "text1", text="我的名字是小林。请用一句话向我问好。")
            await turn(ws, "text2", text="我刚才告诉你我叫什么名字？请简短回答。")
        elif args.mode == "samples":
            await turn(ws, "english", text="Please say exactly: Hello, have a nice day.")
            await turn(ws, "numbers", text="请只说：今天是十月二十一日，数字是四十二。")
            await turn(ws, "mixed", text="请只说：你好，Hello world。")
            await turn(ws, "streaming", text="请用八个较长的自然段介绍室内园艺养护，不要列表，至少八百字。")
        elif args.mode == "streaming":
            await turn(ws, "streaming", text="请用八个较长的自然段介绍室内园艺养护，不要列表，至少八百字。")
        else:
            clip = audio_clip(root / "vllm-omni/tests/assets/minicpmo_4_5/soft_interrupt_16k.wav")
            await turn(ws, "audio1", audio=clip)
            await turn(ws, "interrupt", text="请详细介绍雨天在室内可以做的几种活动。", interrupt=True)
            await turn(ws, "after_cancel", text="现在只说：我们继续聊。")
        await send(ws, type="session.close")
        try:
            await until(ws, "session.closed", 5)
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8092)
    parser.add_argument("--model", default=model)
    parser.add_argument("--mode", choices=["text", "audio", "samples", "textonly", "streaming", "reset", "disconnect"], default="text")
    asyncio.run(main(parser.parse_args()))
