from __future__ import annotations

from backend.scripts.generate_latency_report import _compute_metrics


def test_sentence_and_finalization_bottleneck_metrics_are_computed() -> None:
    backend = [
        {"event": "sentence_completed_at", "timestamp_monotonic_ms": 90, "timestamp_wall_ms": 1000},
        {"event": "sentence_translation_queued_at", "timestamp_monotonic_ms": 100, "timestamp_wall_ms": 1010},
        {"event": "sentence_translation_dequeued_at", "timestamp_monotonic_ms": 340, "timestamp_wall_ms": 1250},
        {"event": "sentence_translation_inference_end_at", "timestamp_monotonic_ms": 1340, "timestamp_wall_ms": 2250},
        {"event": "sentence_translation_broadcast_at", "timestamp_monotonic_ms": 1342, "timestamp_wall_ms": 2252},
        {"event": "finalization_queued_at", "timestamp_monotonic_ms": 2000, "timestamp_wall_ms": 2910},
        {"event": "finalization_dequeued_at", "timestamp_monotonic_ms": 2300, "timestamp_wall_ms": 3210},
        {"event": "finalization_worker_completed_at", "timestamp_monotonic_ms": 4100, "timestamp_wall_ms": 5010},
    ]
    frontend = [
        {"event": "frontend_sentence_translation_received_at", "timestamp": 1260},
        {"event": "frontend_sentence_translation_rendered_at", "timestamp": 1272},
    ]
    metrics = _compute_metrics(
        backend,
        frontend,
        frontend_wall_offset=1000,
    )

    assert metrics["sentence_translation_queue_wait_ms"]["value_ms"] == 240
    assert metrics["sentence_translation_inference_ms"]["value_ms"] == 1000
    assert metrics["sentence_translation_delivery_ms"]["value_ms"] == 8
    assert metrics["sentence_translation_render_ms"]["value_ms"] == 12
    assert metrics["sentence_completed_to_translation_received_ms"]["value_ms"] == 1260
    assert metrics["finalization_queue_wait_ms"]["value_ms"] == 300
    assert metrics["finalization_processing_ms"]["value_ms"] == 1800
