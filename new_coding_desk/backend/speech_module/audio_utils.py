"""Audio loading utilities with m4a/AAC fallback via pydub."""

from __future__ import annotations
import numpy as np
from typing import Optional


def load_audio(file_path: str) -> tuple[np.ndarray, int]:
    """Load audio file, return (float32 samples, sample_rate).

    Always resamples to 16000 Hz mono float32.
    Tries soundfile first; falls back to pydub for m4a/AAC.
    """
    try:
        import soundfile as sf
        samples, sr = sf.read(file_path, dtype="float32")
    except Exception:
        samples, sr = _load_via_pydub(file_path)

    if samples.ndim > 1:
        samples = samples.mean(axis=1)

    if sr != 16000:
        samples = resample_if_needed(samples, sr, 16000)
        sr = 16000

    samples = samples.astype(np.float32)
    return samples, sr


def _load_via_pydub(file_path: str) -> tuple[np.ndarray, int]:
    """Fallback: load m4a/AAC via pydub."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(file_path)
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        samples /= 32768.0
        return samples, 16000
    except ImportError:
        raise RuntimeError(
            "Cannot load audio: soundfile failed and pydub is not installed. "
            "Install pydub: pip install pydub"
        )
    except Exception as e:
        raise RuntimeError(f"Failed to load audio file '{file_path}': {e}")


def resample_if_needed(
    samples: np.ndarray, orig_sr: int, target_sr: int = 16000
) -> np.ndarray:
    """Resample audio to target sample rate using scipy."""
    if orig_sr == target_sr:
        return samples
    try:
        from scipy.signal import resample
        n_target = int(len(samples) * target_sr / orig_sr)
        return resample(samples, n_target)
    except ImportError:
        raise RuntimeError("scipy required for resampling. Install: pip install scipy")


def apply_highpass_filter(
    audio: np.ndarray,
    sample_rate: int = 16000,
    cutoff: float = 80,
    order: int = 4,
) -> np.ndarray:
    """Remove low-frequency noise (hum, rumble, wind) via Butterworth highpass.

    Phase 1 VAD optimization: cleaner audio → fewer noise false-positives.
    """
    from scipy.signal import butter, sosfilt

    nyquist = sample_rate / 2
    normalized = cutoff / nyquist
    if normalized >= 1.0:
        return audio  # Cutoff above Nyquist, skip
    sos = butter(order, normalized, btype="high", output="sos")
    return sosfilt(sos, audio).astype(audio.dtype)


def apply_preprocessing(
    audio: np.ndarray,
    sample_rate: int = 16000,
    highpass_cutoff: Optional[float] = 80,
    normalize: bool = True,
) -> np.ndarray:
    """Preprocess audio before VAD/ASR: highpass filter + peak normalization.

    Args:
        audio: float32 samples
        sample_rate: Hz
        highpass_cutoff: Hz cutoff for highpass filter, None to skip
        normalize: peak normalize to ±1.0
    """
    if highpass_cutoff is not None:
        audio = apply_highpass_filter(audio, sample_rate, highpass_cutoff)
    if normalize:
        peak = np.max(np.abs(audio))
        if peak > 1e-5:
            audio = audio / peak
    return audio.astype(np.float32)


