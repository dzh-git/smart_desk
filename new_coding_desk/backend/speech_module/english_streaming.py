"""Local CPU English online ASR backed by sherpa-onnx Zipformer.

Unlike the old SenseVoice rolling path, each PCM frame is accepted by the
recognizer once and the stream owns its decoder/cache state.  SenseVoice stays
available for language detection and sentence-final correction elsewhere.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

from .text_utils import merge_english_transcripts, normalize_english_display

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = (
    PROJECT_ROOT / "models" / "sherpa-onnx-streaming-zipformer-en-2023-06-26"
)
MODEL_ENV = "ENGLISH_STREAMING_ASR_MODEL_PATH"
MODEL_FILES = (
    "encoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "decoder-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "joiner-epoch-99-avg-1-chunk-16-left-128.int8.onnx",
    "tokens.txt",
)

_recognizer = None
_model_path: Path | None = None
_load_error: str | None = None
_lock = threading.RLock()


def get_english_streaming_model_path() -> Path:
    """Return the English online model directory without downloading it."""
    raw = os.getenv(MODEL_ENV, "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_MODEL_PATH


def _validate_model(path: Path) -> None:
    missing = [name for name in MODEL_FILES if not (path / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "English streaming ASR model is incomplete at "
            f"{path}: missing {', '.join(missing)}. "
            "Run backend/scripts/prepare_bilingual_models.py."
        )


def warmup_english_streaming() -> None:
    """Load the shared CPU recognizer. Runtime never downloads a model."""
    global _recognizer, _model_path, _load_error
    with _lock:
        if _recognizer is not None:
            return
        path = get_english_streaming_model_path()
        try:
            _validate_model(path)
            import sherpa_onnx

            _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(path / "tokens.txt"),
                encoder=str(path / MODEL_FILES[0]),
                decoder=str(path / MODEL_FILES[1]),
                joiner=str(path / MODEL_FILES[2]),
                num_threads=max(1, min(4, os.cpu_count() or 1)),
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                provider="cpu",
            )
            _model_path = path
            _load_error = None
        except Exception as exc:
            _recognizer = None
            _model_path = path
            _load_error = str(exc)
            raise


def get_english_streaming_status() -> dict[str, str | None]:
    """Return an API-safe status record without forcing model load."""
    path = get_english_streaming_model_path()
    if _recognizer is not None:
        status = "loaded"
        error = None
    elif _load_error:
        status = "error"
        error = _load_error
    elif all((path / item).is_file() for item in MODEL_FILES):
        status = "unknown"
        error = None
    else:
        status = "error"
        error = (
            "model files are missing; run "
            "backend/scripts/prepare_bilingual_models.py"
        )
    return {
        "status": status,
        "path": str(path),
        "error": error,
        "engine": "sherpa_onnx_streaming",
    }


class EnglishStreamingProcessor:
    """One Zipformer stream and cumulative text state for one ASR session."""

    def __init__(self) -> None:
        warmup_english_streaming()
        assert _recognizer is not None
        with _lock:
            self._stream = _recognizer.create_stream()
        self._full_text = ""
        self._finished = False
        self.frames_processed = 0

    @property
    def accumulated_text(self) -> str:
        return self._full_text

    def process_chunk(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        if self._finished:
            return self._full_text
        if not len(audio):
            return self._full_text
        assert _recognizer is not None
        pcm = np.ascontiguousarray(audio, dtype=np.float32)
        with _lock:
            self._stream.accept_waveform(sample_rate, pcm)
            while _recognizer.is_ready(self._stream):
                _recognizer.decode_stream(self._stream)
            result = _recognizer.get_result(self._stream)
        self.frames_processed += 1
        self._merge_result(_result_text(result))
        return self._full_text

    def finish(self) -> str:
        if self._finished:
            return self._full_text
        assert _recognizer is not None
        with _lock:
            self._stream.input_finished()
            while _recognizer.is_ready(self._stream):
                _recognizer.decode_stream(self._stream)
            result = _recognizer.get_result(self._stream)
        self._finished = True
        self._merge_result(_result_text(result))
        return self._full_text

    def _merge_result(self, text: str) -> None:
        candidate = normalize_english_display(text)
        if not candidate:
            return
        # Sherpa returns a growing stream hypothesis.  Merge only when a
        # backend version returns a delta, while retaining corrections safely.
        if candidate.startswith(self._full_text):
            self._full_text = candidate
        elif self._full_text.startswith(candidate):
            return
        else:
            self._full_text = merge_english_transcripts(self._full_text, candidate)


def _result_text(result: object) -> str:
    """Support both sherpa-onnx string and result-object API releases."""
    return result if isinstance(result, str) else str(getattr(result, "text", ""))
