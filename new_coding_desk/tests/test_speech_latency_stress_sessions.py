from __future__ import annotations

import numpy as np
import pytest

from backend.scripts.prepare_speech_latency_stress_sessions import (
    TARGET_ACTIVE_RMS_DBFS,
    _active_rms,
    _dbfs,
    _long_sequence,
    _normalize_active_rms,
)


@pytest.mark.parametrize("amplitude", [0.0005, 0.01, 0.2])
def test_active_rms_normalization_equalizes_volume(amplitude: float) -> None:
    timeline = np.arange(16_000, dtype=np.float32) / 16_000
    samples = amplitude * np.sin(2 * np.pi * 220 * timeline)

    normalized, metrics = _normalize_active_rms(samples)

    assert _dbfs(_active_rms(normalized)) == pytest.approx(
        TARGET_ACTIVE_RMS_DBFS, abs=0.05,
    )
    assert metrics["active_rms_after_dbfs"] == pytest.approx(
        TARGET_ACTIVE_RMS_DBFS, abs=0.05,
    )


def test_long_sequence_exceeds_five_minutes_without_chopping_segments() -> None:
    segments = [
        {
            "audio": f"clip-{index}.wav",
            "start_seconds": 0.0,
            "end_seconds": 6.0,
        }
        for index in range(15)
    ]

    result = _long_sequence(segments)
    estimated_seconds = sum(
        item["end_seconds"] - item["start_seconds"] + 0.7
        for item in result
    )

    assert estimated_seconds >= 300.0
    assert len(result) > len(segments)
