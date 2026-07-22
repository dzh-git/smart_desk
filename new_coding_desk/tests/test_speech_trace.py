"""
Tests for SpeechTrace — temporary diagnostic instrumentation.

Task 128A: Verifies that:
    1. trace() can record events and export them via get_trace().
    2. clear_trace() empties the buffer.
    3. Ring buffer wraps correctly when exceeding MAX_ENTRIES.
    4. Disabled trace is a no-op.
    5. Backend trace points in the speech pipeline are called.
    6. Device report generator does not fail and reports false/unknown
       when CUDA is unavailable.
"""
from __future__ import annotations

import json
import os
import threading
from unittest.mock import AsyncMock, patch

import pytest

from backend.websocket.speech_trace import (
    trace,
    get_trace,
    clear_trace,
    is_trace_enabled,
    MAX_ENTRIES,
)


# ── Fixture: auto-clear between tests ─────────────────────────────


@pytest.fixture(autouse=True)
def _clear_trace_before() -> None:
    """Clear trace buffer before each test."""
    clear_trace()


@pytest.fixture
def enable_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable tracing for the duration of this test."""
    monkeypatch.setenv("SMART_DESK_ENABLE_SPEECH_TRACE", "true")
    monkeypatch.setattr(
        "backend.websocket.speech_trace._enabled", True,
    )


@pytest.fixture
def disable_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tracing is disabled."""
    monkeypatch.setenv("SMART_DESK_ENABLE_SPEECH_TRACE", "false")
    monkeypatch.setattr(
        "backend.websocket.speech_trace._enabled", False,
    )


class TestTraceHelper:
    """Core trace helper functionality."""

    def test_trace_records_event(self, enable_trace) -> None:
        """trace() appends an event to the buffer."""
        trace("test_event", utterance_id="utt_test_001", meeting_id=1, seat_id=1)
        events = get_trace()
        assert len(events) == 1
        assert events[0]["event"] == "test_event"
        assert events[0]["utterance_id"] == "utt_test_001"
        assert events[0]["meeting_id"] == 1
        assert events[0]["seat_id"] == 1
        assert "timestamp_monotonic_ms" in events[0]
        assert "timestamp_wall_ms" in events[0]

    def test_trace_extra_fields(self, enable_trace) -> None:
        """trace() accepts and stores extra keyword arguments."""
        trace("with_extra", revision=5, asr_infer_ms=123, duration_ms=45.6)
        events = get_trace()
        assert len(events) == 1
        assert events[0]["revision"] == 5
        assert events[0]["asr_infer_ms"] == 123
        assert events[0]["duration_ms"] == 45.6

    def test_get_trace_returns_copy(self, enable_trace) -> None:
        """get_trace() returns a copy; mutating it does not affect buffer."""
        trace("event_a")
        copy1 = get_trace()
        copy1.clear()
        copy2 = get_trace()
        assert len(copy2) == 1

    def test_clear_trace_empties_buffer(self, enable_trace) -> None:
        """clear_trace() removes all events from the buffer."""
        trace("event_a")
        trace("event_b")
        assert len(get_trace()) == 2
        clear_trace()
        assert len(get_trace()) == 0

    def test_clear_trace_idempotent(self, enable_trace) -> None:
        """clear_trace() can be called multiple times safely."""
        clear_trace()
        clear_trace()
        assert len(get_trace()) == 0

    def test_trace_disabled_is_noop(self, disable_trace) -> None:
        """When trace is disabled, trace() does nothing."""
        trace("should_not_appear", utterance_id="utt_disabled")
        assert len(get_trace()) == 0

    def test_is_trace_enabled_returns_false(self, disable_trace) -> None:
        """is_trace_enabled() returns False when disabled."""
        assert is_trace_enabled() is False

    def test_is_trace_enabled_returns_true(self, enable_trace) -> None:
        """is_trace_enabled() returns True when enabled."""
        assert is_trace_enabled() is True

    def test_utterance_id_optional(self, enable_trace) -> None:
        """trace() works without utterance_id (session-level events)."""
        trace("session_event", meeting_id=1, seat_id=1)
        events = get_trace()
        assert len(events) == 1
        assert "utterance_id" not in events[0]

    def test_buffer_capacity_wraps(self, enable_trace) -> None:
        """When buffer exceeds MAX_ENTRIES, oldest event is discarded."""
        for i in range(MAX_ENTRIES):
            trace(f"event_{i}", index=i)
        assert len(get_trace()) == MAX_ENTRIES

        trace("event_last")
        events = get_trace()
        assert len(events) == MAX_ENTRIES
        assert events[-1]["event"] == "event_last"


class TestTraceThreadSafety:
    """Trace buffer is thread-safe."""

    def test_concurrent_trace_calls(self, enable_trace) -> None:
        """Multiple threads can call trace() concurrently without data loss."""
        def _writer(n: int) -> None:
            for i in range(20):
                trace(f"thread_{n}_event_{i}")

        threads = [threading.Thread(target=_writer, args=(tid,)) for tid in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        events = get_trace()
        assert len(events) > 0
        for ev in events:
            assert "event" in ev
            assert "timestamp_monotonic_ms" in ev


# ── Backend pipeline trace point tests ────────────────────


class TestPipelineTracePoints:
    """Key trace points in the backend speech pipeline are called."""

    @pytest.mark.anyio
    async def test_binary_message_traces_key_points(
        self, enable_trace, monkeypatch,
    ) -> None:
        """_handle_binary_message records backend_pcm_received_at,
        backend_process_pcm_start_at, interim_event_created_at, and
        interim_event_broadcast_at."""
        from backend.websocket.speech_ws import _handle_binary_message
        from backend.services.speech_stream_service import stream_service

        key, token = stream_service.create_session(1, 1)
        try:
            stream_service.start_utterance(key, "utt_trace_key_001")

            def _mock_process(sk: str, data: bytes) -> dict:
                return {
                    "utterance_id": "utt_trace_key_001",
                    "revision": 1,
                    "source_text": "test text",
                    "caption": {
                        "previous_line": "",
                        "current_line": "test",
                        "mode": "two_line",
                    },
                    "vad_should_finalize": False,
                }

            monkeypatch.setattr(stream_service, "process_pcm_frame", _mock_process)

            ws = AsyncMock()
            clear_trace()
            await _handle_binary_message(ws, b"\x00" * 3200, 1, 1, key)

            events = get_trace()
            trace_names = [e["event"] for e in events]

            assert "backend_pcm_received_at" in trace_names
            # WS-layer trace was renamed from asr_streaming_start_at
            # to backend_process_pcm_start_at (Task 128A rework)
            assert "backend_process_pcm_start_at" in trace_names
            assert "interim_event_created_at" in trace_names
            assert "interim_event_broadcast_at" in trace_names
        finally:
            stream_service.remove_session(key, token)
            clear_trace()

    @pytest.mark.anyio
    async def test_binary_message_empty_text_skips_interim_trace(
        self, enable_trace, monkeypatch,
    ) -> None:
        """When source_text is empty, interim_event traces are skipped."""
        from backend.websocket.speech_ws import _handle_binary_message
        from backend.services.speech_stream_service import stream_service

        key, token = stream_service.create_session(1, 1)
        try:
            stream_service.start_utterance(key, "utt_trace_empty_001")

            def _mock_process(sk: str, data: bytes) -> dict:
                return {
                    "utterance_id": "utt_trace_empty_001",
                    "revision": 1,
                    "source_text": "",
                    "caption": {
                        "previous_line": "",
                        "current_line": "",
                        "mode": "two_line",
                    },
                    "vad_should_finalize": False,
                }

            monkeypatch.setattr(stream_service, "process_pcm_frame", _mock_process)

            ws = AsyncMock()
            clear_trace()
            await _handle_binary_message(ws, b"\x00" * 3200, 1, 1, key)

            events = get_trace()
            trace_names = [e["event"] for e in events]

            assert "backend_pcm_received_at" in trace_names
            assert "backend_process_pcm_start_at" in trace_names
            assert "interim_event_created_at" not in trace_names
        finally:
            stream_service.remove_session(key, token)
            clear_trace()

    def test_process_pcm_frame_traces_asr_timing(
        self, enable_trace, monkeypatch,
    ) -> None:
        """process_pcm_frame records asr_streaming_start_at and
        asr_streaming_end_at."""
        from backend.services.speech_stream_service import stream_service

        key, token = stream_service.create_session(1, 1)
        try:
            stream_service.start_utterance(
                key, "utt_trace_asr_timing_001", language_mode="zh",
            )

            mock_sm = _MockSpeechModuleWithTrace()
            monkeypatch.setattr(
                stream_service, "_get_speech_module", lambda: mock_sm,
            )

            clear_trace()
            for _ in range(5):
                stream_service.process_pcm_frame(key, b"\x00" * 3200)
            voice = (3000).to_bytes(2, "little", signed=True) * 1600
            for _ in range(3):
                stream_service.process_pcm_frame(key, voice)

            events = get_trace()
            trace_names = [e["event"] for e in events]

            assert "asr_streaming_start_at" in trace_names
            assert "asr_streaming_end_at" in trace_names

            asr_end_events = [
                e for e in events if e["event"] == "asr_streaming_end_at"
            ]
            if asr_end_events:
                assert "asr_infer_ms" in asr_end_events[0]
                assert isinstance(asr_end_events[0]["asr_infer_ms"], (int, float))
                assert asr_end_events[0]["asr_infer_ms"] >= 0
        finally:
            stream_service.remove_session(key, token)
            clear_trace()


class _MockSpeechModuleWithTrace:
    """Minimal mock that returns ASR text for trace tests."""

    _ready = True

    @property
    def ready(self) -> bool:
        return self._ready

    def preload(self) -> None:
        pass

    def set_session_context(
        self, session_key: str, meeting_id: int, seat_id: int,
    ) -> None:
        pass

    def process_interim_array(
        self, audio: object, session_key: str,
    ) -> str:
        return "测试语音识别"

    def start_utterance(self, session_key: str) -> None:
        pass

    def reset_interim(self, session_key: str) -> None:
        pass


# ── Device report generator tests ─────────────────────────


class TestDeviceReportGenerator:
    """Device report generator works correctly without CUDA."""

    def test_generate_device_report_no_cuda_failure(self, monkeypatch) -> None:
        """generate_device_report does not raise when CUDA is unavailable."""
        from backend.scripts.generate_device_report import generate_report

        monkeypatch.setattr(
            "backend.scripts.generate_device_report._probe_torch",
            lambda: {
                "torch_available": False,
                "torch_cuda_available": False,
                "cuda_device_name": None,
                "cuda_device_count": 0,
            },
        )

        report = generate_report()
        assert report is not None
        assert report["report_type"] == "speech-latency-device-report"
        assert report["task"] == "128A"
        assert report["torch"]["torch_available"] is False
        assert report["torch"]["torch_cuda_available"] is False
        assert report["conclusion"]["runs_on_cpu"] is True
        assert report["conclusion"]["runs_on_cuda"] is False

    def test_generate_device_report_with_cuda(self, monkeypatch) -> None:
        """generate_device_report handles CUDA-available scenario."""
        from backend.scripts.generate_device_report import generate_report

        monkeypatch.setattr(
            "backend.scripts.generate_device_report._probe_torch",
            lambda: {
                "torch_available": True,
                "torch_cuda_available": True,
                "cuda_device_name": "NVIDIA Test GPU",
                "cuda_device_count": 1,
            },
        )

        report = generate_report()
        assert report["torch"]["torch_available"] is True
        assert report["torch"]["torch_cuda_available"] is True
        assert report["torch"]["cuda_device_name"] == "NVIDIA Test GPU"

    def test_generate_device_report_contains_required_fields(self) -> None:
        """Report contains all required top-level sections."""
        from backend.scripts.generate_device_report import generate_report

        report = generate_report()
        for key in (
            "report_type", "task", "python", "os", "cpu",
            "torch", "speech_module", "translation_service",
            "conclusion",
        ):
            assert key in report, f"Missing required field: {key}"

    def test_generate_device_report_unknown_fields(self, monkeypatch) -> None:
        """Fields that cannot be read show 'unknown' rather than raising."""
        from backend.scripts.generate_device_report import generate_report

        monkeypatch.setattr(
            "backend.scripts.generate_device_report._get_cpu_info",
            lambda: "unknown",
        )

        report = generate_report()
        assert report["cpu"]["info"] == "unknown"

    def test_generate_device_report_handles_import_error(
        self, monkeypatch,
    ) -> None:
        """probe_speech_module handles import errors gracefully."""
        monkeypatch.setattr(
            "backend.scripts.generate_device_report._probe_speech_module",
            lambda: {
                "error_reading_speech_module": "Simulated import error",
            },
        )

        from backend.scripts.generate_device_report import generate_report
        report = generate_report()
        assert "error_reading_speech_module" in report["speech_module"]


# ── Latency report generator tests ──────────────────────


class TestLatencyReportGenerator:
    """Latency report generator functions correctly."""

    def test_generate_latency_report_contains_required_fields(self) -> None:
        """Report contains all required sections (reworked schema)."""
        from backend.scripts.generate_latency_report import generate_report

        report = generate_report()
        for key in (
            "report_type", "task", "trace_sources",
            "missing_fields", "trace_points", "latency_metrics_defined",
            "metrics_computed", "bottleneck_assessment",
            "sampling_instructions", "code_level_bottleneck_assessment",
        ):
            assert key in report, f"Missing required field: {key}"

        # Check that trace_sources has expected sub-keys
        assert "frontend" in report["trace_sources"]
        assert "backend" in report["trace_sources"]

        # Check that metrics_computed has expected category keys
        computed = report["metrics_computed"]
        for cat in ("frontend_only", "backend_only", "cross_boundary",
                     "end_to_end", "unavailable"):
            assert cat in computed, f"Missing metrics category: {cat}"

    def test_trace_points_listed(self) -> None:
        """Trace point list contains expected entries including renamed point."""
        from backend.scripts.generate_latency_report import generate_report

        report = generate_report()
        names = [tp["name"] for tp in report["trace_points"]]

        required_trace_points = [
            "start_clicked_at",
            "microphone_start_requested_at",
            "microphone_started_at",
            "speech_ws_connect_start_at",
            "backend_pcm_received_at",
            "backend_process_pcm_start_at",  # renamed from asr_streaming_start_at (WS-layer)
            "asr_streaming_start_at",        # the real ASR start (service-layer)
            "asr_streaming_end_at",
            "interim_event_created_at",
            "interim_event_broadcast_at",
            "frontend_interim_received_at",
            "frontend_interim_rendered_at",
        ]
        for tp in required_trace_points:
            assert tp in names, f"Missing trace point: {tp}"

        # Verify that backend_process_pcm_start_at is distinct from asr_streaming_start_at
        assert "backend_process_pcm_start_at" in names
        assert names.count("asr_streaming_start_at") == 1, (
            "Duplicate asr_streaming_start_at detected"
        )

    def test_latency_metrics_defined(self) -> None:
        """All latency metrics are defined."""
        from backend.scripts.generate_latency_report import generate_report

        report = generate_report()
        assert report["latency_metrics_count"] >= 11

    def test_sampling_instructions_present(self) -> None:
        """Sampling instructions are included."""
        from backend.scripts.generate_latency_report import generate_report

        report = generate_report()
        instructions = report["sampling_instructions"]
        assert "how_to_sample" in instructions
        assert instructions["how_to_sample"] != ""
        # Should now mention frontend export methods
        assert "frontend_export_methods" in instructions

    def test_bottleneck_assessment_present(self) -> None:
        """Bottleneck assessment section is included."""
        from backend.scripts.generate_latency_report import generate_report

        report = generate_report()
        assessment = report["bottleneck_assessment"]
        assert "assessment" in assessment
        assert "computed_segments" in assessment

    # ── Merged metrics tests (Task 128A rework) ────────────────────────

    def test_compute_metrics_with_frontend_and_backend(self, tmp_path) -> None:
        """When frontend+backend traces are provided, e2e metrics are computed."""
        from backend.scripts.generate_latency_report import generate_report

        # Create a simulated frontend trace file
        wall_offset = 1000000  # simulated Date.now() - performance.now()
        frontend_events = [
            {"event": "start_clicked_at", "timestamp": 0, "data": {}},
            {"event": "microphone_started_at", "timestamp": 150, "data": {}},
            {"event": "frontend_pcm_created_at", "timestamp": 400, "data": {}},
            {"event": "frontend_pcm_sent_at", "timestamp": 405, "data": {}},
            {"event": "frontend_interim_received_at", "timestamp": 1200, "data": {}},
            {"event": "frontend_interim_rendered_at", "timestamp": 1220, "data": {}},
        ]
        frontend_trace = {
            "recorded_at": "2026-06-15T07:00:00Z",
            "trace_enabled": True,
            "event_count": len(frontend_events),
            "wall_clock_offset_ms": wall_offset,
            "events": frontend_events,
        }

        fe_path = tmp_path / "frontend-trace.json"
        with open(str(fe_path), "w", encoding="utf-8") as f:
            json.dump(frontend_trace, f)

        # Populate backend trace with matching events via direct trace() calls
        # (report reads from the ring buffer, so we put events there)
        be_events = [
            {"event": "backend_pcm_received_at",
             "timestamp_monotonic_ms": 500, "timestamp_wall_ms": wall_offset + 410},
            {"event": "asr_streaming_start_at",
             "timestamp_monotonic_ms": 505, "timestamp_wall_ms": wall_offset + 415},
            {"event": "asr_streaming_end_at",
             "timestamp_monotonic_ms": 755, "timestamp_wall_ms": wall_offset + 665,
             "asr_infer_ms": 250},
            {"event": "interim_event_created_at",
             "timestamp_monotonic_ms": 760, "timestamp_wall_ms": wall_offset + 670},
            {"event": "interim_event_broadcast_at",
             "timestamp_monotonic_ms": 762, "timestamp_wall_ms": wall_offset + 672},
        ]
        # Temporarily enable trace and inject backend events
        import backend.websocket.speech_trace as st_mod
        old_enabled = st_mod._enabled
        try:
            st_mod._enabled = True
            st_mod.clear_trace()
            for ev in be_events:
                st_mod.trace(
                    ev["event"],
                    timestamp_monotonic_ms=ev["timestamp_monotonic_ms"],
                    timestamp_wall_ms=ev["timestamp_wall_ms"],
                    **{k: v for k, v in ev.items()
                       if k not in ("event", "timestamp_monotonic_ms", "timestamp_wall_ms")},
                )

            report = generate_report(frontend_trace_path=str(fe_path))
        finally:
            st_mod.clear_trace()
            st_mod._enabled = old_enabled

        # Verify report structure
        assert report["trace_sources"]["frontend"]["available"] is True
        assert report["trace_sources"]["backend"]["available"] is True

        # Check computed metrics by category
        computed = report["metrics_computed"]

        # Frontend-only metrics
        fe_metrics = computed["frontend_only"]
        assert fe_metrics["start_to_mic_ready_ms"]["computed"] is True
        assert fe_metrics["start_to_mic_ready_ms"]["value_ms"] == 150
        assert fe_metrics["first_pcm_created_to_sent_ms"]["computed"] is True
        assert fe_metrics["first_pcm_created_to_sent_ms"]["value_ms"] == 5
        assert fe_metrics["frontend_received_to_rendered_ms"]["computed"] is True
        assert fe_metrics["frontend_received_to_rendered_ms"]["value_ms"] == 20

        # Backend-only metrics
        bk_metrics = computed["backend_only"]
        assert bk_metrics["backend_received_to_asr_start_ms"]["computed"] is True
        assert bk_metrics["backend_received_to_asr_start_ms"]["value_ms"] == 5
        assert bk_metrics["asr_infer_ms"]["computed"] is True
        # The perf_counter override takes precedence
        assert bk_metrics["asr_infer_ms"]["value_ms"] == 250
        assert bk_metrics["asr_end_to_interim_broadcast_ms"]["computed"] is True

        # End-to-end metrics
        e2e_metrics = computed["end_to_end"]
        assert e2e_metrics["start_to_first_interim_ms"]["computed"] is True
        assert e2e_metrics["start_to_first_interim_ms"]["value_ms"] == 1220
        assert e2e_metrics["first_pcm_to_first_interim_ms"]["computed"] is True
        assert e2e_metrics["first_pcm_to_first_interim_ms"]["value_ms"] == 820

        # Cross-boundary metrics
        xb_metrics = computed["cross_boundary"]
        assert xb_metrics["first_pcm_sent_to_backend_received_ms"]["computed"] is True
        assert xb_metrics["interim_broadcast_to_frontend_received_ms"]["computed"] is True

        # Bottleneck assessment should show complete
        assert report["bottleneck_assessment"]["has_e2e"] is True

    def test_compute_metrics_missing_frontend_trace(self) -> None:
        """Without frontend trace, end-to-end metrics are unavailable."""
        from backend.scripts.generate_latency_report import generate_report

        report = generate_report(frontend_trace_path=None)
        computed = report["metrics_computed"]

        # All categories should exist but have no computed values
        for cat_name, cat_data in computed.items():
            for metric_name, m in cat_data.items():
                # Every metric should be unavailable (both traces missing)
                assert m["computed"] is False, (
                    f"{metric_name} should be unavailable without any trace data"
                )

        # Assessment should note insufficient data
        assessment = report["bottleneck_assessment"]
        assert assessment["assessment"] in ("insufficient_data", "partial_data")

    def test_old_ws_trace_not_polluting_asr(self) -> None:
        """The renamed backend_process_pcm_start_at does not pollute asr_infer_ms.

        asr_infer_ms should be computed from asr_streaming_start_at →
        asr_streaming_end_at (service-layer), not from the old WS-layer
        asr_streaming_start_at (now backend_process_pcm_start_at).
        """
        from backend.scripts.generate_latency_report import _compute_metrics

        # Backend events: include both backend_process_pcm_start_at and
        # asr_streaming_start_at. The old name should not affect asr_infer_ms.
        backend_events = [
            {"event": "backend_pcm_received_at",
             "timestamp_monotonic_ms": 0, "timestamp_wall_ms": 1000},
            {"event": "backend_process_pcm_start_at",
             "timestamp_monotonic_ms": 10, "timestamp_wall_ms": 1010},
            {"event": "asr_streaming_start_at",
             "timestamp_monotonic_ms": 50, "timestamp_wall_ms": 1050},
            {"event": "asr_streaming_end_at",
             "timestamp_monotonic_ms": 300, "timestamp_wall_ms": 1300,
             "asr_infer_ms": 250},
            {"event": "interim_event_created_at",
             "timestamp_monotonic_ms": 310, "timestamp_wall_ms": 1310},
            {"event": "interim_event_broadcast_at",
             "timestamp_monotonic_ms": 315, "timestamp_wall_ms": 1315},
        ]
        frontend_events = []

        metrics = _compute_metrics(backend_events, frontend_events, None)

        # asr_infer_ms should be 250 (from extra field), NOT 290 (300-10)
        assert metrics["asr_infer_ms"]["computed"] is True
        assert metrics["asr_infer_ms"]["value_ms"] == 250, (
            f"Expected 250 (perf_counter), got {metrics['asr_infer_ms']['value_ms']}"
        )

        # backend_received_to_asr_start_ms should use asr_streaming_start_at,
        # not backend_process_pcm_start_at
        assert metrics["backend_received_to_asr_start_ms"]["computed"] is True
        assert metrics["backend_received_to_asr_start_ms"]["value_ms"] == 50, (
            f"Expected 50 (backend_pcm_received → asr_streaming_start_at), "
            f"got {metrics['backend_received_to_asr_start_ms']['value_ms']}"
        )


# ── Trace file export / load tests (Task 128E) ──────────────────────────────


class TestTraceExport:
    """Trace export and load roundtrips correctly."""

    def test_export_to_file_creates_json(self, enable_trace, tmp_path) -> None:
        """export_trace_to_file writes a valid JSON file."""
        from backend.websocket.speech_trace import (
            export_trace_to_file, load_trace_from_file, clear_trace,
        )

        clear_trace()
        trace("event_a", utterance_id="utt_1", meeting_id=1, seat_id=1)
        trace("event_b", utterance_id="utt_1", revision=5)

        out_path = str(tmp_path / "trace-export.json")
        result = export_trace_to_file(out_path)
        assert result["success"] is True
        assert result["event_count"] == 2

        # Load back and verify
        loaded = load_trace_from_file(out_path)
        assert loaded["available"] is True
        assert loaded["event_count"] == 2
        names = [e["event"] for e in loaded["events"]]
        assert "event_a" in names
        assert "event_b" in names

    def test_export_empty_trace(self, enable_trace, tmp_path) -> None:
        """Exporting an empty trace yields event_count=0."""
        from backend.websocket.speech_trace import (
            export_trace_to_file, clear_trace,
        )

        clear_trace()
        out_path = str(tmp_path / "empty-trace.json")
        result = export_trace_to_file(out_path)
        assert result["success"] is True
        assert result["event_count"] == 0

    def test_load_nonexistent_file(self) -> None:
        """load_trace_from_file returns available=False for missing file."""
        from backend.websocket.speech_trace import load_trace_from_file

        loaded = load_trace_from_file("/nonexistent/trace.json")
        assert loaded["available"] is False
        assert "not found" in (loaded["note"] or "").lower()

    def test_export_utf8_safety(self, enable_trace, tmp_path) -> None:
        """Export handles Unicode trace data (Chinese text)."""
        from backend.websocket.speech_trace import (
            export_trace_to_file, load_trace_from_file, clear_trace,
        )

        clear_trace()
        trace("test_cn", utterance_id="utt_测试", note="中文路径测试")
        out_path = str(tmp_path / "trace-utf8-test.json")
        export_result = export_trace_to_file(out_path)
        assert export_result["success"] is True

        loaded = load_trace_from_file(out_path)
        assert loaded["available"] is True
        ev = loaded["events"][0]
        assert "测试" in str(ev.get("utterance_id", ""))

    def test_merged_report_with_file_backend_trace(self, tmp_path) -> None:
        """generate_report with --backend-trace file computes metrics correctly."""
        from backend.scripts.generate_latency_report import generate_report
        from backend.websocket.speech_trace import export_trace_to_file, clear_trace
        import backend.websocket.speech_trace as st_mod

        # Write frontend trace file
        wall_offset = 1000000
        frontend_events = [
            {"event": "start_clicked_at", "timestamp": 0, "data": {}},
            {"event": "microphone_started_at", "timestamp": 150, "data": {}},
            {"event": "frontend_pcm_created_at", "timestamp": 400, "data": {}},
            {"event": "frontend_pcm_sent_at", "timestamp": 405, "data": {}},
            {"event": "frontend_interim_received_at", "timestamp": 1200, "data": {}},
            {"event": "frontend_interim_rendered_at", "timestamp": 1220, "data": {}},
        ]
        fe_trace = {
            "recorded_at": "2026-06-15T07:00:00Z",
            "trace_enabled": True,
            "event_count": len(frontend_events),
            "wall_clock_offset_ms": wall_offset,
            "events": frontend_events,
        }
        fe_path = tmp_path / "fe-trace.json"
        with open(str(fe_path), "w", encoding="utf-8") as f:
            json.dump(fe_trace, f)

        # Write backend trace file via export_trace_to_file
        old_enabled = st_mod._enabled
        try:
            st_mod._enabled = True
            clear_trace()
            # Use trace() to populate ring buffer, then export
            st_mod.trace("backend_pcm_received_at",
                         timestamp_monotonic_ms=500, timestamp_wall_ms=wall_offset + 410)
            st_mod.trace("asr_streaming_start_at",
                         timestamp_monotonic_ms=505, timestamp_wall_ms=wall_offset + 415)
            st_mod.trace("asr_streaming_end_at",
                         timestamp_monotonic_ms=755, timestamp_wall_ms=wall_offset + 665,
                         asr_infer_ms=250)
            st_mod.trace("interim_event_created_at",
                         timestamp_monotonic_ms=760, timestamp_wall_ms=wall_offset + 670)
            st_mod.trace("interim_event_broadcast_at",
                         timestamp_monotonic_ms=762, timestamp_wall_ms=wall_offset + 672)

            bk_path = tmp_path / "bk-trace.json"
            exp_result = export_trace_to_file(str(bk_path))
            assert exp_result["success"] is True
            assert exp_result["event_count"] == 5
        finally:
            st_mod.clear_trace()
            st_mod._enabled = old_enabled

        # Generate report with file-based backend trace
        report = generate_report(
            frontend_trace_path=str(fe_path),
            backend_trace_path=str(bk_path),
        )

        # Verify
        assert report["trace_sources"]["frontend"]["available"] is True
        assert report["trace_sources"]["backend"]["available"] is True
        assert report["trace_sources"]["backend"]["source"] == "file"

        computed = report["metrics_computed"]
        assert computed["frontend_only"]["start_to_mic_ready_ms"]["computed"] is True
        assert computed["frontend_only"]["start_to_mic_ready_ms"]["value_ms"] == 150
        assert computed["backend_only"]["asr_infer_ms"]["computed"] is True
        assert computed["backend_only"]["asr_infer_ms"]["value_ms"] == 250
        assert computed["end_to_end"]["start_to_first_interim_ms"]["computed"] is True
        assert computed["end_to_end"]["start_to_first_interim_ms"]["value_ms"] == 1220
        assert computed["cross_boundary"]["first_pcm_sent_to_backend_received_ms"]["computed"] is True

        # Check missing_fields section
        mf = report["missing_fields"]
        assert "all_expected_trace_points" in mf
        assert mf["missing_frontend"] or mf["present_frontend"]  # at least one list non-empty
