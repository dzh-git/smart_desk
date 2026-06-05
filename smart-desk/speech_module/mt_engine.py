"""Bidirectional zh↔en translation via Helsinki-NLP Opus-MT.

Uses two MarianMT models:
  - opus-mt-zh-en: Chinese → English
  - opus-mt-en-zh: English → Chinese

Model resolution (same pattern as stt_streaming.py):
  1. Explicit model_dir → subdir opus-mt-zh-en / opus-mt-en-zh
  2. HF cache: models/models--Helsinki-NLP--opus-mt-zh-en/snapshots/*/
  3. Fallback: from_pretrained() download from HuggingFace Hub

translate() auto-detects language via text_utils.detect_language() and
routes to the appropriate model. Never raises — returns placeholder on failure.
"""

from __future__ import annotations
import importlib.util as _importlib_util
import os as _os
import glob as _glob
from typing import Optional

# Module-level model singletons
_zh2en_model = None
_zh2en_tokenizer = None
_en2zh_model = None
_en2zh_tokenizer = None


# ── Model Path Resolution ────────────────────────────────────────────────────

def _resolve_model_path(model_dir: str | None, model_name: str) -> str:
    """Resolve model path: explicit dir > local HF cache > Hub download.

    model_name like "opus-mt-zh-en" or "opus-mt-en-zh".
    """
    # 1. Explicit model_dir → subdir
    if model_dir and _os.path.isdir(model_dir):
        subdir = _os.path.join(model_dir, model_name)
        if _os.path.isdir(subdir):
            return subdir

    # 2. HF cache
    hf_pattern = f"models/models--Helsinki-NLP--{model_name}/snapshots/*"
    candidates = _glob.glob(hf_pattern)
    if candidates:
        return candidates[0]

    # 3. Hub download fallback
    return f"Helsinki-NLP/{model_name}"


def _load_model(model_name: str, model_dir: str | None, device: str):
    """Load a single MarianMT model + tokenizer. Returns (model, tokenizer)."""
    if _importlib_util.find_spec("torch") is None:
        raise RuntimeError("PyTorch is required before loading MarianMT models")
    from transformers import MarianMTModel, MarianTokenizer

    path = _resolve_model_path(model_dir, model_name)
    tokenizer = MarianTokenizer.from_pretrained(path)
    model = MarianMTModel.from_pretrained(path).to(device)
    model.eval()

    src = "local cache" if _os.path.isdir(path) else "downloaded"
    print(f"  {model_name} loaded ({src}, device={device}).")

    return model, tokenizer


# ── MTEngine ──────────────────────────────────────────────────────────────────

class MTEngine:
    """Bidirectional zh↔en translation via Helsinki-NLP Opus-MT.

    Loads two MarianMT models for Chinese-English and English-Chinese
    translation. Auto-detects input language and routes to the correct model.
    All public methods return placeholders on failure instead of raising.
    """

    def __init__(self, model_dir: str | None = None, device: str = "cpu"):
        """model_dir: optional explicit path. device: 'cpu' or 'cuda'."""
        self._model_dir = model_dir
        self._device = device
        self._ready = False

    # ── Properties ─────────────────────────────────────────────────────────

    @property
    def ready(self) -> bool:
        """True after preload() has completed successfully."""
        return self._ready

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def preload(self) -> None:
        """Load opus-mt-zh-en + opus-mt-en-zh. Idempotent. Raise on first failure."""
        if self._ready:
            return
        if _os.environ.get("SMART_DESK_ENABLE_MT") != "1" and _os.environ.get("SMART_DESK_RUN_SLOW_MODELS") != "1":
            raise RuntimeError("Machine translation preload is disabled; set SMART_DESK_ENABLE_MT=1 to enable it")

        global _zh2en_model, _zh2en_tokenizer, _en2zh_model, _en2zh_tokenizer

        _zh2en_model, _zh2en_tokenizer = _load_model(
            "opus-mt-zh-en", self._model_dir, self._device,
        )
        _en2zh_model, _en2zh_tokenizer = _load_model(
            "opus-mt-en-zh", self._model_dir, self._device,
        )

        self._ready = True

    # ── Translation ────────────────────────────────────────────────────────

    def translate(self, text: str) -> tuple[str, str]:
        """Auto-detect language → translate to the other.

        Returns (zh_str, en_str). Neither is None.
        Never raises — returns placeholder on failure.
        """
        if not text:
            return ("", "")

        try:
            from .text_utils import detect_language

            lang = detect_language(text)
            if lang == "zh":
                en_text = self._generate(text, _zh2en_model, _zh2en_tokenizer)
                return (text, en_text)
            else:
                zh_text = self._generate(text, _en2zh_model, _en2zh_tokenizer)
                return (zh_text, text)
        except Exception:
            return (text, "[translation failed]")

    # ── Internal ───────────────────────────────────────────────────────────

    @staticmethod
    def _generate(text: str, model, tokenizer) -> str:
        """Run MarianMT generation. Returns translated text or placeholder."""
        try:
            inputs = tokenizer(text, return_tensors="pt").to(model.device)
            translated = model.generate(**inputs)
            return tokenizer.decode(translated[0], skip_special_tokens=True)
        except Exception:
            return "[translation failed]"
