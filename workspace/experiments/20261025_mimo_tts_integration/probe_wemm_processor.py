"""Read-only checkpoint/processor probe, no model load or service mutation."""

import argparse
import json

import numpy as np
import torch
from transformers import AutoConfig, AutoTokenizer

from vllm.model_executor.models.wemm_omni import (
    WeMMDummyInputsBuilder,
    WeMMMultiModalProcessor,
    WeMMProcessingInfo,
)
from vllm.multimodal.media.wemm import wemm_audio_item
from vllm.multimodal.processing.context import InputProcessingContext, TimingContext
from vllm.multimodal.processing.inputs import ProcessorInputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model")
    args = parser.parse_args()
    config = AutoConfig.from_pretrained(
        args.model, trust_remote_code=True, local_files_only=True
    )
    tokenizer = AutoTokenizer.from_pretrained(
        args.model, trust_remote_code=True, local_files_only=True
    )
    token_ids = {}
    for text in ("有", "无", "已", "未", "\u23f8"):
        ids = tokenizer.encode(text, add_special_tokens=False)
        token_ids[text] = ids
        if text != "\u23f8":
            assert len(ids) == 1 and tokenizer.decode(ids) == text, (text, ids)

    from types import SimpleNamespace

    from vllm.config.multimodal import MultiModalConfig

    mm_config = MultiModalConfig()
    model_config = SimpleNamespace(
        model=args.model, tokenizer=args.model, tokenizer_mode="auto",
        trust_remote_code=True, revision=None, tokenizer_revision=None,
        hf_config=config, hf_text_config=config.get_text_config(),
        dtype=torch.bfloat16,
        multimodal_config=mm_config,
        get_multimodal_config=lambda: mm_config,
    )
    info = WeMMProcessingInfo(InputProcessingContext(model_config, tokenizer))
    processor = WeMMMultiModalProcessor(info, WeMMDummyInputsBuilder(info))
    waveform = np.sin(np.arange(16000) * 2 * np.pi * 440 / 16000).astype(np.float32) * 0.1
    wrapped, _ = wemm_audio_item((waveform, 16000))
    mm_items = info.parse_mm_data({"audio": [wrapped]})
    prompt = tokenizer.encode(
        "<|im_start|>user\n<|audio_start|><|audio_pad|><|audio_end|>"
        "\nWhat do you hear?<|im_end|>\n<|im_start|>assistant\n",
        add_special_tokens=False,
    )
    result = processor.apply(
        ProcessorInputs(prompt=prompt, mm_data_items=mm_items), TimingContext()
    )
    print(json.dumps({
        "architecture": config.architectures,
        "text_model_type": config.text_config.model_type,
        "decision_token_ids": token_ids,
        "prompt_length": len(result["prompt_token_ids"]),
        "audio_placeholders": [
            {"offset": value.offset, "length": value.length}
            for value in result["mm_placeholders"]["audio"]
        ],
        "mm_keys": list(result["mm_kwargs"]["audio"][0]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
