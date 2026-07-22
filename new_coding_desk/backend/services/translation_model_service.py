"""Local, direction-aware OPUS-MT translation service."""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

NOT_AVAILABLE = "[translation not available]"
_ENV_ENABLE = "ENABLE_TRANSLATION_MODEL"
_ENV_LEGACY_PATH = "TRANSLATION_MODEL_PATH"
_DIRECTION_ENV = {
    ("zh", "en"): "TRANSLATION_ZH_EN_MODEL_PATH",
    ("en", "zh"): "TRANSLATION_EN_ZH_MODEL_PATH",
}
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DEFAULT_LOCAL_PATHS = {
    ("zh", "en"): os.path.join(_PROJECT_ROOT, "models", "opus-mt-zh-en"),
    ("en", "zh"): os.path.join(_PROJECT_ROOT, "models", "opus-mt-en-zh"),
}
_SUPPORTED_DIRECTIONS = tuple(_DEFAULT_LOCAL_PATHS)

# Marian's bundled generation config permits 512 unconstrained output tokens.
# That is harmless for short inputs, but a malformed or unusually long ASR
# sentence can make beam search repeat a name/fragment until that limit.  Keep
# every model call deliberately small and semantic.
_TERMINAL_BOUNDARIES = frozenset("。！？.!?")
_CLAUSE_BOUNDARIES = frozenset("，,、；;：:")
_DEFAULT_SOURCE_TOKEN_LIMIT = 64
_RETRY_SOURCE_TOKEN_LIMIT = 32
_MAX_NEW_TOKENS = 192


def _split_at_boundaries(text: str, boundaries: frozenset[str]) -> list[str]:
    """Split after punctuation while retaining that punctuation in each unit."""
    units: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char in boundaries:
            unit = text[start:index + 1].strip()
            if unit:
                units.append(unit)
            start = index + 1
    tail = text[start:].strip()
    if tail:
        units.append(tail)
    return units


def _token_count(tokenizer: Any, text: str) -> int:
    """Return a tokenizer count, with a deterministic fallback for test doubles."""
    try:
        encoded = tokenizer(text, add_special_tokens=True, truncation=False)
        ids = encoded.get("input_ids") if hasattr(encoded, "get") else encoded["input_ids"]
        if ids and isinstance(ids[0], list):
            ids = ids[0]
        if isinstance(ids, (list, tuple)):
            return max(1, len(ids))
    except Exception:
        pass
    # Chinese characters and non-space English words are both conservative
    # enough fallbacks when a lightweight mock tokenizer is injected in tests.
    return max(1, len(re.findall(r"[\u4e00-\u9fff]|\S+", text)))


def _fits_token_limit(tokenizer: Any, text: str, token_limit: int) -> bool:
    return _token_count(tokenizer, text) <= token_limit


def _split_oversized_unit(
    text: str,
    tokenizer: Any,
    source_lang: str,
    token_limit: int,
) -> list[str]:
    """Split one long clause without cutting English words where possible."""
    text = text.strip()
    if not text or _fits_token_limit(tokenizer, text, token_limit):
        return [text] if text else []

    result: list[str] = []
    remainder = text
    while remainder:
        if _fits_token_limit(tokenizer, remainder, token_limit):
            result.append(remainder)
            break

        if source_lang == "en":
            words = remainder.split()
            if len(words) > 1:
                best = 1
                for end in range(2, len(words) + 1):
                    if _fits_token_limit(tokenizer, " ".join(words[:end]), token_limit):
                        best = end
                    else:
                        break
                result.append(" ".join(words[:best]))
                remainder = " ".join(words[best:])
                continue

        # Chinese normally has no spaces; preserve its exact character order.
        best = 1
        for end in range(2, len(remainder) + 1):
            if _fits_token_limit(tokenizer, remainder[:end], token_limit):
                best = end
            else:
                break
        result.append(remainder[:best])
        remainder = remainder[best:].lstrip()
    return result


def _split_translation_units(
    text: str,
    tokenizer: Any,
    source_lang: str,
    token_limit: int = _DEFAULT_SOURCE_TOKEN_LIMIT,
) -> list[str]:
    """Produce bounded, punctuation-preserving translation units.

    Terminal sentences are deliberately never merged: translating each one
    independently prevents a long ASR finalization from poisoning the entire
    meeting-record translation.
    """
    units: list[str] = []
    for sentence in _split_at_boundaries(text, _TERMINAL_BOUNDARIES):
        if _fits_token_limit(tokenizer, sentence, token_limit):
            units.append(sentence)
            continue
        clauses = _split_at_boundaries(sentence, _CLAUSE_BOUNDARIES)
        for clause in clauses or [sentence]:
            units.extend(_split_oversized_unit(clause, tokenizer, source_lang, token_limit))
    return units


def _output_looks_degenerate(text: str, generated_length: int, max_new_tokens: int) -> bool:
    """Reject capped or clearly looping output before it reaches persistence."""
    if generated_length >= max_new_tokens:
        return True
    tokens = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]|\d+|[^\w\s]", text)
    if len(tokens) < 24:
        return False
    counts = Counter(tokens)
    if max(counts.values()) / len(tokens) > 0.28:
        return True
    trigrams = [tuple(tokens[index:index + 3]) for index in range(len(tokens) - 2)]
    return bool(trigrams and max(Counter(trigrams).values()) >= 4)


def is_translation_model_enabled() -> bool:
    value = os.environ.get(_ENV_ENABLE, "").strip().lower()
    return value in {"1", "true", "yes"}


def get_model_path(source_lang: str = "zh", target_lang: str = "en") -> str:
    """Resolve a local model path with direction-specific variables first."""

    direction = (source_lang.lower(), target_lang.lower())
    if direction not in _SUPPORTED_DIRECTIONS:
        raise ValueError(f"Unsupported translation direction: {direction[0]}->{direction[1]}")
    explicit = os.environ.get(_DIRECTION_ENV[direction], "").strip()
    if explicit:
        return explicit
    if direction == ("zh", "en"):
        legacy = os.environ.get(_ENV_LEGACY_PATH, "").strip()
        if legacy:
            return legacy
    return _DEFAULT_LOCAL_PATHS[direction]


@dataclass
class _ModelBundle:
    source_lang: str
    target_lang: str
    path: str
    tokenizer: Any = None
    model: Any = None
    loaded: bool = False
    error: str | None = None
    load_latency_ms: float = 0.0


class TranslationModelService:
    """Singleton registry for local zh→en and en→zh OPUS-MT models."""

    _instance: "TranslationModelService | None" = None

    def __init__(self) -> None:
        self._enabled = is_translation_model_enabled()
        self._bundles = {
            direction: _ModelBundle(*direction, get_model_path(*direction))
            for direction in _SUPPORTED_DIRECTIONS
        }
        self._inference_lock = threading.RLock()
        # Compatibility attributes retained for older diagnostics/tests.
        self._loaded = False

    @classmethod
    def get_instance(cls) -> "TranslationModelService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        if cls._instance is not None:
            cls._instance.unload()
        cls._instance = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def loaded(self) -> bool:
        """Legacy zh→en readiness property."""
        return self._bundles[("zh", "en")].loaded

    @property
    def all_loaded(self) -> bool:
        return all(bundle.loaded for bundle in self._bundles.values())

    @property
    def load_error(self) -> str | None:
        return next((bundle.error for bundle in self._bundles.values() if bundle.error), None)

    @property
    def load_latency_ms(self) -> float:
        return self._bundles[("zh", "en")].load_latency_ms

    @property
    def model_path(self) -> str:
        return self._bundles[("zh", "en")].path

    @property
    def provider(self) -> str:
        if not self._enabled:
            return "disabled"
        if self.all_loaded:
            return "HuggingFace Transformers (local OPUS-MT zh-en + en-zh)"
        return "not_loaded"

    def load(self, source_lang: str = "zh", target_lang: str = "en") -> bool:
        direction = (source_lang.lower(), target_lang.lower())
        if direction not in self._bundles:
            return False
        with self._inference_lock:
            return self._load_bundle(self._bundles[direction])

    def load_all(self) -> bool:
        """Sequentially preload both CPU models to avoid memory spikes."""
        if not self._enabled:
            for bundle in self._bundles.values():
                bundle.error = "Translation model is disabled (ENABLE_TRANSLATION_MODEL not set)"
            return False
        ok = True
        for source_lang, target_lang in _SUPPORTED_DIRECTIONS:
            ok = self.load(source_lang, target_lang) and ok
        return ok

    def _load_bundle(self, bundle: _ModelBundle) -> bool:
        if bundle.loaded:
            return True
        if not self._enabled:
            bundle.error = "Translation model is disabled (ENABLE_TRANSLATION_MODEL not set)"
            return False
        if not os.path.isdir(bundle.path):
            bundle.error = f"Local translation model directory is missing: {bundle.path}"
            return False

        started = time.monotonic()
        try:
            from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

            bundle.tokenizer = AutoTokenizer.from_pretrained(
                bundle.path, local_files_only=True,
            )
            bundle.model = AutoModelForSeq2SeqLM.from_pretrained(
                bundle.path, local_files_only=True,
            )
            bundle.model.eval()
            bundle.loaded = True
            bundle.error = None
            bundle.load_latency_ms = round((time.monotonic() - started) * 1000, 1)
            self._loaded = self.loaded
            logger.info(
                "Loaded local OPUS-MT %s->%s in %.1fms from %s",
                bundle.source_lang,
                bundle.target_lang,
                bundle.load_latency_ms,
                bundle.path,
            )
            return True
        except Exception as exc:
            bundle.loaded = False
            bundle.error = (
                f"Model load failed after {(time.monotonic() - started) * 1000:.0f}ms: {exc}"
            )
            logger.warning("OPUS-MT %s->%s: %s", bundle.source_lang, bundle.target_lang, bundle.error)
            return False

    @staticmethod
    def _max_new_tokens(source_tokens: int) -> int:
        # The output can legitimately be longer than a Chinese source sentence,
        # but never needs the model's default 512-token escape hatch.
        return min(_MAX_NEW_TOKENS, max(48, source_tokens * 2 + 16))

    def _generate_unit(
        self,
        bundle: _ModelBundle,
        text: str,
        *,
        stricter: bool = False,
        quality: str = "final",
    ) -> tuple[str, bool]:
        """Generate one bounded unit and report whether its output is usable."""
        import torch

        source_tokens = _token_count(bundle.tokenizer, text)
        max_new_tokens = self._max_new_tokens(source_tokens)
        inputs = bundle.tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=_DEFAULT_SOURCE_TOKEN_LIMIT if not stricter else _RETRY_SOURCE_TOKEN_LIMIT,
        )
        generation_options = {
            "num_beams": 2 if quality == "live" else 4,
            "max_new_tokens": max_new_tokens,
            "no_repeat_ngram_size": 2 if stricter else 3,
            "repetition_penalty": 1.25 if stricter else 1.15,
            "early_stopping": True,
        }
        with torch.no_grad():
            translated_ids = bundle.model.generate(**inputs, **generation_options)
        translated = bundle.tokenizer.decode(
            translated_ids[0], skip_special_tokens=True,
        ).strip()
        generated_length = len(translated_ids[0])
        return translated, not _output_looks_degenerate(
            translated,
            generated_length,
            max_new_tokens,
        )

    @staticmethod
    def _join_units(parts: list[str], target_lang: str) -> str:
        if target_lang == "en":
            return " ".join(part.strip() for part in parts if part.strip()).strip()
        return re.sub(r"\s+", "", "".join(part.strip() for part in parts)).strip()

    def translate(
        self,
        text: str,
        source_lang: str = "zh",
        target_lang: str = "en",
        *,
        quality: str = "final",
    ) -> str:
        clean = (text or "").strip()
        if not clean:
            return ""
        source_lang = source_lang.lower()
        target_lang = target_lang.lower()
        if source_lang == target_lang:
            return clean
        direction = (source_lang, target_lang)
        if direction not in self._bundles or not self._enabled:
            return NOT_AVAILABLE

        with self._inference_lock:
            bundle = self._bundles[direction]
            if not bundle.loaded and not self._load_bundle(bundle):
                return NOT_AVAILABLE
            try:
                parts: list[str] = []
                for unit in _split_translation_units(
                    clean, bundle.tokenizer, source_lang,
                ):
                    translated, valid = self._generate_unit(
                        bundle, unit, quality=quality,
                    )
                    if not valid:
                        retry_units = _split_translation_units(
                            unit,
                            bundle.tokenizer,
                            source_lang,
                            _RETRY_SOURCE_TOKEN_LIMIT,
                        )
                        retry_parts: list[str] = []
                        for retry_unit in retry_units:
                            retry_translated, retry_valid = self._generate_unit(
                                bundle,
                                retry_unit,
                                stricter=True,
                                quality=quality,
                            )
                            if not retry_valid:
                                bundle.error = (
                                    "Translation output was rejected as repetitive after retry"
                                )
                                logger.warning(
                                    "OPUS-MT %s->%s rejected repetitive output for %r",
                                    source_lang, target_lang, retry_unit[:80],
                                )
                                return NOT_AVAILABLE
                            retry_parts.append(retry_translated)
                        parts.extend(retry_parts)
                    else:
                        parts.append(translated)
                result = self._join_units(parts, target_lang)
                bundle.error = None
                return result
            except Exception as exc:
                bundle.error = f"Translation inference failed: {exc}"
                logger.warning("OPUS-MT %s->%s: %s", source_lang, target_lang, bundle.error)
                return NOT_AVAILABLE

    def get_status(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for (source_lang, target_lang), bundle in self._bundles.items():
            key = f"{source_lang}_{target_lang}"
            status = "disabled" if not self._enabled else (
                "loaded" if bundle.loaded else ("error" if bundle.error else "unknown")
            )
            result[key] = {
                "status": status,
                "path": bundle.path,
                "error": bundle.error,
                "load_latency_ms": bundle.load_latency_ms,
            }
        return result

    def unload(self) -> None:
        with self._inference_lock:
            for bundle in self._bundles.values():
                bundle.model = None
                bundle.tokenizer = None
                bundle.loaded = False
                bundle.error = None
                bundle.load_latency_ms = 0.0
            self._loaded = False
