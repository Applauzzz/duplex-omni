"""Select an audio/text backbone without changing the turn state machine."""

from semantic_vad import MiMoChatProvider, MiMoSemanticVADProvider

QWEN_MODEL_PATH = (
    "/mnt/geminihzceph/user_whynotzhliu/modelbase/Omni/"
    "Qwen3-Omni-30B-A3B-Instruct"
)
WEMM_MODEL_PATH = (
    "/mnt/zehaoliu/user_whynotzhliu/modelbase/Omni/WeMM-Video-35BA3B"
)


def classifier_token_ids(tokenizer):
    result = {}
    for code in ("有", "无", "已", "未"):
        ids = tokenizer.encode(code, add_special_tokens=False)
        if len(ids) != 1 or tokenizer.decode(ids) != code:
            raise ValueError(f"Classifier code {code!r} must round-trip as one token")
        result[code] = ids[0]
    if len(set(result.values())) != len(result):
        raise ValueError("Classifier codes must have distinct token IDs")
    return result


def create_backbone(client, url, *, backbone, model=None, tokenizer_path=None):
    if backbone == "mimo":
        name = model or "mimo-v2.6-flash"
        return (MiMoSemanticVADProvider(client, url, model=name),
                MiMoChatProvider(client, url, model=name))
    if backbone not in ("qwen3-omni", "wemm"):
        raise ValueError(f"Unknown backbone: {backbone}")
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        tokenizer_path or (WEMM_MODEL_PATH if backbone == "wemm" else QWEN_MODEL_PATH),
        local_files_only=True,
    )
    codes = classifier_token_ids(tokenizer)
    name = model or ("wemm" if backbone == "wemm" else "qwen3-omni-thinker")
    return (MiMoSemanticVADProvider(client, url, model=name, code_token_ids=codes),
            MiMoChatProvider(client, url, model=name,
                             enable_thinking=False if backbone == "wemm" else None))
