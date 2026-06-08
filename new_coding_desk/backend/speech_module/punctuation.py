"""CT-Transformer punctuation restoration for streaming ASR.

Wraps FunASR real-time punctuation model for adding sentence-final
punctuation to Paraformer output, enabling SentenceMerger's
punctuation-based flush rule.

Model: iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727
Inference time: ~1ms per call (real-time capable).

Also provides boundary character sets and a heuristic fallback for
the rest of the speech module.

Usage:
    from speech_module.punctuation import warmup_punc, add_punctuation
    from speech_module.punctuation import SENTENCE_END, COMMA_BOUNDARY, ALL_BOUNDARY

    warmup_punc()
    text = add_punctuation("今天天气不错")
    # → "今天天气不错。"
"""

from __future__ import annotations

# ── Boundary character sets (used by caption formatter and sentence merger) ──

SENTENCE_END = frozenset({"。", "？", "！", ".", "?", "!"})
COMMA_BOUNDARY = frozenset({"，", ",", "、", "；", ";"})
ALL_BOUNDARY: frozenset[str] = SENTENCE_END | COMMA_BOUNDARY

_punc_model = None


def is_punctuation_loaded() -> bool:
    """Check whether the CT-Transformer punctuation model is loaded.

    Returns True if warmup_punc() succeeded and the model is ready.
    Does NOT trigger loading.
    """
    return _punc_model is not None


def warmup_punc(model_dir: str | None = None, device: str = "cpu"):
    """Load CT-Transformer punctuation model. Idempotent.

    Searches local cache first (models/iic/*punc_ct-transformer*),
    falls back to ModelScope download. Gracefully degrades on failure
    (add_punctuation falls back to heuristic behaviour).
    """
    global _punc_model
    if _punc_model is not None:
        return

    from funasr.auto.auto_model import AutoModel
    import os as _os
    import glob as _glob

    # FunASR 1.3.3: 'ct-punc-c' alias → iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch
    model_id = "iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch"

    # Try local cache first (ModelScope format, then HF cache)
    local = _glob.glob("models/iic/*punc_ct-transformer*")
    if local and _os.path.isdir(local[0]):
        path = local[0]
    else:
        hf_candidates = _glob.glob("models/models--funasr--punc_ct*/snapshots/*")
        if hf_candidates and _os.path.isdir(hf_candidates[0]):
            path = hf_candidates[0]
        else:
            path = model_id

    try:
        _punc_model = AutoModel(
            model=path, disable_update=True, device=device,
        )
    except Exception as e:
        print(f"  CT-Transformer load failed: {e}")
        print(f"  (Punctuation disabled, using heuristic fallback)")
        return

    src = "local cache" if path != model_id else "downloaded"
    print(f"  CT-Transformer punctuation loaded ({src}, device={device}).")


def add_punctuation(text: str) -> str:
    """Add punctuation to plain ASR text.

    Uses CT-Transformer model if loaded.
    Falls back to heuristic: appends 。 if text does not already end with
    sentence-final or comma punctuation.

    Returns text with punctuation inserted. Preserves original character order.
    """
    global _punc_model
    if _punc_model is not None:
        if not text or not text.strip():
            return text
        try:
            result = _punc_model.generate(input=text)
            if isinstance(result, list) and len(result) > 0:
                item = result[0]
                if isinstance(item, dict):
                    return item.get("text", text)
                elif isinstance(item, str):
                    return item
            elif isinstance(result, dict):
                return result.get("text", text)
            elif isinstance(result, str):
                return result
        except Exception:
            pass

    # Heuristic fallback: append 。if text doesn't end with any punctuation
    if text and text[-1] not in ALL_BOUNDARY:
        return text + "。"
    return text
