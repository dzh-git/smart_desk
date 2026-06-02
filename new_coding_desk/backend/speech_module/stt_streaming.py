"""True streaming ASR: Paraformer Streaming with encoder cache + is_final control.

Phase 2 stability optimization:
  - Encoder cache (CIF hidden state + FSMN state) correctly passed chunk→chunk
  - is_final triggered by VAD silence threshold, not just segment end
  - No repeated full-context decoding — each frame processed once

Phase 3 accuracy optimization:
  - Chunk size presets for latency/accuracy tradeoff
  - Hotword contextual biasing
  - 2pass offline rescoring (Paraformer-large corrects streaming output)

Replaces pseudo-streaming (repeated full-context decode) with genuine
chunk-based incremental decoding.
"""

from __future__ import annotations
import time
import numpy as np
from typing import Optional

_streaming_model = None
_offline_model = None


# ── Phase 3: Chunk Size Presets ────────────────────────────────────────────

CHUNK_SIZE_PRESETS: dict[str, list[int]] = {
    "ultra_low_latency": [0, 8, 4],   # 480ms block, 240ms lookahead, ~720ms total
    "balanced":          [0, 10, 5],   # 600ms block, 300ms lookahead, ~900ms total (default)
    "high_accuracy":     [0, 12, 6],   # 720ms block, 360ms lookahead, ~1080ms total
    "near_offline":      [0, 16, 8],   # 960ms block, 480ms lookahead, ~1440ms total
}


def get_chunk_preset(name: str = "balanced") -> list[int]:
    """Return chunk_size configuration by preset name.

    Total latency ≈ (current_chunk + right_lookahead) × 60ms + inference_time.

    | Preset            | current_chunk | right_lookahead | Total Delay |
    |-------------------|---------------|-----------------|-------------|
    | ultra_low_latency | 8 (480ms)     | 4 (240ms)       | ~720ms      |
    | balanced (default)| 10 (600ms)    | 5 (300ms)       | ~900ms      |
    | high_accuracy     | 12 (720ms)    | 6 (360ms)       | ~1080ms     |
    | near_offline      | 16 (960ms)    | 8 (480ms)       | ~1440ms     |
    """
    return CHUNK_SIZE_PRESETS.get(name, CHUNK_SIZE_PRESETS["balanced"])


# ── Local Model Path Resolution ──────────────────────────────────────────────

def _find_local_model(pattern: str) -> str | None:
    """Find local cache directory matching pattern.

    Searches both HuggingFace cache (models/models--funasr--*) and
    ModelScope cache (models/iic/*).
    """
    import glob as _glob
    import os as _os
    # HF format: models/models--funasr--<pattern>/snapshots/<hash>/
    base_hf = "models/models--funasr--"
    candidates = _glob.glob(f"{base_hf}{pattern}/snapshots/*")
    if candidates:
        return candidates[0]
    # ModelScope format: models/iic/<model_id>/
    candidates = _glob.glob(f"models/iic/*{pattern}*")
    if candidates:
        return candidates[0]
    return None


def _resolve_model_path(model_dir: str | None, hf_pattern: str, ms_id: str) -> str:
    """Resolve model path: explicit dir > local cache (HF + MS) > ModelScope ID."""
    import os as _os
    if model_dir and _os.path.isdir(model_dir):
        return model_dir
    # Check ModelScope cache first (has .pt), then HF cache
    ms_dir = f"models/{ms_id}"
    if _os.path.isdir(ms_dir):
        return ms_dir
    local = _find_local_model(hf_pattern)
    if local:
        return local
    return ms_id  # Fallback: let FunASR download from ModelScope


# ── Model Loading ───────────────────────────────────────────────────────────

def warmup_streaming(model_dir: str | None = None, device: str = "cpu"):
    """Load Paraformer Streaming model for chunk-based inference.

    Priority: explicit dir > local HF cache > ModelScope download.
    """
    global _streaming_model
    if _streaming_model is not None:
        return

    from funasr.auto.auto_model import AutoModel

    path = _resolve_model_path(
        model_dir,
        "paraformer-zh-streaming",
        "iic/speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online",
    )
    _streaming_model = AutoModel(
        model=path, disable_update=True, device=device,
        ncpu=4 if device == "cpu" else 2,
    )
    src = "local cache" if "/" not in str(path) or "models" in str(path) else "downloaded"
    print(f"  Paraformer Streaming loaded ({src}, device={device}).")


def warmup_offline(model_dir: str | None = None, device: str = "cpu"):
    """Load Paraformer-large for 2pass offline rescoring (Phase 3)."""
    global _offline_model
    if _offline_model is not None:
        return

    from funasr.auto.auto_model import AutoModel

    path = _resolve_model_path(
        model_dir,
        "Paraformer-large",
        "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    )
    _offline_model = AutoModel(
        model=path, disable_update=True, device=device,
        ncpu=4 if device == "cpu" else 2,
    )
    src = "local cache" if "/" not in str(path) or "models" in str(path) else "downloaded"
    print(f"  Paraformer-large loaded ({src}, device={device}).")




# ── Streaming Chunk Processor ────────────────────────────────────────────────

class StreamingChunkProcessor:
    """Per-segment state for true streaming ASR.

    Manages encoder/decoder cache lifecycle across chunks within a VAD segment.

    Key invariants (Phase 2 stability):
      1. cache is ALWAYS updated after each model.generate() call
      2. is_final=True ONLY when VAD detects end-of-sentence silence
      3. After is_final=True, cache is reset (new segment)
    """

    def __init__(
        self,
        chunk_size: list[int] | None = None,
        encoder_chunk_look_back: int = 4,
        decoder_chunk_look_back: int = 1,
        hotwords: str | list[str] | None = None,
    ):
        self._chunk_size = chunk_size or [0, 10, 5]
        self._encoder_lookback = encoder_chunk_look_back
        self._decoder_lookback = decoder_chunk_look_back
        self._hotwords = hotwords

        self._cache: dict = {}
        self._accumulated_text: str = ""
        self._total_frames: int = 0

    @property
    def chunk_size(self) -> list[int]:
        return self._chunk_size

    @property
    def accumulated_text(self) -> str:
        return self._accumulated_text

    def reset(self):
        """Reset state for new VAD segment. Clears cache and accumulated text."""
        self._cache = {}
        self._accumulated_text = ""
        self._total_frames = 0

    def process_chunk(
        self,
        audio: np.ndarray,
        is_final: bool = False,
    ) -> dict:
        """Feed one audio chunk to streaming Paraformer.

        Args:
            audio: float32 16kHz mono chunk
            is_final: True when VAD detects end-of-sentence silence

        Returns:
            dict with keys: text (new text this chunk), full_text (accumulated),
                           cache_valid (bool), is_final (echoed)

        Raises:
            RuntimeError: if model not loaded
        """
        global _streaming_model
        if _streaming_model is None:
            raise RuntimeError("Streaming model not loaded. Call warmup_streaming() first.")

        audio32 = audio.astype(np.float32)
        if audio32.ndim > 1:
            audio32 = audio32.mean(axis=1)

        t0 = time.perf_counter()
        result = _streaming_model.generate(
            input=audio32,
            cache=self._cache,
            is_final=is_final,
            chunk_size=self._chunk_size,
            encoder_chunk_look_back=self._encoder_lookback,
            decoder_chunk_look_back=self._decoder_lookback,
        )
        decode_ms = round((time.perf_counter() - t0) * 1000)

        # CRITICAL (Phase 2): cache is mutated IN-PLACE by model.generate().
        # self._cache already contains updated encoder/decoder/frontend states.
        # Do NOT reassign self._cache = result — result is a list, not a dict.

        # Extract incremental text
        chunk_text = ""
        if isinstance(result, list) and len(result) > 0:
            item = result[0]
            if isinstance(item, dict):
                chunk_text = item.get("text", "")
            elif isinstance(item, str):
                chunk_text = item
        elif isinstance(result, dict):
            chunk_text = result.get("text", "")
        elif isinstance(result, str):
            chunk_text = result

        # Clean FunASR language tags
        import re
        chunk_text = re.sub(r"<\|[^|]+\|>", "", chunk_text).strip()

        # Accumulate: streaming chunks are incremental, final chunk may flush residuals.
        # Strategy: keep the longest non-empty accumulated text seen across all chunks.
        prev_text = self._accumulated_text
        if chunk_text:
            if is_final:
                # is_final forces CIF to flush remaining tokens.
                # If the final chunk produces shorter text than what we've accumulated
                # during streaming, keep the accumulated (more complete) version.
                if len(chunk_text) > len(prev_text):
                    self._accumulated_text = chunk_text
                # else: keep prev_text (the streaming-accumulated version)
            else:
                # Streaming: merge incremental output with previous
                self._accumulated_text = self._merge_text(prev_text, chunk_text)

        self._total_frames += len(audio32)

        return {
            "text": chunk_text,
            "full_text": self._accumulated_text,
            "is_final": is_final,
            "decode_ms": decode_ms,
            "cache_valid": bool(self._cache),
        }

    @staticmethod
    def _merge_text(prev: str, chunk: str) -> str:
        """Merge incremental chunk text with previous accumulated text.

        Delegates to text_utils.merge_texts for the public implementation.
        """
        from .text_utils import merge_texts
        return merge_texts(prev, chunk)


# ── Offline Rescore (Phase 3: 2pass) ────────────────────────────────────────

def offline_rescore(audio: np.ndarray) -> str:
    """Offline full-context rescoring with Paraformer-large.

    Used for 2pass: replaces streaming result when VAD detects end-of-sentence.
    """
    global _offline_model
    if _offline_model is None:
        raise RuntimeError("Offline model not loaded. Call warmup_offline() first.")

    audio32 = audio.astype(np.float32)
    if audio32.ndim > 1:
        audio32 = audio32.mean(axis=1)

    result = _offline_model.generate(input=audio32, batch_size_s=60)

    text = ""
    if isinstance(result, list) and len(result) > 0:
        item = result[0]
        if isinstance(item, dict):
            text = item.get("text", "")
        elif isinstance(item, str):
            text = item
    elif isinstance(result, dict):
        text = result.get("text", "")
    elif isinstance(result, str):
        text = result

    import re
    text = re.sub(r"<\|[^|]+\|>", "", text).strip()
    return text


# ── VAD Silence Detector (lightweight) ──────────────────────────────────────

class SilenceDetector:
    """Lightweight RMS-based silence counter for is_final triggering.

    Not a full VAD — used alongside the main VAD to detect end-of-sentence
    within an active speech segment.

    Phase 2: triggers is_final=True when continuous silence exceeds threshold.
    """

    def __init__(
        self,
        silence_threshold_rms: float = 0.005,
        silence_duration_s: float = 0.8,
        sample_rate: int = 16000,
    ):
        self._threshold = silence_threshold_rms
        self._silence_duration = silence_duration_s
        self._sample_rate = sample_rate
        self._silence_samples = 0.0  # accumulated seconds of silence

    def feed(self, chunk: np.ndarray, is_speech: bool):
        """Update silence counter.

        Args:
            chunk: audio chunk
            is_speech: True if main VAD says this chunk is speech-like
        """
        if is_speech:
            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
            if rms < self._threshold:
                self._silence_samples += len(chunk) / self._sample_rate
            else:
                self._silence_samples = 0.0
        else:
            self._silence_samples += len(chunk) / self._sample_rate

    @property
    def should_end(self) -> bool:
        """True when accumulated silence exceeds threshold → trigger is_final."""
        return self._silence_samples >= self._silence_duration

    def reset(self):
        self._silence_samples = 0.0
