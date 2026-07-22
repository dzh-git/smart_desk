from __future__ import annotations

import numpy as np

from backend.scripts.benchmark_streaming_speech_latency import (
    _checkpoint_rows,
    _distribution,
    _select_runs,
    _voice_onset_seconds,
)


def test_distribution_reports_interpolated_percentiles() -> None:
    result = _distribution([10.0, 20.0, 30.0, 40.0])

    assert result["count"] == 4
    assert result["mean_ms"] == 25.0
    assert result["p50_ms"] == 25.0
    assert result["max_ms"] == 40.0


def test_checkpoints_use_latest_frame_at_or_before_audio_second() -> None:
    metrics = [
        {
            "audio_offset_seconds": float(second),
            "processing_ms": float(second),
            "queue_wait_ms": 2.0,
            "queue_backlog_ms": 100.0,
            "completion_lag_ms": float(second * 2),
        }
        for second in range(1, 61)
    ]

    rows = _checkpoint_rows(metrics, 60.0)

    assert [row["audio_second"] for row in rows] == [30, 60]
    assert rows[0]["completion_lag_ms"] == 60.0
    assert rows[1]["completion_lag_ms"] == 120.0


def test_all_suite_selects_manual_long_and_manual_auto_smoke() -> None:
    manifest = {
        "controlled_sessions": [
            {"language": "zh", "audio": "zh-short.wav"},
            {"language": "en", "audio": "en-short.wav"},
        ],
        "long_stress_sessions": [
            {"language": "zh", "audio": "zh-long.wav"},
            {"language": "en", "audio": "en-long.wav"},
        ],
    }

    runs = _select_runs(manifest, "all")

    assert [(item[0]["audio"], item[1]) for item in runs] == [
        ("zh-short.wav", "zh"),
        ("zh-short.wav", "auto"),
        ("en-short.wav", "en"),
        ("en-short.wav", "auto"),
        ("zh-long.wav", "zh"),
        ("en-long.wav", "en"),
    ]


def test_voice_onset_uses_vad_rms_floor() -> None:
    silent = np.zeros(1_600, dtype=np.int16).tobytes()
    speech = np.full(1_600, 1_000, dtype=np.int16).tobytes()

    assert _voice_onset_seconds([silent, silent, speech]) == 0.2
