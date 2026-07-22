"""Sentence-final bilingual ASR powered by a local SenseVoiceSmall model."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .text_utils import detect_language

LanguageCode = Literal["zh", "en"]
RecognitionModel = Literal["sensevoice", "paraformer_zh"]


@dataclass(frozen=True)
class SpeechRecognitionResult:
    """Normalized sentence-final recognition result."""

    text: str
    source_lang: LanguageCode
    recognition_model: RecognitionModel = "sensevoice"


_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_DEFAULT_MODEL_PATH = os.path.join(_PROJECT_ROOT, "models", "SenseVoiceSmall")
_ENV_MODEL_PATH = "BILINGUAL_ASR_MODEL_PATH"
_LANG_TAG = re.compile(r"<\|([^|]+)\|>")
_RICH_TAG = re.compile(r"<\|[^|]+\|>")

_model: Any = None
_model_path: str | None = None
_load_error: str | None = None
_lock = threading.RLock()


def get_bilingual_asr_model_path() -> str:
    """Return the explicit or project-local SenseVoiceSmall directory."""

    return os.environ.get(_ENV_MODEL_PATH, "").strip() or _DEFAULT_MODEL_PATH


def _has_model_weights(path: str) -> bool:
    return os.path.isdir(path) and any(
        os.path.isfile(os.path.join(path, name))
        for name in ("model.pt", "model.safetensors", "pytorch_model.bin")
    )


def normalize_language(value: object, text: str = "") -> LanguageCode:
    """Normalize SenseVoice language metadata to the supported language pair."""

    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized in {"zh", "zh-cn", "cn", "chinese", "cmn", "yue"}:
        return "zh"
    if normalized in {"en", "en-us", "en-gb", "english"}:
        return "en"
    return "zh" if detect_language(text) == "zh" else "en"


def parse_sensevoice_result(raw_result: object) -> SpeechRecognitionResult:
    """Extract text and language from the common FunASR result shapes."""

    item: object = raw_result
    if isinstance(raw_result, list):
        item = raw_result[0] if raw_result else {}

    language: object = ""
    raw_text = ""
    if isinstance(item, dict):
        raw_text = str(item.get("text") or "")
        language = item.get("language") or item.get("lang") or ""
    elif isinstance(item, str):
        raw_text = item

    tags = _LANG_TAG.findall(raw_text)
    if tags:
        language = tags[0]

    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        text = rich_transcription_postprocess(raw_text)
    except Exception:
        text = _RICH_TAG.sub("", raw_text)

    text = _RICH_TAG.sub("", str(text)).strip()
    return SpeechRecognitionResult(
        text=text,
        source_lang=normalize_language(language, text),
        recognition_model="sensevoice",
    )


def warmup_bilingual_asr(model_dir: str | None = None, device: str = "cpu") -> None:
    """Load SenseVoiceSmall from disk without allowing a runtime download."""

    global _model, _model_path, _load_error
    with _lock:
        if _model is not None:
            return
        path = os.path.abspath(model_dir or get_bilingual_asr_model_path())
        _model_path = path
        if not _has_model_weights(path):
            _load_error = f"SenseVoiceSmall model files are missing: {path}"
            raise FileNotFoundError(_load_error)

        try:
            from funasr import AutoModel

            remote_code = os.path.join(path, "model.py")
            kwargs: dict[str, Any] = {
                "model": path,
                "trust_remote_code": os.path.isfile(remote_code),
                "disable_update": True,
                "device": device,
                "ncpu": 4 if device == "cpu" else 2,
            }
            if os.path.isfile(remote_code):
                kwargs["remote_code"] = remote_code
            _model = AutoModel(**kwargs)
            _load_error = None
        except Exception as exc:
            _model = None
            _load_error = f"SenseVoiceSmall load failed: {exc}"
            raise RuntimeError(_load_error) from exc


def recognize_bilingual(
    audio: np.ndarray,
    language: LanguageCode | Literal["auto"] = "auto",
) -> SpeechRecognitionResult:
    """Recognize one 16 kHz mono sentence, optionally forcing zh or en."""

    with _lock:
        if _model is None:
            raise RuntimeError(
                _load_error or "Bilingual ASR is not loaded. Call warmup_bilingual_asr() first."
            )
        audio32 = np.asarray(audio, dtype=np.float32)
        if audio32.ndim > 1:
            audio32 = audio32.mean(axis=1)
        result = _model.generate(
            input=audio32,
            cache={},
            language=language,
            use_itn=True,
            batch_size_s=60,
            disable_pbar=True,
        )
        parsed = parse_sensevoice_result(result)
        if language in {"zh", "en"} and parsed.source_lang != language:
            return SpeechRecognitionResult(
                text=parsed.text,
                source_lang=language,
                recognition_model="sensevoice",
            )
        return parsed


def get_bilingual_asr_status() -> dict[str, object]:
    path = _model_path or os.path.abspath(get_bilingual_asr_model_path())
    return {
        "status": "loaded" if _model is not None else ("error" if _load_error else "unknown"),
        "path": path,
        "error": _load_error,
    }


def reset_bilingual_asr_for_tests() -> None:
    global _model, _model_path, _load_error
    with _lock:
        _model = None
        _model_path = None
        _load_error = None
