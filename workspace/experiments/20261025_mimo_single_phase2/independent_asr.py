"""Offline GPU Whisper transcription using local weights and bundled tokenizer."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf
import torch
from transformers import WhisperFeatureExtractor, WhisperForConditionalGeneration
from whisper.tokenizer import get_tokenizer

from gpu_smoke import SAMPLES, save_json


def main(args):
    out = args.run / f"whisper_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    out.mkdir(exist_ok=False)
    if not torch.cuda.is_available():
        raise RuntimeError("Independent ASR requires CUDA")
    print(f"ARTIFACTS={out}", flush=True)
    torch.set_num_threads(4)
    extractor = WhisperFeatureExtractor.from_pretrained(args.model, local_files_only=True)
    model = WhisperForConditionalGeneration.from_pretrained(
        args.model, local_files_only=True, dtype=torch.float16).to("cuda").eval()
    tokenizer = get_tokenizer(multilingual=True, num_languages=100,
                              language="en", task="transcribe")
    config = model.generation_config
    config.is_multilingual = True
    config.lang_to_id = {f"<|{code}|>": token for code, token in
                         zip(tokenizer.all_language_codes, tokenizer.all_language_tokens)}
    config.task_to_id = {"transcribe": tokenizer.transcribe, "translate": tokenizer.translate}
    config.no_timestamps_token_id = tokenizer.no_timestamps
    config.decoder_start_token_id = tokenizer.sot
    config.eos_token_id = tokenizer.eot
    config.pad_token_id = tokenizer.eot
    config.begin_suppress_tokens = [tokenizer.encode(" ")[0], tokenizer.eot]
    config.suppress_tokens = list(tokenizer.non_speech_tokens)
    manifest = {"model": str(args.model), "device": torch.cuda.get_device_name(0),
                "torch": torch.__version__, "dtype": "float16",
                "tokenizer": "openai-whisper bundled multilingual, 100 languages",
                "role": "independent validation only, not serving architecture"}
    save_json(out / "manifest.json", manifest)
    save_json(out / "runtime_generation_config.json", config.to_dict())
    for name, reference, language in SAMPLES:
        wav = args.samples / f"{name}.wav"
        deadline = time.monotonic() + args.wait
        while not wav.exists() and time.monotonic() < deadline:
            time.sleep(5)
        if not wav.exists():
            raise TimeoutError(f"No generated sample: {wav}")
        audio, rate = sf.read(wav, dtype="float32")
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if rate != 16000:
            factor = np.gcd(rate, 16000)
            audio = resample_poly(audio, 16000 // factor, rate // factor)
        if len(audio) > 30 * 16000:
            raise ValueError(f"Short-form independent ASR sample exceeds 30s: {name}")
        # Mixed text uses the Chinese task prefix, without reference-text prompting.
        lang = "en" if language == "English" else "zh"
        tokenizer = get_tokenizer(multilingual=True, num_languages=100,
                                  language=lang, task="transcribe")
        features = extractor(audio, sampling_rate=16000, return_tensors="pt")
        started = time.monotonic()
        with torch.inference_mode():
            ids = model.generate(
                features.input_features.to(device="cuda", dtype=torch.float16),
                max_new_tokens=400, do_sample=False,
                num_beams=1, return_timestamps=False, language=lang, task="transcribe")
        tokens = ids[0].tolist()
        transcript = tokenizer.decode([token for token in tokens if token < tokenizer.eot]).strip()
        result = {"sample": name, "reference": reference, "asr": transcript,
                  "tokens": tokens, "total_s": time.monotonic() - started,
                  "prompted_with_reference": False}
        save_json(out / f"{name}.json", result)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--wait", type=float, default=1800)
    main(parser.parse_args())
