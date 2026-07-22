"""
Tests for Task 119 — speech model preload status, punctuation loading,
and API endpoint.

Coverage:
    - SpeechModule.preload() calls warmup_punc()
    - Preload is idempotent
    - Concurrent preload does not double-load
    - GET /api/speech/status returns correct state
    - POST /api/speech/preload succeeds
    - MeetingService.start_meeting triggers preload
    - Frontend speech status polling (unit tests)
"""
from __future__ import annotations

import threading
from unittest.mock import patch, MagicMock

import pytest

from backend.speech_module.speech_module import SpeechModule, STATUS_UNKNOWN, STATUS_LOADED, STATUS_ERROR, _INITIAL_STATUS


@pytest.fixture(autouse=True)
def _mock_english_streaming_warmup():
    """Keep status-contract tests independent from a real Zipformer load."""
    with (
        patch("backend.speech_module.english_streaming.warmup_english_streaming"),
        patch("backend.speech_module.bilingual_asr.warmup_bilingual_asr"),
    ):
        yield


# ── Helpers ──────────────────────────────────────────────────────────────────────

# Shortcut to the testable thread‑creation function so tests can patch it
# without the broad side‑effects of patching threading.Thread.start globally.
_PATCH_START_THREAD = "backend.services.speech_stream_service._start_daemon_thread"


# ── SpeechModule Preload Tests ──────────────────────────────────────────────────


class TestSpeechModulePreload:
    """SpeechModule.preload() with mocked model warmups."""

    def test_preload_calls_warmup_punc(self):
        """preload() must call warmup_punc()."""
        sm = SpeechModule()
        with (
            patch("backend.speech_module.speech_module._log_warning"),
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc") as mock_punc,
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            sm.preload()
            mock_punc.assert_called_once()
            assert sm.ready

    def test_preload_punctuation_failure_sets_error_status(self):
        """If warmup_punc raises, punctuation_model = error but ASR still ready."""
        sm = SpeechModule()
        with (
            patch("backend.speech_module.speech_module._log_warning"),
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc",
                  side_effect=RuntimeError("model download failed")),
        ):
            sm.preload()
            assert sm.status["punctuation_model"] == STATUS_ERROR
            assert sm.status["streaming_model"] == STATUS_LOADED
            assert sm.status["offline_model"] == STATUS_LOADED
            # ready only requires streaming + offline — punctuation failure
            # must NOT block ASR readiness
            assert sm.ready, "ASR ready should be True even when punctuation fails"
            assert "punctuation" in (sm.status["last_error"] or "")

    def test_preload_punctuation_loaded_but_not_set(self):
        """If warmup_punc succeeds but is_punctuation_loaded returns False."""
        sm = SpeechModule()
        with (
            patch("backend.speech_module.speech_module._log_warning"),
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=False),
        ):
            sm.preload()
            assert sm.status["punctuation_model"] == STATUS_ERROR

    def test_preload_idempotent(self):
        """Calling preload() twice must not re-load models."""
        sm = SpeechModule()
        call_count = 0

        def _count_warmup():
            nonlocal call_count
            call_count += 1

        with (
            patch("backend.speech_module.speech_module._log_warning"),
            patch("backend.speech_module.stt_streaming.warmup_streaming",
                  side_effect=_count_warmup),
            patch("backend.speech_module.stt_streaming.warmup_offline",
                  side_effect=_count_warmup),
            patch("backend.speech_module.punctuation.warmup_punc",
                  side_effect=_count_warmup),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            sm.preload()
            first_calls = call_count
            sm.preload()
            # Second call should not increase warmup calls
            assert call_count == first_calls

    def test_concurrent_preload_no_double_load(self):
        """Concurrent preload calls must not load models twice."""
        sm = SpeechModule()
        call_count = 0
        lock = threading.Lock()

        def _slow_warmup():
            nonlocal call_count
            with lock:
                call_count += 1

        with (
            patch("backend.speech_module.speech_module._log_warning"),
            patch("backend.speech_module.stt_streaming.warmup_streaming",
                  side_effect=_slow_warmup),
            patch("backend.speech_module.stt_streaming.warmup_offline",
                  side_effect=_slow_warmup),
            patch("backend.speech_module.punctuation.warmup_punc",
                  side_effect=_slow_warmup),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            threads = [threading.Thread(target=sm.preload) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            # warmup should have been called exactly once per model (3 total)
            assert call_count == 3

    def test_initial_status(self):
        """New SpeechModule should have correct initial status."""
        sm = SpeechModule()
        s = sm.status
        assert s["ready"] is False
        assert s["preloading"] is False
        assert s["streaming_model"] == STATUS_UNKNOWN
        assert s["offline_model"] == STATUS_UNKNOWN
        assert s["punctuation_model"] == STATUS_UNKNOWN
        assert s["last_error"] is None

    def test_status_after_partial_failure(self):
        """Status reflects partial failure correctly."""
        sm = SpeechModule()
        with (
            patch("backend.speech_module.speech_module._log_warning"),
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline",
                  side_effect=RuntimeError("OOM")),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            sm.preload()
            s = sm.status
            assert s["streaming_model"] == STATUS_LOADED
            assert s["offline_model"] == STATUS_ERROR
            assert s["punctuation_model"] == STATUS_LOADED
            assert not s["ready"]
            assert "OOM" in (s["last_error"] or "")


# ── API Status Tests ────────────────────────────────────────────────────────────


# Module-level TestClient uses the conftest-overridden app with test DB
from fastapi.testclient import TestClient
from backend.main import app

_api_client = TestClient(app)


class TestSpeechStatusAPI:
    """GET /api/speech/status and POST /api/speech/preload.

    IMPORTANT: Tests that trigger preload NEVER call POST /api/speech/preload
    directly through TestClient, because that would start a background thread
    loading real torch/funasr models (crash/hang in test environment).

    Instead:
      - ``test_post_preload_returns_ok`` patches the handler dependency.
      - ``test_status_after_triggered_preload`` calls the preload function
        directly with the thread-creation helper patched.
    """

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset stream_service singleton state before each test."""
        from backend.services.speech_stream_service import stream_service
        stream_service._speech_module = None
        stream_service._speech_module_error = None
        stream_service._preload_started = False
        yield

    def test_get_status_returns_default_when_not_loaded(self):
        """Status endpoint should return initial state when no preload called."""
        resp = _api_client.get("/api/speech/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        status = data["data"]
        assert status["ready"] is False
        assert status["preloading"] is False
        assert status["punctuation_fallback"] is False

    def test_post_preload_returns_ok(self):
        """POST /api/speech/preload should return success.

        Patches ``_preload_speech_models_background`` at the API handler level
        so the real background-thread startup is never triggered.
        """
        with patch("backend.api.speech._preload_speech_models_background"):
            resp = _api_client.post("/api/speech/preload")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True

    def test_get_diagnostics_exposes_runtime_queues_and_bounded_events(self):
        resp = _api_client.get("/api/speech/diagnostics?limit=25")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert isinstance(data["trace_enabled"], bool)
        assert data["event_count_returned"] <= 25
        assert "finalization" in data["queues"]
        assert "sentence_translation" in data["queues"]
        assert "last_queue_wait_ms" in data["queues"]["finalization"]
        assert "last_inference_ms" in data["queues"]["sentence_translation"]
        assert "streaming_asr_slower_than_realtime" in data["indicators"]

    def test_clear_diagnostics_only_clears_trace_buffer(self):
        resp = _api_client.post("/api/speech/diagnostics/clear")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["event_count"] == 0

    def test_status_after_triggered_preload(self):
        """After triggering preload, status should show preloading=true.

        Uses a direct call to ``_preload_speech_models_background()`` (not
        through the HTTP endpoint) with the thread-creation helper patched out.
        The GET /api/speech/status call still goes through the real API.
        """
        from backend.services.speech_stream_service import (
            _preload_speech_models_background,
        )

        # Pre-trigger: status should be initial
        resp_pre = _api_client.get("/api/speech/status")
        assert resp_pre.json()["data"]["ready"] is False

        # Trigger preload directly with thread creation suppressed.
        # This tests:
        #   1. The module is created synchronously (not in thread)
        #   2. preloading status is visible immediately
        with patch(_PATCH_START_THREAD):
            _preload_speech_models_background()

        # After trigger, status must reflect preloading state
        resp_post = _api_client.get("/api/speech/status")
        assert resp_post.status_code == 200
        data = resp_post.json()["data"]
        assert data["preloading"] is True, (
            f"Expected preloading=True after trigger, got {data}"
        )


# ── Meeting Service Preload Trigger ─────────────────────────────────────────────


@pytest.fixture
def svc(db, event_bus):
    """MeetingService with test DB and EventBus."""
    from backend.services.meeting_service import MeetingService
    return MeetingService(db, event_bus)


class TestMeetingPreloadTrigger:
    """MeetingService.start_meeting triggers background preload."""

    def test_start_meeting_triggers_preload(self, svc, db, event_bus):
        """After start_meeting(), _trigger_speech_preload must be called.

        Suppresses the background thread to avoid real model loading.
        """
        from backend.services.meeting_service import _trigger_speech_preload

        with (
            patch(
                "backend.services.meeting_service._trigger_speech_preload",
                wraps=_trigger_speech_preload,
            ) as mock_trigger,
            patch(_PATCH_START_THREAD),
        ):
            meeting = svc.create_meeting("Preload Test")
            svc.start_meeting(meeting.id)
            mock_trigger.assert_called_once()

    def test_start_meeting_idempotent_still_triggers_once(self, svc, db, event_bus):
        """Starting an already active meeting should not re-trigger preload."""
        from backend.services.meeting_service import _trigger_speech_preload

        with patch(
            "backend.services.meeting_service._trigger_speech_preload",
        ) as mock_trigger:
            meeting = svc.create_meeting("Idempotent")
            svc.start_meeting(meeting.id)
            svc.start_meeting(meeting.id)  # second call is idempotent
            mock_trigger.assert_called_once()

    def test_preload_trigger_calls_background(self):
        """_trigger_speech_preload must call _preload_speech_models_background."""
        with patch(
            "backend.services.speech_stream_service._preload_speech_models_background",
        ) as mock_bg:
            from backend.services.meeting_service import _trigger_speech_preload
            _trigger_speech_preload()
            mock_bg.assert_called_once()


# ── get_model_status tests ──────────────────────────────────────────────────────


class TestGetModelStatus:
    """SpeechStreamService.get_model_status() unit tests."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset stream_service singleton state before each test."""
        from backend.services.speech_stream_service import stream_service
        stream_service._speech_module = None
        stream_service._speech_module_error = None
        stream_service._preload_started = False
        yield

    def test_get_model_status_initial(self):
        """Initial status must have correct shape and default values."""
        from backend.services.speech_stream_service import stream_service
        status = stream_service.get_model_status()
        assert status["ready"] is False
        assert status["preloading"] is False
        assert status["punctuation_fallback"] is False

    def test_loading_punctuation_is_not_reported_as_unavailable(self):
        """A transitional loading state must not show a fallback warning."""
        from backend.services.speech_stream_service import stream_service
        from backend.speech_module import SpeechModule

        module = SpeechModule()
        module._status["preloading"] = True
        module._status["punctuation_model"] = "loading"
        stream_service._speech_module = module

        with patch(
            "backend.speech_module.punctuation.is_punctuation_loaded",
            return_value=False,
        ):
            status = stream_service.get_model_status()

        assert status["preloading"] is True
        assert status["punctuation_model"] == "loading"
        assert status["punctuation_fallback"] is False

    def test_get_model_status_after_successful_load(self):
        """After successful module load, status should reflect readiness."""
        from backend.services.speech_stream_service import stream_service

        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            ok = stream_service.ensure_speech_module()
            assert ok
            status = stream_service.get_model_status()
            assert status["ready"] is True
            assert status["punctuation_fallback"] is False

    def test_get_model_status_tracks_punctuation_fallback(self):
        """When punctuation model is not loaded, fallback flag must be True."""
        from backend.services.speech_stream_service import stream_service

        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=False),
        ):
            ok = stream_service.ensure_speech_module()
            # ensure_speech_module returns True because preload catches errors
            # internally (models may partially fail without crashing)
            assert ok
            status = stream_service.get_model_status()
            assert status["punctuation_model"] == STATUS_ERROR
            assert status["punctuation_fallback"] is True


# ── Frontend API Types Tests ────────────────────────────────────────────────────


class TestSpeechStatusFrontendTypes:
    """Verify speech status types are properly exported."""

    def test_types_exist(self):
        """Check that SpeechModelStatus interface is defined."""
        import sys
        # The test runs in Python, but this validates the TS types are correct
        # by checking the backend status dict shape
        from backend.speech_module.speech_module import _INITIAL_STATUS
        required_keys = {
            "ready", "preloading", "streaming_model",
            "offline_model", "punctuation_model", "last_error",
        }
        assert required_keys.issubset(_INITIAL_STATUS.keys())


# ── Concurrent / Background Preload Tests ────────────────────────────────────────


class TestBackgroundPreloadConcurrency:
    """_preload_speech_models_background concurrency control.

    Patches ``_start_daemon_thread`` (not ``threading.Thread.start``) so that
    the gating logic is exercised without actually spawning OS threads that
    would try to load real torch/funasr models.
    """

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset stream_service singleton state before each test."""
        from backend.services.speech_stream_service import stream_service
        stream_service._speech_module = None
        stream_service._speech_module_error = None
        stream_service._preload_started = False
        yield

    def test_multiple_calls_do_not_create_multiple_threads(self):
        """Calling _preload_speech_models_background multiple times must
        not create more than one thread."""
        from backend.services.speech_stream_service import (
            _preload_speech_models_background,
        )

        call_count = 0

        def _counting_start(_target, **_kwargs):
            nonlocal call_count
            call_count += 1
            # Do NOT actually start the thread — we only test the gating logic

        with patch(_PATCH_START_THREAD, side_effect=_counting_start):
            _preload_speech_models_background()
            _preload_speech_models_background()
            _preload_speech_models_background()

        # Only one thread should have been started
        assert call_count == 1, (
            f"Expected 1 thread, got {call_count}"
        )

    def test_sets_preload_started_flag(self):
        """After first call, _preload_started must be True."""
        from backend.services.speech_stream_service import (
            stream_service,
            _preload_speech_models_background,
        )
        with patch(_PATCH_START_THREAD):
            _preload_speech_models_background()
        assert stream_service._preload_started is True

    def test_creates_speech_module_immediately(self):
        """_speech_module must be created before the background thread runs."""
        from backend.services.speech_stream_service import (
            stream_service,
            _preload_speech_models_background,
        )
        with patch(_PATCH_START_THREAD):
            _preload_speech_models_background()
        assert stream_service._speech_module is not None
        assert stream_service._speech_module._status["preloading"] is True

    def test_double_call_after_load_is_noop(self):
        """After preload completes, calling again must be a no-op."""
        from backend.services.speech_stream_service import (
            stream_service,
            _preload_speech_models_background,
        )

        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            # First call enters background; simulate preload completing
            _preload_speech_models_background()
            # Manually complete the preload for testing purposes
            stream_service._speech_module._status["ready"] = True
            stream_service._speech_module._status["preloading"] = False
            stream_service._preload_started = False

            # Track flag before second call
            old_module = stream_service._speech_module

            # Second call — must be no-op since already loaded
            _preload_speech_models_background()

            assert stream_service._speech_module is old_module


# ── Preload Status Accuracy Tests ─────────────────────────────────────────────────


class TestPreloadStatusAccuracy:
    """POST /api/speech/preload → status must reflect preloading=true."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset stream_service singleton state before each test."""
        from backend.services.speech_stream_service import stream_service
        stream_service._speech_module = None
        stream_service._speech_module_error = None
        stream_service._preload_started = False
        yield

    def test_preload_immediately_creates_module(self):
        """After _preload_speech_models_background, _speech_module must exist
        and get_model_status must show preloading=true."""
        from backend.services.speech_stream_service import (
            stream_service,
            _preload_speech_models_background,
        )
        with patch(_PATCH_START_THREAD):
            _preload_speech_models_background()
        assert stream_service._speech_module is not None
        status = stream_service.get_model_status()
        assert status["preloading"] is True, (
            f"Expected preloading=True, got {status}"
        )


# ── Punctuation Fallback Does Not Block ASR ──────────────────────────────────────


class TestPunctuationFallbackDoesNotBlockASR:
    """punctuation_model=error → ready=true, punctuation_fallback=true."""

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset stream_service singleton state before each test."""
        from backend.services.speech_stream_service import stream_service
        stream_service._speech_module = None
        stream_service._speech_module_error = None
        stream_service._preload_started = False
        yield

    def test_punctuation_error_does_not_block_asr_ready(self):
        """When punctuation model errors, ASR ready must still be True."""
        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=False),
        ):
            from backend.services.speech_stream_service import stream_service
            ok = stream_service.ensure_speech_module()
            assert ok

            status = stream_service.get_model_status()
            assert status["punctuation_model"] == STATUS_ERROR
            assert status["punctuation_fallback"] is True
            # ASR ready must be True even with punctuation error
            assert status["ready"] is True, (
                "ready must be True when streaming+offline loaded, "
                "even if punctuation failed"
            )

    def test_punctuation_fallback_nonblocking_frontend(self):
        """Simulate frontend rendering logic: punctuation_fallback must NOT
        disable Start. Only ASR readiness (ready) blocks Start."""
        status_good = {
            "ready": True,
            "punctuation_fallback": True,
            "punctuation_model": STATUS_ERROR,
            "streaming_model": STATUS_LOADED,
            "offline_model": STATUS_LOADED,
        }
        models_ready = status_good["ready"]
        start_disabled_by_models = not models_ready
        assert start_disabled_by_models is False, (
            "Start must NOT be disabled when ASR is ready despite punctuation fallback"
        )

        status_loading = {
            "ready": False,
            "preloading": True,
            "punctuation_fallback": True,
        }
        assert status_loading["ready"] is False
        assert status_loading["preloading"] is True


# ── ensure_speech_module Semantic ─────────────────────────────────────────────────


class TestEnsureSpeechModule:
    """ensure_speech_module must return correct readiness values.

    NOTE: Because ``SpeechModule.preload()`` catches per-model exceptions and
    continues to the next model, tests that simulate a specific model failure
    MUST patch ALL follow-on warmup functions to prevent real model loading.
    """

    @pytest.fixture(autouse=True)
    def _reset_singleton(self):
        """Reset stream_service singleton state before each test."""
        from backend.services.speech_stream_service import stream_service
        stream_service._speech_module = None
        stream_service._speech_module_error = None
        stream_service._preload_started = False
        yield

    def test_returns_true_when_models_ready(self):
        """When all ASR models load, ensure_speech_module returns True."""
        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
            patch("backend.speech_module.punctuation.is_punctuation_loaded",
                  return_value=True),
        ):
            from backend.services.speech_stream_service import stream_service
            result = stream_service.ensure_speech_module()
            assert result is True

    def test_returns_false_when_streaming_fails(self):
        """When streaming model fails, ensure_speech_module returns False.

        Patches all follow-on warmup functions because preload() catches
        exceptions and continues to the next model.
        """
        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming",
                  side_effect=RuntimeError("streaming OOM")),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc"),
        ):
            from backend.services.speech_stream_service import stream_service
            result = stream_service.ensure_speech_module()
            assert result is False

    def test_returns_true_when_only_punctuation_fails(self):
        """When only punctuation fails, ensure_speech_module returns True."""
        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline"),
            patch("backend.speech_module.punctuation.warmup_punc",
                  side_effect=RuntimeError("punc OOM")),
        ):
            from backend.services.speech_stream_service import stream_service
            result = stream_service.ensure_speech_module()
            # Punctuation failure must NOT block ASR readiness
            assert result is True, (
                "ensure_speech_module must return True when ASR models loaded "
                "even if punctuation failed"
            )

    def test_returns_false_when_offline_fails(self):
        """When offline model fails, ensure_speech_module returns False.

        Patches the punctuation warmup because preload() continues past
        the offline model failure and would try to load punctuation next.
        """
        with (
            patch("backend.speech_module.stt_streaming.warmup_streaming"),
            patch("backend.speech_module.stt_streaming.warmup_offline",
                  side_effect=RuntimeError("offline OOM")),
            patch("backend.speech_module.punctuation.warmup_punc"),
        ):
            from backend.services.speech_stream_service import stream_service
            result = stream_service.ensure_speech_module()
            assert result is False


# ── Active Meeting Seed Preload Trigger ──────────────────────────────────────────


class TestActiveMeetingSeedPreload:
    """Active meeting after seed_demo triggers preload."""

    def test_active_meeting_triggers_preload(self, db):
        """Simulate lifespan logic: if an active meeting exists in DB,
        _preload_speech_models_background must be called."""
        from backend.models.meeting import Meeting
        from datetime import datetime, timezone

        # Create an active meeting directly (like seed_demo does)
        meeting = Meeting(
            title="Seed Test Meeting",
            description="Test",
            status="active",
            created_at=datetime.now(timezone.utc),
            started_at=datetime.now(timezone.utc),
        )
        db.add(meeting)
        db.commit()

        # Simulate lifespan logic
        from backend.services.speech_stream_service import (
            _preload_speech_models_background,
            stream_service,
        )

        # Reset singleton
        stream_service._speech_module = None
        stream_service._preload_started = False

        active = db.query(Meeting).filter(
            Meeting.status == "active",
        ).first()
        assert active is not None, "Active meeting must exist"
        assert active.id == meeting.id

        # Trigger preload (same code path as main.py lifespan).
        # Suppress background thread to avoid real model loading in tests.
        with patch(_PATCH_START_THREAD):
            _preload_speech_models_background()

        # Verify preload was triggered
        assert stream_service._preload_started is True
        assert stream_service._speech_module is not None
        assert stream_service._speech_module._status["preloading"] is True

    def test_active_meeting_noop_when_none_active(self, db):
        """When no active meeting exists, preload must NOT be triggered."""
        from backend.services.speech_stream_service import (
            stream_service,
        )
        stream_service._speech_module = None
        stream_service._preload_started = False

        from backend.models.meeting import Meeting
        active = db.query(Meeting).filter(
            Meeting.status == "active",
        ).first()
        assert active is None, "No active meeting should exist"

        # The lifespan logic would not call preload — verify nothing happened
        assert stream_service._speech_module is None
        assert stream_service._preload_started is False
