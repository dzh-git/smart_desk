"""
TranslationModelService — wraps OPUS-MT zh-en model for Chinese-to-English translation.

Provides:
    - Config-driven model path (TRANSLATION_MODEL_PATH env var).
    - Enable/disable toggle (ENABLE_TRANSLATION_MODEL env var).
    - Singleton lazy-load with load-latency tracking.
    - Safe fallback when model is unavailable (returns placeholder with error reason).

Per Task 123 requirements:
    - Default model: Helsinki-NLP/opus-mt-zh-en (HuggingFace).
    - Fallback local path: models/opus-mt-zh-en (relative to project root).
    - Only used for final translation (never interim).
    - Failure must not crash the backend.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Sentinel / constants ───────────────────────────────────────────────────────

NOT_AVAILABLE = "[translation not available]"

#: Env var to enable or disable the real translation model.
_ENV_ENABLE = "ENABLE_TRANSLATION_MODEL"
#: Env var to override the model path (local dir or HF model id).
_ENV_MODEL_PATH = "TRANSLATION_MODEL_PATH"

_DEFAULT_HF_MODEL = "Helsinki-NLP/opus-mt-zh-en"
_DEFAULT_LOCAL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "models",
    "opus-mt-zh-en",
)


def is_translation_model_enabled() -> bool:
    """Check the ENABLE_TRANSLATION_MODEL env var (case-insensitive).

    Returns True for: "1", "true", "yes" (case-insensitive).
    Returns False otherwise (including unset).
    """
    val = os.environ.get(_ENV_ENABLE, "").strip().lower()
    return val in ("1", "true", "yes")


def get_model_path() -> str:
    """Resolve the model path from env var or default locations.

    Resolution order:
        1. TRANSLATION_MODEL_PATH env var (if set).
        2. Local ``models/opus-mt-zh-en/`` if it exists and contains model files.
        3. HuggingFace model ID ``Helsinki-NLP/opus-mt-zh-en`` (download via HF hub).

    Returns a path string (local directory or HF model ID).
    """
    # 1. Explicit env var
    env_path = os.environ.get(_ENV_MODEL_PATH, "").strip()
    if env_path:
        return env_path

    # 2. Local project path
    if os.path.isdir(_DEFAULT_LOCAL_PATH):
        # Check for safetensors or bin file
        has_weights = any(
            os.path.isfile(os.path.join(_DEFAULT_LOCAL_PATH, fname))
            for fname in ("model.safetensors", "pytorch_model.bin")
        )
        if has_weights:
            return _DEFAULT_LOCAL_PATH

    # 3. Fallback to HF model ID
    return _DEFAULT_HF_MODEL


class TranslationModelService:
    """Singleton service for the OPUS-MT zh-en translation model.

    Usage:
        svc = TranslationModelService.get_instance()
        result = svc.translate("你好，欢迎参加智能会议。")
        # → "Hello, welcome to the smart meeting."

    Lifecycle:
        - First call to ``translate()`` triggers lazy load.
        - Subsequent calls reuse the loaded model.
        - ``unload()`` releases the model from memory.
    """

    _instance: TranslationModelService | None = None

    def __init__(self) -> None:
        self._model: Any = None
        self._tokenizer: Any = None
        self._loaded: bool = False
        self._load_error: str | None = None
        self._load_latency_ms: float = 0.0
        self._enabled: bool = is_translation_model_enabled()
        self._model_path: str = get_model_path()
        self._inference_lock = threading.RLock()

    # ── Singleton ──────────────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> TranslationModelService:
        """Return the module-level singleton, creating it if needed."""
        if cls._instance is None:
            cls._instance = TranslationModelService()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton (useful for testing)."""
        if cls._instance is not None:
            cls._instance.unload()
        cls._instance = None

    # ── Properties ─────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def load_latency_ms(self) -> float:
        return self._load_latency_ms

    @property
    def model_path(self) -> str:
        return self._model_path

    @property
    def provider(self) -> str:
        """Human-readable provider string for the report."""
        if not self._enabled:
            return "disabled"
        if self._loaded:
            return "HuggingFace Transformers (OPUS-MT zh-en)"
        return "not_loaded"

    # ── Load ───────────────────────────────────────────────────────────────────

    def load(self) -> bool:
        with self._inference_lock:
            return self._load_locked()

    def _load_locked(self) -> bool:
        """Load the model and tokenizer. Idempotent.

        Returns True on success, False on failure (sets self._load_error).
        Will not raise — all exceptions are caught and stored.
        """
        if self._loaded:
            return True

        if not self._enabled:
            self._load_error = "Translation model is disabled (ENABLE_TRANSLATION_MODEL not set)"
            logger.info("TranslationModelService: disabled by env var")
            return False

        t0 = time.monotonic()
        try:
            from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

            logger.info(
                "TranslationModelService: loading model from %s",
                self._model_path,
            )
            self._tokenizer = AutoTokenizer.from_pretrained(
                self._model_path, local_files_only=False,
            )
            self._model = AutoModelForSeq2SeqLM.from_pretrained(
                self._model_path, local_files_only=False,
            )
            self._model.eval()
            self._loaded = True
            self._load_error = None
            elapsed = time.monotonic() - t0
            self._load_latency_ms = round(elapsed * 1000, 1)
            logger.info(
                "TranslationModelService: loaded in %.1fms",
                self._load_latency_ms,
            )
            return True
        except Exception as exc:
            elapsed = time.monotonic() - t0
            self._loaded = False
            self._load_error = f"Model load failed after {elapsed*1000:.0f}ms: {exc}"
            logger.warning("TranslationModelService: %s", self._load_error)
            return False

    # ── Translate ──────────────────────────────────────────────────────────────

    def translate(self, text: str) -> str:
        with self._inference_lock:
            return self._translate_locked(text)

    def _translate_locked(self, text: str) -> str:
        """Translate Chinese text to English using the loaded model.

        Args:
            text: Source Chinese text (may contain punctuation).

        Returns:
            English translation string. If the model is disabled or fails,
            returns NOT_AVAILABLE or an error message.

        This method is safe to call even when the model is disabled or
        not loaded — it will attempt lazy load, and fall back gracefully.
        """
        if not text or not text.strip():
            return ""

        if not self._enabled:
            return NOT_AVAILABLE

        # Lazy load
        if not self._loaded:
            success = self.load()
            if not success:
                return NOT_AVAILABLE

        # Run inference
        try:
            import torch

            inputs = self._tokenizer(
                text, return_tensors="pt", padding=True, truncation=True,
            )
            with torch.no_grad():
                translated_ids = self._model.generate(**inputs)
            result = self._tokenizer.decode(
                translated_ids[0], skip_special_tokens=True,
            )
            return result.strip()
        except Exception as exc:
            logger.warning("TranslationModelService: inference failed: %s", exc)
            self._load_error = f"Translation inference failed: {exc}"
            return NOT_AVAILABLE

    # ── Unload ─────────────────────────────────────────────────────────────────

    def unload(self) -> None:
        """Release the model and tokenizer from memory."""
        self._model = None
        self._tokenizer = None
        self._loaded = False
        self._load_error = None
        self._load_latency_ms = 0.0
