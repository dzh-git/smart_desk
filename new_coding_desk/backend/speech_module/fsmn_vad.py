"""ML-based VAD: FunASR FSMN-VAD with thread safety.

Phase 1 optimization: replaces energy-based VAD for better accuracy in
noisy environments, fewer false-positive segments, and fewer over-cuts.

Interface: detect_segments() — run on full audio, return speech regions.
"""

from __future__ import annotations
import threading
import numpy as np
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _find_local_fsmn_vad() -> str | None:
    """Find local HuggingFace cache for FSMN-VAD model."""
    import glob as _glob
    candidates = _glob.glob(
        str(_PROJECT_ROOT / "models" / "models--funasr--fsmn-vad" / "snapshots" / "*")
    )
    return candidates[0] if candidates else None


class FSMNVAD:
    """Thread-safe FSMN-VAD wrapper with FunASR AutoModel.

    ML-based: discriminates speech from noise, not just RMS.
    Thread-safe: internal lock around model.generate().
    Configurable: min_silence_duration_ms, speech_noise_thres, etc.
    """

    def __init__(
        self,
        model_name: str = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
        min_silence_duration_ms: int = 400,
        max_single_segment_time: int = 30000,
        speech_noise_thres: float = 0.55,
        speech_pad_ms: int = 150,
        device: str = "cpu",
    ):
        self._model_name = model_name
        self._min_silence_duration_ms = min_silence_duration_ms
        self._max_single_segment_time = max_single_segment_time
        self._speech_noise_thres = speech_noise_thres
        self._speech_pad_ms = speech_pad_ms
        self._device = device

        self._model = None
        self._lock = threading.Lock()
        self._sample_rate = 16000

    def _load_model(self):
        """Lazy-load FSMN-VAD model (expensive, ~200MB download on first use).

        Priority: local HF cache > explicit dir > ModelScope download.
        """
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from funasr import AutoModel

            # Resolve model path: try local HF cache first
            model_path = self._model_name
            local = _find_local_fsmn_vad()
            if local:
                model_path = local

            self._model = AutoModel(
                model=model_path,
                device=self._device,
                disable_update=True,
                vad_kwargs={
                    "max_single_segment_time": self._max_single_segment_time,
                    "min_silence_duration_ms": self._min_silence_duration_ms,
                    "speech_noise_thres": self._speech_noise_thres,
                    "speech_pad_ms": self._speech_pad_ms,
                },
            )

    def preload(self) -> None:
        """Load model weights without running inference."""
        self._load_model()

    def detect_segments(self, audio: np.ndarray) -> list[dict]:
        """Run FSMN-VAD on full audio buffer, return detected speech segments.

        Thread-safe. Returns list of {start_ms, end_ms, duration_ms}.
        """
        self._load_model()
        with self._lock:
            result = self._model.generate(
                input=audio,
                batch_size_s=300,
            )

        segments = []
        if result and len(result) > 0 and "value" in result[0]:
            for seg in result[0]["value"]:
                start_ms = int(seg[0])
                end_ms = int(seg[1])
                segments.append({
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "duration_ms": end_ms - start_ms,
                })
        return segments


def merge_short_segments(
    segments: list[dict],
    min_duration_ms: float = 2000,
    max_gap_ms: float = 500,
) -> list[dict]:
    """Post-process VAD segments: merge adjacent segments that are too short.

    Phase 1 optimization: reduces over-fragmentation from VAD.
    A short segment close to another short segment gets merged.

    Args:
        segments: list of {start_ms, end_ms, ...}
        min_duration_ms: segments shorter than this are candidates for merging
        max_gap_ms: maximum gap between segments to allow merging

    Returns:
        merged list of segments
    """
    if not segments:
        return segments

    merged = []
    for seg in segments:
        if not merged:
            merged.append(dict(seg))
            continue

        gap = seg["start_ms"] - merged[-1]["end_ms"]
        prev_dur = merged[-1]["end_ms"] - merged[-1]["start_ms"]

        if gap < max_gap_ms and prev_dur < min_duration_ms:
            # Merge: extend previous segment
            merged[-1]["end_ms"] = seg["end_ms"]
            merged[-1]["duration_ms"] = merged[-1]["end_ms"] - merged[-1]["start_ms"]
        else:
            merged.append(dict(seg))

    return merged


_DEFAULT_VAD: FSMNVAD | None = None
_DEFAULT_VAD_ERROR: str | None = None
_DEFAULT_VAD_LOCK = threading.Lock()


def get_default_vad() -> FSMNVAD:
    global _DEFAULT_VAD, _DEFAULT_VAD_ERROR
    if _DEFAULT_VAD is not None:
        return _DEFAULT_VAD
    with _DEFAULT_VAD_LOCK:
        if _DEFAULT_VAD is None:
            try:
                vad = FSMNVAD()
                vad.preload()
                _DEFAULT_VAD = vad
                _DEFAULT_VAD_ERROR = None
            except Exception as exc:
                _DEFAULT_VAD_ERROR = str(exc)
                raise
    return _DEFAULT_VAD


def get_vad_status() -> dict:
    return {
        "state": "loaded" if _DEFAULT_VAD is not None else (
            "error" if _DEFAULT_VAD_ERROR else "unknown"
        ),
        "last_error": _DEFAULT_VAD_ERROR,
    }


def trim_to_speech(
    audio: np.ndarray,
    sample_rate: int = 16000,
    *,
    min_voice_ms: int = 300,
    pad_ms: int = 150,
) -> np.ndarray | None:
    """Keep FSMN-confirmed voice regions, returning None for noise-only audio."""
    if sample_rate != 16000:
        raise ValueError("FSMN-VAD expects 16 kHz audio")
    vad = get_default_vad()
    segments = merge_short_segments(vad.detect_segments(audio))
    if not segments:
        return None
    total_voice_ms = sum(max(0, s["end_ms"] - s["start_ms"]) for s in segments)
    if total_voice_ms < min_voice_ms:
        return None

    chunks: list[np.ndarray] = []
    total_ms = len(audio) * 1000 / sample_rate
    for segment in segments:
        start_ms = max(0, segment["start_ms"] - pad_ms)
        end_ms = min(total_ms, segment["end_ms"] + pad_ms)
        start = int(start_ms * sample_rate / 1000)
        end = int(end_ms * sample_rate / 1000)
        if end > start:
            chunks.append(audio[start:end])
    return np.concatenate(chunks).astype(np.float32) if chunks else None
