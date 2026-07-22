"""Add volume-controlled and five-minute stress sessions to a speech dataset."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


SAMPLE_RATE = 16_000
TARGET_ACTIVE_RMS_DBFS = -23.0
MAX_GAIN_DB = 48.0
PEAK_LIMIT_DBFS = -1.5
LEADING_SILENCE_SECONDS = 0.5
BETWEEN_CLIP_SILENCE_SECONDS = 0.7
TRAILING_SILENCE_SECONDS = 1.2
LONG_TARGET_SECONDS = 300.0


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(max(value, 1e-12))


def _active_rms(samples: np.ndarray) -> float:
    absolute = np.abs(samples)
    peak = float(np.max(absolute)) if samples.size else 0.0
    if peak <= 1e-8:
        return 0.0
    # A relative gate keeps the measurement invariant when a very quiet clip
    # is amplified; an absolute dBFS gate would select a different population
    # before and after gain adjustment.
    gate = max(1e-8, peak * 0.03)
    active = samples[absolute >= gate]
    if not active.size:
        active = samples
    return float(np.sqrt(np.mean(np.square(active), dtype=np.float64)))


def _normalize_active_rms(samples: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    before_rms = _active_rms(samples)
    before_peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    target_rms = 10 ** (TARGET_ACTIVE_RMS_DBFS / 20.0)
    desired_gain = target_rms / max(before_rms, 1e-8)
    max_gain = 10 ** (MAX_GAIN_DB / 20.0)
    gain = float(np.clip(desired_gain, 1.0 / max_gain, max_gain))
    normalized = samples.astype(np.float32, copy=True) * gain
    peak_limit = 10 ** (PEAK_LIMIT_DBFS / 20.0)
    normalized_peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
    if normalized_peak > peak_limit:
        limiter_gain = peak_limit / normalized_peak
        normalized *= limiter_gain
        gain *= limiter_gain
    after_rms = _active_rms(normalized)
    after_peak = float(np.max(np.abs(normalized))) if normalized.size else 0.0
    return normalized, {
        "active_rms_before_dbfs": round(_dbfs(before_rms), 2),
        "active_rms_after_dbfs": round(_dbfs(after_rms), 2),
        "peak_before_dbfs": round(_dbfs(before_peak), 2),
        "peak_after_dbfs": round(_dbfs(after_peak), 2),
        "applied_gain_db": round(_dbfs(gain), 2),
    }


def _load_mono(path: Path) -> np.ndarray:
    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    if rate != SAMPLE_RATE:
        raise RuntimeError(f"Expected {SAMPLE_RATE} Hz, got {rate}: {path}")
    if audio.shape[1] > 1:
        audio = np.mean(audio, axis=1, keepdims=True)
    return audio[:, 0]


def _write_session(
    dataset_root: Path,
    destination: Path,
    segments: list[dict[str, Any]],
    *,
    language: str,
    normalize: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pieces = [np.zeros(round(LEADING_SILENCE_SECONDS * SAMPLE_RATE), dtype=np.float32)]
    output_segments: list[dict[str, Any]] = []
    volume_rows: list[dict[str, Any]] = []
    cursor = len(pieces[0])

    for index, segment in enumerate(segments):
        source_path = dataset_root / segment["audio"]
        samples = _load_mono(source_path)
        normalized, volume = _normalize_active_rms(samples)
        rendered = normalized if normalize else samples
        start_seconds = cursor / SAMPLE_RATE
        pieces.append(rendered)
        cursor += len(rendered)
        output_segments.append({
            **segment,
            "start_seconds": round(start_seconds, 3),
            "end_seconds": round(cursor / SAMPLE_RATE, 3),
        })
        volume_rows.append({
            "audio": segment["audio"],
            "language": language,
            **volume,
        })
        if index != len(segments) - 1:
            silence = np.zeros(
                round(BETWEEN_CLIP_SILENCE_SECONDS * SAMPLE_RATE),
                dtype=np.float32,
            )
            pieces.append(silence)
            cursor += len(silence)

    trailing = np.zeros(round(TRAILING_SILENCE_SECONDS * SAMPLE_RATE), dtype=np.float32)
    pieces.append(trailing)
    cursor += len(trailing)
    rendered_session = np.concatenate(pieces)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(destination), rendered_session, SAMPLE_RATE, subtype="PCM_16")
    joiner = "" if language == "zh" else " "
    relative = destination.relative_to(dataset_root).as_posix()
    return ({
        "audio": relative,
        "language": language,
        "requested_language_modes": [language, "auto"],
        "duration_seconds": round(len(rendered_session) / SAMPLE_RATE, 3),
        "sample_rate": SAMPLE_RATE,
        "transcript": joiner.join(item["transcript"] for item in segments),
        "normalized_transcript": joiner.join(
            item["normalized_transcript"] for item in segments
        ),
        "segments": output_segments,
        "normalization": (
            {
                "method": "gated active RMS with peak limiting",
                "target_active_rms_dbfs": TARGET_ACTIVE_RMS_DBFS,
                "max_gain_db": MAX_GAIN_DB,
                "peak_limit_dbfs": PEAK_LIMIT_DBFS,
            }
            if normalize else None
        ),
    }, volume_rows)


def _unique_language_segments(manifest: dict[str, Any], language: str) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for session in manifest["sessions"]:
        if session["language"] != language:
            continue
        for segment in session["segments"]:
            if segment["audio"] in seen:
                continue
            seen.add(segment["audio"])
            unique.append(segment)
    return unique


def _long_sequence(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return []
    sequence: list[dict[str, Any]] = []
    estimated_seconds = LEADING_SILENCE_SECONDS + TRAILING_SILENCE_SECONDS
    round_index = 0
    while estimated_seconds < LONG_TARGET_SECONDS:
        shift = (round_index * 5) % len(segments)
        rotated = segments[shift:] + segments[:shift]
        if round_index % 2:
            rotated = list(reversed(rotated))
        for segment in rotated:
            sequence.append(segment)
            estimated_seconds += (
                float(segment["end_seconds"])
                - float(segment["start_seconds"])
                + BETWEEN_CLIP_SILENCE_SECONDS
            )
            if estimated_seconds >= LONG_TARGET_SECONDS:
                break
        round_index += 1
    return sequence


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def augment(dataset_root: Path) -> Path:
    dataset_root = dataset_root.resolve()
    manifest_path = dataset_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    controlled_sessions: list[dict[str, Any]] = []
    long_sessions: list[dict[str, Any]] = []
    volume_by_audio: dict[str, dict[str, Any]] = {}

    for language in ("zh", "en"):
        originals = [item for item in manifest["sessions"] if item["language"] == language]
        for index, original in enumerate(originals, 1):
            session, volume_rows = _write_session(
                dataset_root,
                dataset_root / "sessions" / "controlled" / f"{language}_controlled_{index:02d}.wav",
                original["segments"],
                language=language,
                normalize=True,
            )
            session["scenario"] = "volume-controlled latency and accuracy baseline"
            controlled_sessions.append(session)
            for row in volume_rows:
                volume_by_audio[row["audio"]] = row

        long_source = _long_sequence(_unique_language_segments(manifest, language))
        long_session, volume_rows = _write_session(
            dataset_root,
            dataset_root / "sessions" / "long" / f"{language}_long_05min.wav",
            long_source,
            language=language,
            normalize=True,
        )
        long_session["scenario"] = (
            "five-minute normalized cumulative-backlog stress test; source clips repeat "
            "in deterministic rotated order and are not intended for aggregate accuracy scoring"
        )
        long_session["repeated_source_audio"] = True
        long_sessions.append(long_session)
        for row in volume_rows:
            volume_by_audio[row["audio"]] = row

    volume_rows = sorted(volume_by_audio.values(), key=lambda item: item["audio"])
    before_values = [item["active_rms_before_dbfs"] for item in volume_rows]
    after_values = [item["active_rms_after_dbfs"] for item in volume_rows]
    volume_report = {
        "method": "gated active RMS with peak limiting",
        "target_active_rms_dbfs": TARGET_ACTIVE_RMS_DBFS,
        "source_clip_count": len(volume_rows),
        "before": {
            "minimum_dbfs": min(before_values),
            "maximum_dbfs": max(before_values),
            "spread_db": round(max(before_values) - min(before_values), 2),
        },
        "after": {
            "minimum_dbfs": min(after_values),
            "maximum_dbfs": max(after_values),
            "spread_db": round(max(after_values) - min(after_values), 2),
        },
        "clips": volume_rows,
    }
    (dataset_root / "volume_report.json").write_text(
        json.dumps(volume_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    manifest["dataset_format_version"] = 2
    manifest["controlled_sessions"] = controlled_sessions
    manifest["long_stress_sessions"] = long_sessions
    manifest["recommended_latency_protocol"] = {
        "controlled_short": "use all controlled_sessions for first-caption and accuracy metrics",
        "cumulative_backlog": "use long_stress_sessions and replay each at real-time 100 ms cadence",
        "vad_robustness": "use the original sessions field without volume normalization",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    wave_paths = sorted((dataset_root / "sessions").rglob("*.wav"))
    checksums = [
        f"{_sha256(path)}  {path.relative_to(dataset_root).as_posix()}"
        for path in wave_paths
    ]
    (dataset_root / "SHA256SUMS.txt").write_text(
        "\n".join(checksums) + "\n", encoding="utf-8"
    )
    print(
        f"Prepared {len(controlled_sessions)} controlled sessions and "
        f"{len(long_sessions)} long sessions at {dataset_root}"
    )
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("working/speech_latency_dataset/fleurs_zh_en"),
    )
    args = parser.parse_args()
    augment(args.dataset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
