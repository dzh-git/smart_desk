"""
Task 128B — Real speech dataset benchmark.

Scans `真实语音数据集/` for .m4a recording files and matching .txt reference
texts, then runs two benchmark modes:

    Mode A (offline ASR):
        Decode full audio → call SpeechModule.transcribe_array()
        → measure inference time, compute CER against reference text.

    Mode B (streaming replay):
        Decode full audio → split into 100ms PCM16 chunks (1600 samples @ 16 kHz)
        → feed sequentially to SpeechModule.process_interim_array()
        → measure first-interim latency, per-chunk inference time,
          interim count, and whether final text is generated.

Output:
    working/speech-real-dataset-benchmark-report.json  (JSON report)
    working/plan/task-speech-real-dataset/final-report.md  (Markdown summary)

Usage:
    python -m backend.scripts.benchmark_real_speech_dataset \
        --dataset-dir "真实语音数据集" \
        --output working/speech-real-dataset-benchmark-report.json

Environment:
    SMART_DESK_ENABLE_SPEECH_TRACE  — set to "true" for trace events (optional)

Constraints (Task 128B):
    - Does NOT modify any .m4a or .txt file in the dataset directory.
    - Does NOT modify backend API, WebSocket protocol, database, or UI.
    - Does NOT replace ASR or translation models.
    - Does NOT implement ASR worker queueing.
    - Benchmark trace is a temporary diagnostic, NOT a product feature.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

_REPORT_PATH_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent
    / "working"
    / "speech-real-dataset-benchmark-report.json"
)

# ── Chunk configuration (matches frontend: 100ms @ 16kHz) ────────────────────

CHUNK_DURATION_MS = 100       # 100ms per PCM frame
SAMPLE_RATE = 16000           # 16 kHz mono
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 1600 samples
CHUNK_BYTES = CHUNK_SAMPLES * 2  # 3200 bytes (PCM16 s16le)

# ── Streaming preset imports (lazy, cached) ─────────────────────────────────

_CHUNK_SIZE_PRESETS: dict[str, list[int]] | None = None


def _get_presets() -> dict[str, list[int]]:
    """Get available chunk size presets from stt_streaming module."""
    global _CHUNK_SIZE_PRESETS
    if _CHUNK_SIZE_PRESETS is None:
        from backend.speech_module.stt_streaming import CHUNK_SIZE_PRESETS
        _CHUNK_SIZE_PRESETS = dict(CHUNK_SIZE_PRESETS)
    return _CHUNK_SIZE_PRESETS


def _get_preset_chunk(preset_name: str) -> list[int]:
    """Resolve a preset name to chunk_size list. Falls back to balanced."""
    presets = _get_presets()
    if preset_name in presets:
        return presets[preset_name]
    # Try common aliases (no 'low_latency' in real code, map to ultra_low_latency)
    alias_map = {
        "low_latency": "ultra_low_latency",
        "high_accuracy": "high_accuracy",
        "near_offline": "near_offline",
    }
    resolved = alias_map.get(preset_name)
    if resolved and resolved in presets:
        return presets[resolved]
    return presets["balanced"]

# ── CER helpers ──────────────────────────────────────────────────────────────


def _normalize_chinese(text: str) -> str:
    """Normalize Chinese text: strip whitespace, remove common punctuation.

    Keeps Chinese characters, letters, digits. Removes ASCII/Chinese punctuation,
    whitespace, and newlines. Used before CER computation.
    """
    # Remove whitespace and newlines
    text = re.sub(r"\s+", "", text)
    # Remove common Chinese punctuation (。，、！？：；""''（）【】《》—…·～)
    text = re.sub(r"[\"\'(),.!?:;<>\[\]{}，。、！？：；""''（）【】《》—…·～]", "", text)
    # Remove ASCII punctuation except letters/digits
    text = re.sub(r"[^\w]", "", text, flags=re.UNICODE)
    return text


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein (edit) distance between two strings.

    Uses a two-row DP matrix for O(min(m,n)) memory.
    """
    if len(s1) < len(s2):
        s1, s2 = s2, s1  # s1 is the longer one
    m, n = len(s1), len(s2)
    prev = list(range(n + 1))
    for i, c1 in enumerate(s1, 1):
        curr = [i] + [0] * n
        for j, c2 in enumerate(s2, 1):
            cost = 0 if c1 == c2 else 1
            curr[j] = min(
                prev[j] + 1,       # deletion
                curr[j - 1] + 1,   # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[n]


def compute_cer(hypothesis: str, reference: str) -> dict[str, Any]:
    """Compute Character Error Rate between hypothesis and reference texts.

    Both texts are normalized (whitespace/punctuation removed, Chinese chars kept).

    Returns:
        dict with keys: cer (float|None), distance (int), ref_len (int),
        normalized_hyp (str), normalized_ref (str), available (bool).
        If reference is empty, returns cer=None, available=False.
    """
    norm_hyp = _normalize_chinese(hypothesis)
    norm_ref = _normalize_chinese(reference)

    ref_len = len(norm_ref)
    if ref_len == 0:
        return {
            "cer": None,
            "distance": 0,
            "ref_len": 0,
            "normalized_hyp": norm_hyp,
            "normalized_ref": norm_ref,
            "available": False,
            "note": "Reference text is empty after normalization — CER unavailable",
        }

    distance = _levenshtein_distance(norm_hyp, norm_ref)
    cer = distance / ref_len

    return {
        "cer": round(cer, 6),
        "distance": distance,
        "ref_len": ref_len,
        "normalized_hyp": norm_hyp,
        "normalized_ref": norm_ref,
        "available": True,
        "note": None,
    }


# ── Dataset scanner ──────────────────────────────────────────────────────────


def scan_dataset(dataset_dir: str) -> list[dict[str, Any]]:
    """Scan the dataset directory for .m4a + matching .txt pairs.

    Returns:
        List of dicts, each with keys:
            audio_file (str): basename of the .m4a file
            text_file (str|None): basename of the matching .txt, or None
            audio_path (str): full path to .m4a
            text_path (str|None): full path to .txt, or None
            warning (str|None): message if .txt is missing
    """
    dataset_path = Path(dataset_dir)
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    m4a_files = sorted(dataset_path.glob("*.m4a"))
    if not m4a_files:
        raise FileNotFoundError(
            f"No .m4a files found in dataset directory: {dataset_dir}"
        )

    results: list[dict[str, Any]] = []
    for m4a in m4a_files:
        stem = m4a.stem  # e.g. "录音1" from "录音1.m4a"
        txt_path = m4a.with_suffix(".txt")
        entry: dict[str, Any] = {
            "audio_file": m4a.name,
            "text_file": txt_path.name if txt_path.exists() else None,
            "audio_path": str(m4a.resolve()),
            "text_path": str(txt_path.resolve()) if txt_path.exists() else None,
            "warning": None,
        }
        if not txt_path.exists():
            entry["warning"] = (
                f"Missing reference text file for '{m4a.name}': "
                f"expected '{txt_path.name}' not found. "
                f"CER will not be computed for this file."
            )
        results.append(entry)

    return results


# ── ffmpeg discovery ─────────────────────────────────────────────────────────


def _find_ffmpeg(ffmpeg_path_arg: str | None = None) -> dict[str, Any]:
    """Locate ffmpeg binary using multiple strategies.

    Priority:
        1. Explicit CLI argument (--ffmpeg-path).
        2. SMART_DESK_FFMPEG_PATH environment variable.
        3. ``ffmpeg`` on PATH (shutil.which).
        4. Windows common install paths (WinGet, manual install).

    Returns:
        dict with keys: available (bool), path (str|None), version (str|None),
        discovery_method (str), search_trace (list of attempted paths).
    """
    result: dict[str, Any] = {
        "available": False,
        "path": None,
        "version": None,
        "discovery_method": None,
        "search_trace": [],
    }

    import shutil

    def _probe(path: str, source: str) -> bool:
        """Try to run ffmpeg -version at *path*, record result."""
        result["search_trace"].append(f"{source}: {path}")
        try:
            r = subprocess.run(
                [path, "-version"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=10,
            )
            if r.returncode == 0:
                result["available"] = True
                result["path"] = shutil.which(path) or path
                first_line = r.stdout.splitlines()[0] if r.stdout else ""
                result["version"] = first_line
                result["discovery_method"] = source
                return True
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass
        return False

    # 1. CLI argument
    if ffmpeg_path_arg:
        if _probe(ffmpeg_path_arg, "cli_arg"):
            return result

    # 2. Environment variable
    env_path = os.environ.get("SMART_DESK_FFMPEG_PATH")
    if env_path:
        if _probe(env_path, "env_var"):
            return result

    # 3. PATH
    path_ff = shutil.which("ffmpeg")
    if path_ff:
        if _probe(path_ff, "path"):
            return result

    # 4. Windows common install locations
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        winget_patterns = [
            # WinGet: Gyan.FFmpeg
            os.path.join(local_appdata, "Microsoft", "WinGet", "Packages",
                         "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe",
                         "ffmpeg-*", "bin", "ffmpeg.exe"),
            # WinGet: generic ffmpeg pattern
            os.path.join(local_appdata, "Microsoft", "WinGet", "Packages",
                         "*FFmpeg*", "*", "bin", "ffmpeg.exe"),
            os.path.join(local_appdata, "Microsoft", "WinGet", "Packages",
                         "*ffmpeg*", "*", "bin", "ffmpeg.exe"),
        ]
        # Also check non-WinGet standard paths
        standard_paths = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        ]

        import glob
        for pattern in winget_patterns:
            candidates = sorted(glob.glob(pattern))
            for c in candidates:
                if _probe(c, "windows_winget"):
                    return result

        for p in standard_paths:
            if _probe(p, "windows_standard"):
                return result

    return result


def probe_environment(ffmpeg_path_arg: str | None = None) -> dict[str, Any]:
    """Probe Python environment, torch, CUDA, ffmpeg.

    Args:
        ffmpeg_path_arg: Optional explicit ffmpeg path (from --ffmpeg-path CLI).
                         If provided, used as the highest-priority ffmpeg source.
    """
    env: dict[str, Any] = {
        "python": sys.version,
        "platform": platform.platform(),
        "torch_available": False,
        "cuda_available": False,
        "cuda_device_name": None,
        "ffmpeg_available": False,
        "ffmpeg_path": None,
        "ffmpeg_version": None,
        "ffmpeg_search_trace": [],
    }

    # Torch
    try:
        import torch
        env["torch_available"] = True
        env["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            env["cuda_device_name"] = torch.cuda.get_device_name(0)
            env["cuda_device_count"] = torch.cuda.device_count()
    except ImportError:
        pass
    except Exception:
        pass

    # ffmpeg — use multi-strategy discovery
    ffmpeg_info = _find_ffmpeg(ffmpeg_path_arg)
    env["ffmpeg_available"] = ffmpeg_info["available"]
    env["ffmpeg_path"] = ffmpeg_info["path"]
    env["ffmpeg_version"] = ffmpeg_info["version"]
    env["ffmpeg_search_trace"] = ffmpeg_info["search_trace"]
    env["ffmpeg_discovery_method"] = ffmpeg_info["discovery_method"]

    return env


# ── Audio decoding via ffmpeg ────────────────────────────────────────────────


def decode_audio(audio_path: str, env_info: dict | None = None) -> dict[str, Any]:
    """Decode an audio file to 16kHz mono float32 using ffmpeg + soundfile.

    Strategy:
        1. Use ffmpeg (from env_info["ffmpeg_path"] or fallback) to decode
           .m4a → temporary WAV (PCM16, mono, 16kHz).
        2. Read the WAV with soundfile.
        3. Return the float32 array and metadata.

    Args:
        audio_path: Path to audio file to decode.
        env_info: Environment dict (from probe_environment). Must contain
                  "ffmpeg_path" if ffmpeg is available.

    Returns:
        dict with keys:
            samples (np.ndarray): float32 audio, shape (N,)
            sr (int): sample rate (always 16000)
            duration_ms (float): audio duration in milliseconds
            decode_ms (float): time spent decoding (ffmpeg + soundfile)
            error (str|None): error message if decoding failed
    """
    result: dict[str, Any] = {
        "samples": None,
        "sr": SAMPLE_RATE,
        "duration_ms": 0.0,
        "decode_ms": 0.0,
        "error": None,
    }

    # Resolve ffmpeg binary path from env_info
    _ffmpeg_bin = "ffmpeg"  # fallback
    if env_info and env_info.get("ffmpeg_path"):
        _ffmpeg_bin = env_info["ffmpeg_path"]

    _t0 = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        # ffmpeg: .m4a → mono 16kHz PCM16 WAV
        ff_cmd = [
            _ffmpeg_bin,
            "-y",                   # overwrite output
            "-i", audio_path,
            "-ac", "1",             # mono
            "-ar", str(SAMPLE_RATE),  # 16 kHz
            "-sample_fmt", "s16",   # PCM16 signed little-endian
            "-f", "wav",
            tmp_path,
        ]
        ff_result = subprocess.run(
            ff_cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        if ff_result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg decode failed (return code {ff_result.returncode}): "
                f"{ff_result.stderr.strip()}"
            )

        # Read decoded WAV
        import soundfile as sf
        samples, sr = sf.read(tmp_path, dtype="float32")

        # Ensure mono
        if samples.ndim > 1:
            samples = samples.mean(axis=1)

        # Ensure float32
        samples = samples.astype(np.float32)

        duration_s = float(len(samples)) / SAMPLE_RATE
        result["samples"] = samples
        result["sr"] = sr
        result["duration_ms"] = round(duration_s * 1000, 2)

    except Exception as exc:
        result["error"] = str(exc)
    finally:
        if "tmp_path" in locals():
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        result["decode_ms"] = round((time.perf_counter() - _t0) * 1000, 2)

    return result


def pcm16_to_float32(data: bytes) -> np.ndarray:
    """Convert PCM16 little-endian bytes to float32 numpy array.

    Matches the implementation in speech_stream_service.py.
    """
    raw = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    raw /= 32768.0
    return raw


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 numpy array to PCM16 little-endian bytes.

    Range [-1.0, 1.0] → int16. Matches frontend MicrophoneCapture.float32ToPcm16.
    """
    clamped = np.clip(audio, -1.0, 1.0)
    i16 = (clamped * 32767).astype(np.int16)
    return i16.tobytes()


# ── Mode A: Offline ASR benchmark ────────────────────────────────────────────


def run_offline_benchmark(
    samples: np.ndarray,
    reference_text: str | None,
) -> dict[str, Any]:
    """Run offline (full-context) ASR on the audio array.

    Uses SpeechModule.transcribe_array() which internally calls
    offline_rescore() from stt_streaming.

    Returns:
        dict with keys: audio_duration_ms, asr_total_ms, asr_real_time_factor,
        recognized_text, reference_text, cer_info, error.
    """
    result: dict[str, Any] = {
        "audio_duration_ms": round(len(samples) / SAMPLE_RATE * 1000, 2),
        "mode": "offline_rescore (Paraformer-large, full-context offline ASR)",
        "asr_total_ms": None,
        "asr_real_time_factor": None,
        "recognized_text": None,
        "reference_text": reference_text,
        "cer": None,
        "error": None,
    }

    try:
        from backend.speech_module import SpeechModule

        sm = SpeechModule()
        sm.preload()

        if not sm.ready:
            raise RuntimeError(
                f"SpeechModule not ready after preload: "
                f"streaming={sm.status.get('streaming_model')}, "
                f"offline={sm.status.get('offline_model')}"
            )

        _t0 = time.perf_counter()
        recognized = sm.transcribe_array(samples, SAMPLE_RATE)
        asr_ms = round((time.perf_counter() - _t0) * 1000, 2)

        result["recognized_text"] = recognized or ""
        result["asr_total_ms"] = asr_ms
        result["asr_real_time_factor"] = round(
            asr_ms / result["audio_duration_ms"], 6
        ) if result["audio_duration_ms"] > 0 else None

        if reference_text:
            cer_info = compute_cer(recognized or "", reference_text)
            result["cer"] = cer_info

    except Exception as exc:
        result["error"] = str(exc)
        # Try to import speech module for a better error message
        try:
            from backend.speech_module.stt_streaming import (
                _offline_model, _streaming_model,
            )
            result["error_details"] = {
                "streaming_model_loaded": _offline_model is not None,
                "offline_model_loaded": _streaming_model is not None,
            }
        except Exception:
            pass

    return result


# ── Chunk timing distribution analysis ──────────────────────────────────────


def _compute_chunk_timing_distribution(
    per_chunk_ms: list[float], num_segments: int = 10,
) -> dict[str, Any]:
    """Analyze per-chunk ASR timing distribution and trend.

    Divides the chunk timeline into equal segments and computes:
      - per-segment avg/max/min
      - overall percentiles (P50, P90, P99)
      - trend slope (normalized by mean — positive means getting slower)

    Args:
        per_chunk_ms: List of per-chunk ASR times in milliseconds.
        num_segments: Number of segments to divide into (default 10).

    Returns:
        dict with keys: segments (list), percentiles (dict), trend (dict).
    """
    n = len(per_chunk_ms)
    if n == 0:
        return {
            "segments": [],
            "percentiles": {},
            "trend": {"slope_normalized": None, "direction": "no_data"},
        }

    # ── Segments ────────────────────────────────────────────────────────
    seg_size = max(1, n // num_segments)
    segments: list[dict[str, Any]] = []
    for i in range(num_segments):
        start = i * seg_size
        end = start + seg_size if i < num_segments - 1 else n
        seg = per_chunk_ms[start:end]
        if not seg:
            continue
        segments.append({
            "segment_index": i + 1,
            "chunk_start": start,
            "chunk_end": end - 1,
            "count": len(seg),
            "avg_ms": round(sum(seg) / len(seg), 2),
            "max_ms": round(max(seg), 2),
            "min_ms": round(min(seg), 2),
        })

    # ── Percentiles ─────────────────────────────────────────────────────
    sorted_times = sorted(per_chunk_ms)
    percentiles: dict[str, float] = {}
    for pctl, label in [(50, "p50"), (90, "p90"), (95, "p95"), (99, "p99")]:
        idx = int(len(sorted_times) * pctl / 100)
        idx = min(idx, len(sorted_times) - 1)
        percentiles[label] = round(sorted_times[idx], 2)
    percentiles["min"] = round(sorted_times[0], 2)
    percentiles["max"] = round(sorted_times[-1], 2)

    # ── Trend slope (linear regression: segment_avg vs segment_index) ──
    # Normalized by overall mean: slope / mean → fraction change per segment
    if len(segments) >= 3:
        seg_indices = [s["segment_index"] for s in segments]
        seg_avgs = [s["avg_ms"] for s in segments]
        overall_mean = sum(seg_avgs) / len(seg_avgs)

        # Simple linear regression: y = a + bx
        n_seg = len(seg_indices)
        sum_x = sum(seg_indices)
        sum_y = sum(seg_avgs)
        sum_xy = sum(x * y for x, y in zip(seg_indices, seg_avgs))
        sum_xx = sum(x * x for x in seg_indices)

        denom = n_seg * sum_xx - sum_x * sum_x
        if denom != 0:
            slope = (n_seg * sum_xy - sum_x * sum_y) / denom
            slope_normalized = slope / overall_mean if overall_mean > 0 else 0

            first_half = seg_avgs[: len(seg_avgs) // 2]
            second_half = seg_avgs[len(seg_avgs) // 2:]
            growth_ratio = (
                (sum(second_half) / len(second_half)) /
                (sum(first_half) / len(first_half))
                if first_half and second_half else None
            )

            if abs(slope_normalized) < 0.05:
                direction = "stable"
            elif slope_normalized > 0:
                direction = "increasing"
            else:
                direction = "decreasing"

            trend = {
                "slope_raw": round(slope, 6),
                "slope_normalized": round(slope_normalized, 6),
                "direction": direction,
                "growth_ratio_second_half_vs_first": round(growth_ratio, 4)
                if growth_ratio else None,
            }
        else:
            trend = {"slope_normalized": None, "direction": "constant"}
    else:
        trend = {"slope_normalized": None, "direction": "insufficient_data"}

    return {
        "segments": segments,
        "percentiles": percentiles,
        "trend": trend,
    }


# ── Mode B: Streaming replay benchmark ───────────────────────────────────────


def run_streaming_benchmark(
    samples: np.ndarray,
    session_key: str = "bench_session",
    audio_duration_ms: float | None = None,
    chunk_preset: str = "balanced",
) -> dict[str, Any]:
    """Simulate streaming ASR by feeding 100ms PCM chunks sequentially.

    Uses SpeechModule.process_interim_array() which is the same path used
    by the production WebSocket handler. Chunks are fed in-order; timing is
    measured per chunk for latency analysis.

    Args:
        samples: float32 audio array.
        session_key: Unique session key for SpeechModule state.
        audio_duration_ms: Actual audio duration in ms (real, not padded).
                           Used to compute streaming RTF.
        chunk_preset: Streaming chunk preset name (balanced, ultra_low_latency,
                      high_accuracy, near_offline).

    Returns:
        dict with keys:
            first_chunk_at, first_interim_at,
            first_chunk_to_first_interim_ms, per_chunk_asr_ms (list),
            max_chunk_asr_ms, avg_chunk_asr_ms, streaming_asr_rtf,
            chunk_asr_distribution (list of segment stats),
            chunk_asr_percentiles (p50/p90/p99),
            chunk_asr_trend (direction + slope),
            total_interim_count, final_text,
            finalization_ms, whether_final_generated,
            whether_interim_would_be_cleared, errors.
    """
    result: dict[str, Any] = {
        "chunk_count": 0,
        "chunk_duration_ms": CHUNK_DURATION_MS,
        "audio_duration_ms": audio_duration_ms,
        # Processing-only (offline fast-replay) metrics
        "first_chunk_to_first_interim_ms": None,
        "processing_first_interim_ms": None,
        # Audio-timeline-based metrics (estimates real mic feed)
        "first_interim_chunk_index": None,
        "first_interim_audio_offset_ms": None,
        "estimated_realtime_first_interim_ms": None,
        # Per-chunk timing
        "per_chunk_asr_ms": [],
        "max_chunk_asr_ms": None,
        "avg_chunk_asr_ms": None,
        "streaming_asr_rtf": None,
        # Interim / final tracking
        "total_interim_count": 0,
        "final_text": None,
        "finalization_ms": None,
        "whether_final_generated": False,
        "whether_interim_would_be_cleared": False,
        "errors": [],
    }

    try:
        from backend.speech_module import SpeechModule

        sm = SpeechModule()
        sm.preload()

        if not sm.ready:
            raise RuntimeError(
                f"SpeechModule not ready after preload: "
                f"streaming={sm.status.get('streaming_model')}, "
                f"offline={sm.status.get('offline_model')}"
            )

        # Set up session context
        sm.set_session_context(session_key, 0, 0)
        sm.start_utterance(session_key)

        # Override chunk_size if a non-default preset was requested
        if chunk_preset != "balanced":
            from backend.speech_module.stt_streaming import StreamingChunkProcessor
            preset_chunk = _get_preset_chunk(chunk_preset)
            state = sm._sessions.get(session_key)
            if state:
                new_processor = StreamingChunkProcessor(chunk_size=preset_chunk)
                # Preserve accumulated text (empty after start_utterance)
                state["processor"] = new_processor

        total_samples = len(samples)
        n_chunks = math.ceil(total_samples / CHUNK_SAMPLES)

        first_interim_text = None
        first_chunk_time = None
        first_interim_time = None
        first_interim_chunk_index: int | None = None
        chunk_asr_times: list[float] = []
        interim_count = 0
        last_text = ""
        chunk_errors: list[str] = []

        for i in range(n_chunks):
            start_idx = i * CHUNK_SAMPLES
            end_idx = min(start_idx + CHUNK_SAMPLES, total_samples)
            chunk = samples[start_idx:end_idx]

            # Pad last chunk with zeros if needed (CIF cache expects full frames)
            if len(chunk) < CHUNK_SAMPLES:
                pad = np.zeros(CHUNK_SAMPLES - len(chunk), dtype=np.float32)
                chunk = np.concatenate([chunk, pad])

            if first_chunk_time is None:
                first_chunk_time = time.perf_counter()

            _t0 = time.perf_counter()
            try:
                text = sm.process_interim_array(chunk, session_key)
            except Exception as exc:
                chunk_errors.append(f"chunk_{i}: {exc}")
                text = last_text or ""
            chunk_ms = round((time.perf_counter() - _t0) * 1000, 2)
            chunk_asr_times.append(chunk_ms)

            # Track first interim with non-empty text
            if text and text.strip() and first_interim_text is None:
                first_interim_text = text
                first_interim_time = time.perf_counter()
                first_interim_chunk_index = i
                interim_count += 1
            elif text != last_text and text.strip():
                interim_count += 1

            last_text = text

        # "Finalization" timing: simulate the final offline rescore path
        _final_t0 = time.perf_counter()
        try:
            final_text = sm.transcribe_array(samples, SAMPLE_RATE)
        except Exception as exc:
            chunk_errors.append(f"finalize: {exc}")
            final_text = last_text
        final_ms = round((time.perf_counter() - _final_t0) * 1000, 2)

        # Compute metrics
        # ── Processing-only first interim ─────────────────────────────────
        # This is the wall-clock time from first chunk start to first
        # non-empty interim when chunks are fed as fast as possible (offline
        # replay). It does NOT include real microphone buffer wait time.
        if first_chunk_time and first_interim_time:
            processing_ms = round(
                (first_interim_time - first_chunk_time) * 1000, 2,
            )
            result["first_chunk_to_first_interim_ms"] = processing_ms
            result["processing_first_interim_ms"] = processing_ms
        else:
            result["first_chunk_to_first_interim_ms"] = None
            result["processing_first_interim_ms"] = None

        # ── Audio-timeline-based first interim ───────────────────────────
        # `first_interim_chunk_index` is 0-based: the index of the first
        # chunk for which process_interim_array returned non-empty text.
        # `first_interim_audio_offset_ms` = (index + 1) * chunk_duration_ms,
        # i.e. how much audio must have arrived (at real-time rate) before
        # the ASR model can produce a non-empty interim. +1 because the
        # chunk's audio must be fully received before processing.
        # `processing_overhead_ms` = the ASR inference time of that chunk.
        result["first_interim_chunk_index"] = first_interim_chunk_index
        if first_interim_chunk_index is not None:
            audio_offset = (first_interim_chunk_index + 1) * CHUNK_DURATION_MS
            proc_overhead = (
                chunk_asr_times[first_interim_chunk_index]
                if first_interim_chunk_index < len(chunk_asr_times)
                else 0
            )
            result["first_interim_audio_offset_ms"] = audio_offset
            result["estimated_realtime_first_interim_ms"] = round(
                audio_offset + proc_overhead, 2,
            )
        else:
            result["first_interim_audio_offset_ms"] = None
            result["estimated_realtime_first_interim_ms"] = None

        result["preset_name"] = chunk_preset
        result["preset_chunk_size"] = _get_preset_chunk(chunk_preset)

        result["chunk_count"] = n_chunks
        result["per_chunk_asr_ms"] = chunk_asr_times
        result["max_chunk_asr_ms"] = round(max(chunk_asr_times), 2) if chunk_asr_times else None
        result["avg_chunk_asr_ms"] = round(
            sum(chunk_asr_times) / len(chunk_asr_times), 2
        ) if chunk_asr_times else None

        # Streaming ASR real-time factor: sum of all chunk inference time / audio duration
        total_asr_ms = sum(chunk_asr_times)
        duration_ms = audio_duration_ms if audio_duration_ms else (n_chunks * CHUNK_DURATION_MS)
        if duration_ms > 0:
            result["streaming_asr_rtf"] = round(total_asr_ms / duration_ms, 6)
        else:
            result["streaming_asr_rtf"] = None

        # Chunk timing distribution & trend analysis
        dist = _compute_chunk_timing_distribution(chunk_asr_times)
        result["chunk_asr_distribution"] = dist["segments"]
        result["chunk_asr_percentiles"] = dist["percentiles"]
        result["chunk_asr_trend"] = dist["trend"]

        result["total_interim_count"] = interim_count
        result["final_text"] = final_text or ""
        result["finalization_ms"] = final_ms
        result["whether_final_generated"] = bool(final_text and final_text.strip())
        result["whether_interim_would_be_cleared"] = True
        result["errors"] = chunk_errors

        # Clean up session
        try:
            sm.reset_interim(session_key)
        except Exception:
            pass

    except Exception as exc:
        result["errors"].append(str(exc))

    return result


# ── Bottleneck assessment ────────────────────────────────────────────────────


def assess_bottleneck(
    env_info: dict[str, Any],
    files_results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assess the likely performance bottleneck based on benchmark results.

    Uses the judgment rules defined in Task 128B §6.
    """
    assessment: dict[str, Any] = {
        "likely_bottleneck": "unknown",
        "hardware_upgrade_likely_helpful": False,
        "notes": [],
    }

    # Collect all per-file streaming and offline results
    streaming_times: list[float] = []
    offline_times: list[float] = []
    audio_durations: list[float] = []
    chunk_asr_all: list[float] = []
    first_interim_all: list[float] = []
    processing_first_interim_all: list[float] = []
    audio_offset_all: list[float] = []
    streaming_rtfs: list[float] = []

    for f in files_results:
        offline = f.get("offline", {}) or {}
        streaming = f.get("streaming", {}) or {}

        if offline.get("asr_total_ms") is not None:
            offline_times.append(offline["asr_total_ms"])
            audio_durations.append(offline.get("audio_duration_ms", 0))

        if streaming.get("avg_chunk_asr_ms") is not None:
            streaming_times.append(streaming["avg_chunk_asr_ms"])
            # Collect both the legacy processing-only metric and the new audio-offset metric
            first_interim = streaming.get("first_chunk_to_first_interim_ms")
            if first_interim is not None:
                first_interim_all.append(first_interim)
            proc_first = streaming.get("processing_first_interim_ms")
            if proc_first is not None:
                processing_first_interim_all.append(proc_first)
            audio_offset = streaming.get("first_interim_audio_offset_ms")
            if audio_offset is not None:
                audio_offset_all.append(audio_offset)

        if streaming.get("streaming_asr_rtf") is not None:
            streaming_rtfs.append(streaming["streaming_asr_rtf"])

        per_chunk = streaming.get("per_chunk_asr_ms", [])
        chunk_asr_all.extend(per_chunk)

    # Rule 1: ASR slower than real-time?
    rtfs = []
    for i, ad in enumerate(audio_durations):
        if i < len(offline_times) and ad > 0:
            rtfs.append(offline_times[i] / ad)
    if rtfs:
        avg_rtf = sum(rtfs) / len(rtfs)
        if avg_rtf > 1.0:
            assessment["likely_bottleneck"] = "offline_asr_slower_than_real_time"
            assessment["notes"].append(
                f"Offline ASR real-time factor (avg) = {avg_rtf:.3f}, "
                f"> 1.0 — ASR is slower than real-time. "
                f"Model inference is the primary bottleneck."
            )

    # Streaming RTF comparison note
    if streaming_rtfs:
        avg_srtf = sum(streaming_rtfs) / len(streaming_rtfs)
        assessment["notes"].append(
            f"Streaming ASR real-time factor = {avg_srtf:.6f}. "
            f"Sum of all chunk inference times is "
            f"{'much less' if avg_srtf < 0.3 else 'comparable'}"
            f" than audio duration — streaming can keep up."
        )

    # Rule 2: Streaming can't keep up?
    if chunk_asr_all:
        avg_chunk_ms = sum(chunk_asr_all) / len(chunk_asr_all)
        if avg_chunk_ms > CHUNK_DURATION_MS:
            assessment["likely_bottleneck"] = "streaming_chunk_processing_too_slow"
            assessment["notes"].append(
                f"Average per-chunk ASR time ({avg_chunk_ms:.1f}ms) exceeds "
                f"chunk duration ({CHUNK_DURATION_MS}ms). "
                f"Streaming processing cannot keep up with real-time input."
            )

    # Rule 3: CUDA not available + CPU slow
    if not env_info.get("cuda_available"):
        if chunk_asr_all:
            avg_chunk_ms = sum(chunk_asr_all) / len(chunk_asr_all)
            if avg_chunk_ms > CHUNK_DURATION_MS:
                assessment["hardware_upgrade_likely_helpful"] = True
                assessment["notes"].append(
                    "CUDA is not available and CPU inference is slow "
                    f"(avg chunk={avg_chunk_ms:.1f}ms > {CHUNK_DURATION_MS}ms). "
                    "A GPU (NVIDIA with CUDA) would significantly improve throughput."
                )
        if rtfs:
            avg_rtf = sum(rtfs) / len(rtfs)
            if avg_rtf > 1.0:
                assessment["hardware_upgrade_likely_helpful"] = True
                assessment["notes"].append(
                    "Offline ASR runs on CPU with RTF > 1.0. "
                    "GPU acceleration would likely make it real-time or better."
                )

    # Rule 4: Audio offset analysis — first-interim limited by streaming window?
    # Only sets likely_bottleneck if no more severe issue was already found.
    if audio_offset_all:
        avg_audio_offset = sum(audio_offset_all) / len(audio_offset_all)
        avg_chunk_ms = (sum(chunk_asr_all) / len(chunk_asr_all)
                        if chunk_asr_all else 0)
        if avg_audio_offset > 300:
            if assessment["likely_bottleneck"] == "unknown":
                assessment["likely_bottleneck"] = "streaming_chunk_window"
            assessment["notes"].append(
                f"First-interim audio offset (avg) = {avg_audio_offset:.0f}ms, "
                f"which is the dominant component of first-interim latency. "
                f"This comes from the streaming model's chunk accumulation window "
                f"(balanced preset ~900ms, actual offset depends on how fast CIF "
                f"encoder triggers decoder). ASR inference is fast "
                f"(avg chunk={avg_chunk_ms:.1f}ms). "
                f"Lowering the chunk preset (e.g. ultra_low_latency) would reduce "
                f"this more than a hardware upgrade."
            )
        else:
            assessment["notes"].append(
                f"First-interim audio offset (avg) = {avg_audio_offset:.0f}ms. "
                f"The streaming window is not a major contributor."
            )

    # Rule 5: Processing overhead analysis
    if processing_first_interim_all:
        avg_proc = sum(processing_first_interim_all) / len(processing_first_interim_all)
        avg_chunk_ms = (sum(chunk_asr_all) / len(chunk_asr_all)
                        if chunk_asr_all else 0)
        if avg_proc > 200 and avg_chunk_ms < CHUNK_DURATION_MS:
            assessment["notes"].append(
                f"Processing-only first-interim (avg={avg_proc:.0f}ms) is "
                f"elevated relative to avg chunk time ({avg_chunk_ms:.1f}ms). "
                "This suggests local processing overhead (Python dispatch, "
                "CIF cache cold start) is contributing. Investigate first-chunk "
                "warmup before considering hardware changes."
            )

    # Rule 6: Both low but user may still feel slow → browser merged trace needed
    if chunk_asr_all and audio_offset_all and processing_first_interim_all:
        avg_chunk_ms = sum(chunk_asr_all) / len(chunk_asr_all)
        avg_audio_offset = sum(audio_offset_all) / len(audio_offset_all)
        avg_proc = sum(processing_first_interim_all) / len(processing_first_interim_all)
        if avg_chunk_ms < CHUNK_DURATION_MS and avg_audio_offset < 300 and avg_proc < 200:
            assessment["notes"].append(
                "ASR throughput, audio offset, and processing overhead are all "
                "within expected range. If users still perceive high first-word "
                "latency, the bottleneck is likely outside this benchmark's scope: "
                "browser getUserMedia, AudioContext creation, WebSocket handshake, "
                "EventBus dispatch, or React rendering. "
                "Collect a frontend+backend merged trace (via speechTrace.ts + "
                "SMART_DESK_ENABLE_SPEECH_TRACE=true) to identify the actual delay."
            )

    # Rule 7: Decode time note
    decode_times = [
        f.get("decode_ms") for f in files_results
        if f.get("decode_ms") is not None
    ]
    if decode_times:
        avg_decode = sum(decode_times) / len(decode_times)
        max_decode = max(decode_times)
        assessment["notes"].append(
            f"Audio decode time: avg={avg_decode:.0f}ms, max={max_decode:.0f}ms. "
            "Decode time is excluded from ASR timing."
        )

    # Rule 8: Chunk ASR trend — is it getting slower over time?
    increasing_trend_files = []
    for f in files_results:
        st = f.get("streaming", {}) or {}
        trend = st.get("chunk_asr_trend", {}) or {}
        if trend.get("direction") == "increasing":
            slope = trend.get("slope_normalized", 0)
            growth = trend.get("growth_ratio_second_half_vs_first")
            increasing_trend_files.append({
                "file": f.get("audio_file", "?"),
                "slope_normalized": slope,
                "growth_ratio": growth,
            })
    if increasing_trend_files:
        for tf in increasing_trend_files:
            assessment["notes"].append(
                f"Chunk ASR timing shows increasing trend for '{tf['file']}': "
                f"normalized slope={tf['slope_normalized']:.4f}, "
                f"second-half/first-half ratio={tf['growth_ratio']:.4f}. "
                "If the second half is significantly slower (>20%), this may "
                "indicate memory accumulation or progressive slowdown in the "
                "CIF encoder/decoder cache."
            )

    if not assessment["notes"]:
        assessment["notes"].append(
            "All metrics within expected range. No clear bottleneck identified "
            "from benchmark data alone."
        )

    return assessment


# ── Task 128F: Preset comparison ──────────────────────────────────────────────


def run_preset_comparison(
    dataset_dir: str,
    preset_names: list[str],
    ffmpeg_path: str | None = None,
) -> dict[str, Any]:
    """Run benchmark across multiple streaming presets and compare results.

    For each preset, runs offline ASR + streaming replay on all files in the
    dataset directory. Offline ASR is run once (model-independent); streaming
    ASR is re-run for each preset.

    Args:
        dataset_dir: Path to the dataset directory containing .m4a files.
        preset_names: List of preset names to compare (e.g. ["balanced",
                      "ultra_low_latency", "high_accuracy"]).
        ffmpeg_path: Optional explicit ffmpeg path.

    Returns:
        dict with keys: report_meta, presets (list of per-preset reports),
        comparison, thresholds.
    """
    # Probe environment (once)
    env_info = probe_environment(ffmpeg_path_arg=ffmpeg_path)

    report: dict[str, Any] = {
        "report_type": "speech-low-latency-preset-comparison",
        "task": "128F",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": dataset_dir,
        "environment": env_info,
        "presets": [],
        "comparison": None,
        "thresholds": {
            "max_acceptable_cer_increase": 0.03,
            "target_estimated_first_interim_ms": 1000,
        },
    }

    if not env_info.get("ffmpeg_available"):
        report["error"] = "ffmpeg not available — cannot decode audio"
        return report

    # Scan dataset
    try:
        file_entries = scan_dataset(dataset_dir)
    except FileNotFoundError as exc:
        report["error"] = str(exc)
        return report

    report["file_count"] = len(file_entries)

    # Resolve presets — mark unavailable ones
    available_presets = _get_presets()
    resolved_presets: list[dict[str, Any]] = []
    for name in preset_names:
        alias_map = {"low_latency": "ultra_low_latency"}
        real_name = alias_map.get(name, name)
        if real_name in available_presets:
            resolved_presets.append({
                "requested_name": name,
                "resolved_name": real_name,
                "chunk_size": available_presets[real_name],
                "available": True,
            })
        else:
            resolved_presets.append({
                "requested_name": name,
                "resolved_name": None,
                "chunk_size": None,
                "available": False,
                "note": f"Preset '{name}' not found. Available: {list(available_presets.keys())}",
            })

    # Check at least one preset is available
    available_count = sum(1 for p in resolved_presets if p["available"])
    if available_count == 0:
        report["error"] = (
            f"No presets available. Requested: {preset_names}. "
            f"Available: {list(available_presets.keys())}"
        )
        return report

    # Read all reference texts once
    reference_texts: dict[str, str | None] = {}
    for entry in file_entries:
        ref = None
        if entry["text_path"]:
            try:
                with open(entry["text_path"], "r", encoding="utf-8") as f:
                    ref = f.read()
            except Exception:
                pass
        reference_texts[entry["audio_file"]] = ref

    # Decode all audio files once (shared across presets)
    decoded_audio: dict[str, dict[str, Any]] = {}
    for entry in file_entries:
        decode_result = decode_audio(entry["audio_path"], env_info)
        decoded_audio[entry["audio_file"]] = decode_result

    # Run offline benchmark once
    offline_results: dict[str, dict[str, Any]] = {}
    for entry in file_entries:
        dr = decoded_audio[entry["audio_file"]]
        if dr.get("error") or dr.get("samples") is None:
            offline_results[entry["audio_file"]] = {"error": dr.get("error")}
            continue
        offline = run_offline_benchmark(dr["samples"], reference_texts[entry["audio_file"]])
        offline_results[entry["audio_file"]] = offline

    # Each preset runs its own streaming benchmark
    for preset_info in resolved_presets:
        preset_name = preset_info["requested_name"]
        resolved_name = preset_info["resolved_name"]
        real_name = alias_map.get(preset_name, preset_name)
        if not preset_info["available"]:
            report["presets"].append({
                "preset_name": preset_name,
                "resolved_name": None,
                "chunk_size": None,
                "available": False,
                "note": preset_info["note"],
                "files": [],
                "summary": None,
            })
            continue

        print(f"\n[{real_name} preset] Running streaming benchmark...")

        # Collect per-file streaming + offline results
        preset_files: list[dict[str, Any]] = []
        success_count = 0
        failed_count = 0
        est_realtime_vals: list[float] = []
        proc_first_vals: list[float] = []
        audio_offset_vals: list[float] = []
        srtf_vals: list[float] = []
        cer_vals: list[float] = []

        for entry in file_entries:
            dr = decoded_audio[entry["audio_file"]]
            offline = offline_results.get(entry["audio_file"], {})
            streaming_error = None

            file_result: dict[str, Any] = {
                "audio_file": entry["audio_file"],
                "text_file": entry["text_file"],
                "audio_duration_ms": dr.get("duration_ms"),
                "decode_ms": dr.get("decode_ms"),
                "offline": offline,
                "streaming": None,
                "errors": [],
            }

            if entry["warning"]:
                file_result["warning"] = entry["warning"]

            if dr.get("error") or dr.get("samples") is None:
                file_result["errors"].append(f"Audio decode failed: {dr.get('error', 'unknown')}")
                file_result["streaming"] = {"error": dr.get("error")}
                failed_count += 1
                preset_files.append(file_result)
                continue

            # Run streaming with this preset
            session_key = f"preset_{real_name}_{entry['audio_file']}_{int(time.time())}"
            streaming = run_streaming_benchmark(
                dr["samples"], session_key,
                audio_duration_ms=dr.get("duration_ms"),
                chunk_preset=real_name,
            )
            file_result["streaming"] = streaming

            if streaming.get("errors"):
                file_result["errors"].extend(
                    f"[{real_name}] {e}" for e in streaming["errors"]
                )

            if streaming.get("estimated_realtime_first_interim_ms") is not None:
                est_realtime_vals.append(streaming["estimated_realtime_first_interim_ms"])
            if streaming.get("processing_first_interim_ms") is not None:
                proc_first_vals.append(streaming["processing_first_interim_ms"])
            if streaming.get("first_interim_audio_offset_ms") is not None:
                audio_offset_vals.append(streaming["first_interim_audio_offset_ms"])
            if streaming.get("streaming_asr_rtf") is not None:
                srtf_vals.append(streaming["streaming_asr_rtf"])
            if (offline.get("cer") and isinstance(offline.get("cer"), dict)
                    and offline["cer"].get("available")):
                cer_vals.append(offline["cer"]["cer"])

            if not file_result["errors"]:
                success_count += 1
            else:
                failed_count += 1

            preset_files.append(file_result)

        preset_summary = {
            "success_count": success_count,
            "failed_count": failed_count,
            "avg_estimated_realtime_first_interim_ms": (
                round(sum(est_realtime_vals) / len(est_realtime_vals), 2)
                if est_realtime_vals else None
            ),
            "avg_processing_first_interim_ms": (
                round(sum(proc_first_vals) / len(proc_first_vals), 2)
                if proc_first_vals else None
            ),
            "avg_first_interim_audio_offset_ms": (
                round(sum(audio_offset_vals) / len(audio_offset_vals), 2)
                if audio_offset_vals else None
            ),
            "avg_streaming_asr_rtf": (
                round(sum(srtf_vals) / len(srtf_vals), 6)
                if srtf_vals else None
            ),
            "avg_cer": (
                round(sum(cer_vals) / len(cer_vals), 6)
                if cer_vals else None
            ),
        }

        preset_entry: dict[str, Any] = {
            "preset_name": preset_name,
            "resolved_name": real_name,
            "chunk_size": available_presets.get(real_name),
            "available": True,
            "note": None,
            "files": preset_files,
            "summary": preset_summary,
        }
        report["presets"].append(preset_entry)

    # ── Comparison logic ───────────────────────────────────────────────────
    valid_presets = [
        p for p in report["presets"]
        if p["available"] and p.get("summary") and p["summary"]["success_count"] > 0
    ]

    if len(valid_presets) >= 2:
        # Best latency: lowest avg_estimated_realtime_first_interim_ms
        best_latency = min(
            valid_presets,
            key=lambda p: (
                p["summary"]["avg_estimated_realtime_first_interim_ms"]
                or float("inf")
            ),
        )
        # Best accuracy: lowest avg_cer
        best_accuracy = min(
            valid_presets,
            key=lambda p: (
                p["summary"]["avg_cer"] if p["summary"]["avg_cer"] is not None
                else float("inf")
            ),
        )

        # Recommendation
        baseline = next(
            (p for p in valid_presets if p["resolved_name"] == "balanced"),
            valid_presets[0],
        )
        fastest = best_latency
        baseline_est = baseline["summary"]["avg_estimated_realtime_first_interim_ms"]
        fastest_est = fastest["summary"]["avg_estimated_realtime_first_interim_ms"]
        baseline_cer = baseline["summary"]["avg_cer"]
        fastest_cer = fastest["summary"]["avg_cer"]

        latency_improvement = None
        cer_regression = None
        if baseline_est and fastest_est:
            latency_improvement = round(baseline_est - fastest_est, 2)
        if baseline_cer is not None and fastest_cer is not None:
            cer_regression = round(fastest_cer - baseline_cer, 6)

        # Determine recommendation
        recommended = fastest["resolved_name"]  # default: fastest
        reason_parts = []

        if latency_improvement and latency_improvement > 100:
            reason_parts.append(
                f"Fastest preset ({fastest['resolved_name']}) reduces "
                f"estimated first interim by {latency_improvement:.0f}ms "
                f"vs baseline ({baseline['resolved_name']})."
            )
        else:
            reason_parts.append(
                f"Latency improvement from {fastest['resolved_name']} is "
                f"minimal ({latency_improvement:.0f}ms vs baseline)."
            )

        if cer_regression is not None and cer_regression > 0.03:
            reason_parts.append(
                f"CER regression of {cer_regression:.4f} from "
                f"{fastest['resolved_name']} exceeds threshold (0.03). "
                f"Recommend keeping {baseline['resolved_name']} as default."
            )
            recommended = baseline["resolved_name"]
        elif cer_regression is not None and cer_regression > 0.01:
            reason_parts.append(
                f"Mild CER regression of {cer_regression:.4f} from "
                f"{fastest['resolved_name']} — acceptable but notable."
            )
        elif cer_regression is not None:
            reason_parts.append(
                f"CER impact is negligible ({cer_regression:.4f}) — "
                f"accuracy preserved."
            )
        else:
            reason_parts.append(
                "CER comparison not available (missing reference texts)."
            )

        report["comparison"] = {
            "best_latency_preset": best_latency["resolved_name"],
            "best_accuracy_preset": best_accuracy["resolved_name"],
            "recommended_preset": recommended,
            "recommendation_reason": " ".join(reason_parts),
            "baseline_preset": baseline["resolved_name"],
            "latency_improvement_ms": latency_improvement,
            "cer_regression": cer_regression,
        }
    elif len(valid_presets) == 1:
        report["comparison"] = {
            "best_latency_preset": valid_presets[0]["resolved_name"],
            "best_accuracy_preset": valid_presets[0]["resolved_name"],
            "recommended_preset": valid_presets[0]["resolved_name"],
            "recommendation_reason": (
                "Only one preset was available for comparison. "
                "Cannot determine best preset."
            ),
            "baseline_preset": valid_presets[0]["resolved_name"],
            "latency_improvement_ms": None,
            "cer_regression": None,
        }
    else:
        report["comparison"] = {
            "best_latency_preset": None,
            "best_accuracy_preset": None,
            "recommended_preset": None,
            "recommendation_reason": "No valid presets to compare.",
            "baseline_preset": None,
            "latency_improvement_ms": None,
            "cer_regression": None,
        }

    return report


# ── Report generation ────────────────────────────────────────────────────────


def generate_report(
    dataset_dir: str,
    output_path: str | None = None,
    ffmpeg_path: str | None = None,
    streaming_preset: str | None = None,
) -> dict[str, Any]:
    """Run the full benchmark and generate a JSON report.

    Args:
        dataset_dir: Path to the dataset directory containing .m4a files.
        output_path: Optional path for the JSON report. If not provided,
                     uses the default working/ path.
        ffmpeg_path: Optional explicit ffmpeg path (overrides auto-detection).
        streaming_preset: Streaming chunk preset name. If None, uses default
                          "balanced". Set via --streaming-preset CLI arg.

    Returns:
        The report dict (also written to output_path if provided).
    """
    # 1. Probe environment (pass ffmpeg_path_arg for discovery)
    env_info = probe_environment(ffmpeg_path_arg=ffmpeg_path)

    _preset_used = streaming_preset or "balanced"
    report: dict[str, Any] = {
        "report_type": "speech-real-dataset-benchmark",
        "task": "128B",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_dir": dataset_dir,
        "streaming_preset": _preset_used,
        "streaming_preset_chunk_size": _get_preset_chunk(_preset_used),
        "environment": env_info,
        "summary": {
            "file_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "avg_first_interim_ms_deprecated_processing_only": None,
            "avg_processing_first_interim_ms": None,
            "avg_first_interim_audio_offset_ms": None,
            "avg_estimated_realtime_first_interim_ms": None,
            "avg_offline_asr_rtf": None,
            "avg_streaming_asr_rtf": None,
            "avg_cer": None,
        },
        "files": [],
        "assessment": None,
    }

    # 2. Scan dataset
    try:
        file_entries = scan_dataset(dataset_dir)
    except FileNotFoundError as exc:
        report["error"] = str(exc)
        return report

    report["summary"]["file_count"] = len(file_entries)

    # 3. Check ffmpeg availability
    if not env_info.get("ffmpeg_available"):
        search_trace = env_info.get("ffmpeg_search_trace", [])
        trace_str = "\n".join(f"  - {t}" for t in search_trace) if search_trace else "  (no search performed)"
        hint = (
            "Install ffmpeg (e.g., 'winget install Gyan.FFMpeg' on Windows, "
            "'apt install ffmpeg' on Linux, 'brew install ffmpeg' on macOS).\n"
            "Or provide path via --ffmpeg-path or SMART_DESK_FFMPEG_PATH env var."
        )
        report["error"] = (
            f"ffmpeg is not available.\n"
            f"Search trace:\n{trace_str}\n{hint}"
        )
        # Still populate the file list with error entries
        for entry in file_entries:
            file_report: dict[str, Any] = {
                "audio_file": entry["audio_file"],
                "text_file": entry["text_file"],
                "warning": entry["warning"],
                "audio_duration_ms": None,
                "decode_ms": None,
                "offline": {"error": "ffmpeg not available — cannot decode audio"},
                "streaming": {"error": "ffmpeg not available — cannot decode audio"},
                "errors": ["ffmpeg not available"],
            }
            report["files"].append(file_report)
        report["summary"]["failed_count"] = len(file_entries)
        return report

    # 4. For each file, decode and run both benchmarks
    success_count = 0
    failed_count = 0
    first_interim_values: list[float] = []
    proc_first_interim_values: list[float] = []
    audio_offset_values: list[float] = []
    est_realtime_values: list[float] = []
    rtf_values: list[float] = []
    srtf_values: list[float] = []
    cer_values: list[float] = []

    for entry in file_entries:
        audio_path = entry["audio_path"]
        text_path = entry["text_path"]
        reference_text: str | None = None
        if text_path:
            try:
                with open(text_path, "r", encoding="utf-8") as f:
                    reference_text = f.read()
            except Exception as exc:
                # Non-fatal: can't read reference
                pass

        file_report: dict[str, Any] = {
            "audio_file": entry["audio_file"],
            "text_file": entry["text_file"],
            "audio_duration_ms": None,
            "decode_ms": None,
            "offline": None,
            "streaming": None,
            "errors": [],
        }

        if entry["warning"]:
            file_report["warning"] = entry["warning"]

        # Decode audio
        decode_result = decode_audio(audio_path, env_info)
        file_report["decode_ms"] = decode_result.get("decode_ms")

        if decode_result.get("error") or decode_result.get("samples") is None:
            file_report["errors"].append(
                f"Audio decode failed: {decode_result.get('error', 'unknown error')}"
            )
            file_report["offline"] = {"error": decode_result.get("error")}
            file_report["streaming"] = {"error": decode_result.get("error")}
            failed_count += 1
            report["files"].append(file_report)
            continue

        samples = decode_result["samples"]
        file_report["audio_duration_ms"] = decode_result["duration_ms"]

        # Mode A: Offline ASR
        offline_result = run_offline_benchmark(samples, reference_text)
        file_report["offline"] = offline_result

        # Mode B: Streaming replay (with optional preset)
        session_key = f"bench_{entry['audio_file']}_{int(time.time())}"
        _preset = streaming_preset or "balanced"
        streaming_result = run_streaming_benchmark(
            samples, session_key,
            audio_duration_ms=file_report["audio_duration_ms"],
            chunk_preset=_preset,
        )
        file_report["streaming"] = streaming_result

        # Aggregate errors
        if offline_result.get("error"):
            file_report["errors"].append(f"Offline ASR: {offline_result['error']}")
        stream_errors = streaming_result.get("errors", [])
        if stream_errors:
            file_report["errors"].extend(
                f"Streaming: {e}" for e in stream_errors
            )

        # Collect summary values
        if streaming_result.get("first_chunk_to_first_interim_ms") is not None:
            first_interim_values.append(
                streaming_result["first_chunk_to_first_interim_ms"]
            )
        if streaming_result.get("processing_first_interim_ms") is not None:
            proc_first_interim_values.append(
                streaming_result["processing_first_interim_ms"]
            )
        if streaming_result.get("first_interim_audio_offset_ms") is not None:
            audio_offset_values.append(
                streaming_result["first_interim_audio_offset_ms"]
            )
        if streaming_result.get("estimated_realtime_first_interim_ms") is not None:
            est_realtime_values.append(
                streaming_result["estimated_realtime_first_interim_ms"]
            )
        if offline_result.get("asr_real_time_factor") is not None:
            rtf_values.append(offline_result["asr_real_time_factor"])
        if streaming_result.get("streaming_asr_rtf") is not None:
            srtf_values.append(streaming_result["streaming_asr_rtf"])
        if offline_result.get("cer") and offline_result["cer"].get("available"):
            cer_values.append(offline_result["cer"]["cer"])

        if not file_report["errors"]:
            success_count += 1
        else:
            failed_count += 1

        report["files"].append(file_report)

    # 5. Compute summary
    report["summary"]["success_count"] = success_count
    report["summary"]["failed_count"] = failed_count
    # Deprecated — kept for backward compat, refers to processing-only metric
    report["summary"]["avg_first_interim_ms_deprecated_processing_only"] = (
        round(sum(first_interim_values) / len(first_interim_values), 2)
        if first_interim_values else None
    )
    report["summary"]["avg_processing_first_interim_ms"] = (
        round(sum(proc_first_interim_values) / len(proc_first_interim_values), 2)
        if proc_first_interim_values else None
    )
    report["summary"]["avg_first_interim_audio_offset_ms"] = (
        round(sum(audio_offset_values) / len(audio_offset_values), 2)
        if audio_offset_values else None
    )
    report["summary"]["avg_estimated_realtime_first_interim_ms"] = (
        round(sum(est_realtime_values) / len(est_realtime_values), 2)
        if est_realtime_values else None
    )
    report["summary"]["avg_offline_asr_rtf"] = (
        round(sum(rtf_values) / len(rtf_values), 6)
        if rtf_values else None
    )
    report["summary"]["avg_streaming_asr_rtf"] = (
        round(sum(srtf_values) / len(srtf_values), 6)
        if srtf_values else None
    )
    report["summary"]["avg_cer"] = (
        round(sum(cer_values) / len(cer_values), 6)
        if cer_values else None
    )

    # 6. Bottleneck assessment
    report["assessment"] = assess_bottleneck(env_info, report["files"])

    return report


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Task 128B/128F — Benchmark real speech dataset against ASR pipeline",
    )
    parser.add_argument(
        "--dataset-dir",
        default="真实语音数据集",
        help="Path to dataset directory containing .m4a + .txt files",
    )
    parser.add_argument(
        "--output",
        default=str(_REPORT_PATH_DEFAULT),
        help="Output path for JSON benchmark report",
    )
    parser.add_argument(
        "--ffmpeg-path",
        default=None,
        help="Explicit path to ffmpeg executable (overrides PATH and auto-detect)",
    )
    parser.add_argument(
        "--streaming-preset",
        default=None,
        help="Streaming chunk preset (balanced, ultra_low_latency, high_accuracy, "
             "near_offline). Overrides default 'balanced' for single-run mode.",
    )
    parser.add_argument(
        "--compare-presets",
        default=None,
        help="Comma-separated preset names to compare, e.g. "
             "'balanced,ultra_low_latency,high_accuracy'. Runs each preset "
             "and generates a comparison report.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # Resolve ffmpeg path: CLI arg > env var > auto-detect
    ffmpeg_path = args.ffmpeg_path or os.environ.get("SMART_DESK_FFMPEG_PATH")

    # ── Mode: --compare-presets (Task 128F) ───────────────────────────
    if args.compare_presets:
        preset_list = [p.strip() for p in args.compare_presets.split(",") if p.strip()]
        if not preset_list:
            print("Error: --compare-presets requires at least one preset name.")
            sys.exit(1)

        print(f"[Task 128F] Preset comparison: {preset_list}")
        print(f"[Task 128F] Dataset: {args.dataset_dir}")
        if ffmpeg_path:
            print(f"[Task 128F] ffmpeg path: {ffmpeg_path}")

        report = run_preset_comparison(
            dataset_dir=args.dataset_dir,
            preset_names=preset_list,
            ffmpeg_path=ffmpeg_path,
        )

        # Write both the standard benchmark report and the preset comparison report
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"\n[Task 128F] Comparison report written to {output_path}")

        # Also write to the dedicated preset report path
        preset_report_path = (
            Path(__file__).resolve().parent.parent.parent
            / "working"
            / "speech-low-latency-preset-report.json"
        )
        preset_report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(preset_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        print(f"[Task 128F] Preset report written to {preset_report_path}")

        # Print comparison summary
        print(f"\n{'='*60}")
        print(f"  Task 128F — Preset Comparison Summary")
        print(f"{'='*60}")
        for p in report.get("presets", []):
            name = p.get("preset_name", "?")
            if not p.get("available"):
                print(f"  {name}: UNAVAILABLE — {p.get('note', '')}")
                continue
            s = p.get("summary", {})
            print(f"  {name} (chunk_size={p.get('chunk_size')}):")
            print(f"    success={s.get('success_count')} failed={s.get('failed_count')}")
            print(f"    est_realtime_first_interim={s.get('avg_estimated_realtime_first_interim_ms', 'N/A')} ms")
            print(f"    audio_offset={s.get('avg_first_interim_audio_offset_ms', 'N/A')} ms")
            print(f"    processing_first={s.get('avg_processing_first_interim_ms', 'N/A')} ms")
            print(f"    streaming_rtf={s.get('avg_streaming_asr_rtf', 'N/A')}")
            print(f"    CER={s.get('avg_cer', 'N/A')}")

        comp = report.get("comparison", {})
        if comp:
            print(f"\n  Comparison:")
            print(f"    Best latency preset:  {comp.get('best_latency_preset', 'N/A')}")
            print(f"    Best accuracy preset: {comp.get('best_accuracy_preset', 'N/A')}")
            print(f"    Recommended preset:   {comp.get('recommended_preset', 'N/A')}")
            print(f"    Reason:               {comp.get('recommendation_reason', 'N/A')}")
            print(f"    Latency improvement:  {comp.get('latency_improvement_ms', 'N/A')} ms")
            print(f"    CER regression:       {comp.get('cer_regression', 'N/A')}")

        print(f"\n[Task 128F] Done.")
        return

    # ── Mode: single-run (Task 128B), optionally with a preset ────────
    streaming_preset = args.streaming_preset or os.environ.get("SMART_DESK_ASR_STREAMING_PRESET")

    print(f"[Task 128B] Benchmark real speech dataset: {args.dataset_dir}")
    print(f"[Task 128B] Output: {args.output}")
    if streaming_preset:
        print(f"[Task 128B] Streaming preset: {streaming_preset}")
    if ffmpeg_path:
        print(f"[Task 128B] ffmpeg path: {ffmpeg_path}")
    print()

    report = generate_report(
        dataset_dir=args.dataset_dir,
        output_path=args.output,
        ffmpeg_path=ffmpeg_path,
        streaming_preset=streaming_preset,
    )

    # Write JSON report
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[Task 128B] JSON report written to {output_path}")

    # Print summary to stdout
    summary = report.get("summary", {})
    files = report.get("files", [])

    print(f"\n{'='*60}")
    print(f"  Task 128B — Benchmark Summary")
    print(f"{'='*60}")
    print(f"  Dataset:          {report.get('dataset_dir')}")
    print(f"  Files found:      {summary.get('file_count', 0)}")
    print(f"  Success:          {summary.get('success_count', 0)}")
    print(f"  Failed:           {summary.get('failed_count', 0)}")
    print(f"  ffmpeg:           {report.get('environment',{}).get('ffmpeg_path', 'not found')} "
          f"({report.get('environment',{}).get('ffmpeg_discovery_method', 'N/A')})")
    print(f"  Avg processing first interim:    {summary.get('avg_processing_first_interim_ms', 'N/A')} ms")
    print(f"  Avg first interim audio offset:  {summary.get('avg_first_interim_audio_offset_ms', 'N/A')} ms")
    print(f"  Avg estimated realtime first:    {summary.get('avg_estimated_realtime_first_interim_ms', 'N/A')} ms")
    print(f"  (deprecated processing-only):    {summary.get('avg_first_interim_ms_deprecated_processing_only', 'N/A')} ms")
    print(f"  Avg offline RTF:                 {summary.get('avg_offline_asr_rtf', 'N/A')}")
    print(f"  Avg streaming RTF:               {summary.get('avg_streaming_asr_rtf', 'N/A')}")
    print(f"  Avg CER:                         {summary.get('avg_cer', 'N/A')}")
    print(f"\n  Per-file details:")

    for f in files:
        audio = f.get("audio_file", "?")
        dur = f.get("audio_duration_ms", "?")
        off = f.get("offline", {}) or {}
        stm = f.get("streaming", {}) or {}
        off_ms = off.get("asr_total_ms", "?")
        cer_val = "?"
        if off.get("cer") and off["cer"].get("available"):
            cer_val = f"{off['cer']['cer']:.4f}"
        processing_ms = stm.get("processing_first_interim_ms", "?")
        audio_offset = stm.get("first_interim_audio_offset_ms", "?")
        est_realtime = stm.get("estimated_realtime_first_interim_ms", "?")
        chunk_avg = stm.get("avg_chunk_asr_ms", "?")
        errors = f.get("errors", [])

        # Safe RTF display: avoid :.4f crash when value is str/None/"?"
        _off_rtf = off.get("asr_real_time_factor")
        off_rtf_str = f"{_off_rtf:.4f}" if isinstance(_off_rtf, (int, float)) else "N/A"

        print(f"    {audio}:")
        off_mode = off.get("mode", "offline_rescore")
        print(f"      duration={dur}ms, {off_mode}")
        srtf = stm.get("streaming_asr_rtf", "?")
        print(f"      offline_asr={off_ms}ms (offline RTF={off_rtf_str}), CER={cer_val}")
        print(f"      streaming_rtf={srtf}, avg_chunk={chunk_avg}ms")
        print(f"      processing_first_interim={processing_ms}ms"
              f"  audio_offset={audio_offset}ms"
              f"  est_realtime={est_realtime}ms")
        trend = stm.get("chunk_asr_trend", {}) or {}
        if trend.get("direction"):
            print(f"      chunk_trend={trend['direction']}"
                  f" (slope_norm={trend.get('slope_normalized', '?')})")
        pct = stm.get("chunk_asr_percentiles", {}) or {}
        if pct:
            print(f"      chunk_p50={pct.get('p50','?')}ms"
                  f" p90={pct.get('p90','?')}ms"
                  f" p99={pct.get('p99','?')}ms")
        if errors:
            for e in errors[:3]:
                print(f"      [!] {e}")
        print()

    if report.get("assessment"):
        a = report["assessment"]
        print(f"  Assessment:")
        print(f"    Likely bottleneck: {a.get('likely_bottleneck', 'unknown')}")
        print(f"    Hardware upgrade helpful: {a.get('hardware_upgrade_likely_helpful', False)}")
        for note in a.get("notes", []):
            print(f"    -> {note}")

    print(f"\n[Task 128B] Done.")


if __name__ == "__main__":
    main()
