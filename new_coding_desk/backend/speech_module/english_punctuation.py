"""Low-latency English punctuation and casing for Zipformer hypotheses.

The sherpa-onnx CNN-BiLSTM model consumes text, not PCM.  It is intentionally
kept separate from the English ASR decoder so a missing punctuation model can
degrade to unpunctuated streaming text without taking recognition offline.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from .text_utils import normalize_english_display

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = (
    PROJECT_ROOT / "models" / "sherpa-onnx-online-punct-en-2024-08-06"
)
MODEL_ENV = "ENGLISH_ONLINE_PUNCTUATION_MODEL_PATH"
MODEL_FILES = ("model.int8.onnx", "bpe.vocab")

# A short hesitation after one of these tokens is not a safe semantic boundary.
# This specifically protects phrases such as "Do we have any assignments?"
# from being frozen as "Do we have any.".
INCOMPLETE_TAIL_WORDS = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "because", "but", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "if", "in", "into", "is", "of", "on", "or", "our", "the",
    "their", "this", "to", "was", "were", "will", "with", "would", "your",
})

_punctuator = None
_model_path: Path | None = None
_load_error: str | None = None
_lock = threading.RLock()
_cache_input = ""
_cache_output = ""
_last_inference_ms = 0.0


def get_english_punctuation_model_path() -> Path:
    raw = os.getenv(MODEL_ENV, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_MODEL_PATH


def _validate_model(path: Path) -> None:
    missing = [name for name in MODEL_FILES if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "English online punctuation model is incomplete at "
            f"{path}: missing {', '.join(missing)}. "
            "Run backend/scripts/prepare_bilingual_models.py."
        )


def warmup_english_punctuation() -> None:
    """Load the shared INT8 CPU punctuation model without downloading it."""
    global _punctuator, _model_path, _load_error
    with _lock:
        if _punctuator is not None:
            return
        path = get_english_punctuation_model_path()
        try:
            _validate_model(path)
            import sherpa_onnx

            config = sherpa_onnx.OnlinePunctuationConfig()
            # sherpa-onnx 1.13 exposes the nested configuration as
            # ``model_config`` (its repr still labels it ``model``).
            model_config = config.model_config
            model_config.cnn_bilstm = str(path / "model.int8.onnx")
            model_config.bpe_vocab = str(path / "bpe.vocab")
            model_config.num_threads = 1
            model_config.provider = "cpu"
            _punctuator = sherpa_onnx.OnlinePunctuation(config)
            _model_path = path
            _load_error = None
        except Exception as exc:
            _punctuator = None
            _model_path = path
            _load_error = str(exc)
            raise


def add_english_punctuation(text: str) -> str:
    """Restore punctuation and true casing for one cumulative hypothesis."""
    global _cache_input, _cache_output, _last_inference_ms
    clean = normalize_english_display(text).lower()
    if not clean:
        return ""
    warmup_english_punctuation()
    assert _punctuator is not None
    with _lock:
        if clean == _cache_input:
            return _cache_output
        started = time.perf_counter()
        output = _punctuator.add_punctuation_with_case(clean)
        _last_inference_ms = (time.perf_counter() - started) * 1000.0
        _cache_input = clean
        _cache_output = normalize_english_display(output)
        return _cache_output


def trailing_word(text: str) -> str:
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text or "")
    return words[-1].casefold() if words else ""


def has_trusted_terminal_boundary(raw_text: str, punctuated_text: str) -> bool:
    """Return whether a short pause may safely freeze the current sentence."""
    clean = normalize_english_display(punctuated_text)
    if not clean or clean[-1] not in ".!?":
        return False
    last = trailing_word(raw_text)
    return bool(last) and last not in INCOMPLETE_TAIL_WORDS


def strip_provisional_terminal(text: str) -> str:
    """Hide the model's end-of-window punctuation until a boundary is trusted."""
    return re.sub(r"[.!?]+$", "", normalize_english_display(text)).rstrip()


def get_english_punctuation_status() -> dict[str, object]:
    path = get_english_punctuation_model_path()
    if _punctuator is not None:
        status, error = "loaded", None
    elif _load_error:
        status, error = "error", _load_error
    elif all((path / name).is_file() for name in MODEL_FILES):
        status, error = "unknown", None
    else:
        status = "error"
        error = "model files are missing; run backend/scripts/prepare_bilingual_models.py"
    return {
        "status": status,
        "path": str(path),
        "error": error,
        "engine": "sherpa_onnx_online_punctuation",
        "last_inference_ms": round(_last_inference_ms, 2),
    }
