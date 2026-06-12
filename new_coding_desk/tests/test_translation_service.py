"""
Unit tests for TranslationService — Phase 4 additions.

Covers:
    - process_final_array with real ASR
    - process_final_array writes utterance_id and source_type
    - translation_final payload contains required fields
    - ASR empty result raises ValidationError
    - Idempotent column migration
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from sqlalchemy import inspect, text

from backend.database import Base, SessionLocal
from backend.events.event_bus import EventBus
from backend.exceptions import ValidationError
from backend.services.translation_model_service import (
    is_translation_model_enabled,
    NOT_AVAILABLE,
)
from backend.services.translation_service import TranslationService
from tests.conftest import TEST_ENGINE


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function", autouse=True)
def _reset_db():
    """Drop/recreate tables before each test."""
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    # Also apply Phase 4 migration so translation_records has new columns
    from backend.migrations import ensure_translation_record_columns
    ensure_translation_record_columns(TEST_ENGINE)

    yield

    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture(scope="function")
def db():
    """Per-test DB session."""
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def event_bus():
    """Fresh EventBus per test."""
    bus = EventBus()
    yield bus


@pytest.fixture(scope="function")
def tsvc(db, event_bus):
    """TranslationService instance."""
    return TranslationService(db, event_bus)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_test_audio(duration_s: float = 2.0, sr: int = 16000) -> np.ndarray:
    """Generate a simple test tone (440Hz sine wave).

    Note: this produces empty ASR results (not speech).
    For the real ASR test, real speech data is loaded from fixture.
    """
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    return (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)


def _load_real_speech_audio() -> np.ndarray:
    """Load the real speech PCM16 fixture as a float32 array."""
    import os
    fixture_path = os.path.join(
        os.path.dirname(__file__), "fixtures", "speech_sample.pcm",
    )
    with open(fixture_path, "rb") as f:
        raw = f.read()
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestProcessFinalArray:
    """TranslationService.process_final_array — Phase 4."""

    def _ensure_speech_available(self, tsvc):
        """Preload speech module; skip if unavailable."""
        try:
            tsvc._ensure_preloaded()
        except ValidationError:
            pytest.skip("Speech models not loaded")

    def test_writes_utterance_id_and_source_type(self, tsvc):
        """process_final_array writes utterance_id and source_type to DB."""
        self._ensure_speech_available(tsvc)
        audio = _load_real_speech_audio()

        record = tsvc.process_final_array(
            audio=audio, sr=16000,
            meeting_id=1, seat_id=1,
            utterance_id="utt_1_1_000001",
            source_type="speech_ws",
        )

        assert record.utterance_id == "utt_1_1_000001"
        assert record.source_type == "speech_ws"
        assert record.meeting_id == 1
        assert record.seat_id == 1
        assert record.source_text != ""
        # Phase 02: persisted source_text should contain punctuation
        assert any(p in record.source_text for p in "。？！，.!?"), (
            f"DB source_text lacks punctuation: '{record.source_text}'"
        )
        assert record.id > 0

    def test_publishes_translation_final_event(self, tsvc, event_bus):
        """process_final_array publishes TranslationFinalEvent with full payload."""
        self._ensure_speech_available(tsvc)
        audio = _load_real_speech_audio()

        received_events = []

        def _capture(event):
            received_events.append(event)

        event_bus.subscribe("translation_final", _capture)

        tsvc.process_final_array(
            audio=audio, sr=16000,
            meeting_id=1, seat_id=1,
            utterance_id="utt_1_1_000002",
            source_type="speech_ws",
        )

        assert len(received_events) == 1
        event = received_events[0]
        assert event.event_name == "translation_final"
        assert event.meeting_id == 1

        payload = event.payload
        assert "translation_id" in payload
        assert payload["utterance_id"] == "utt_1_1_000002"
        assert payload["seat_id"] == 1
        assert isinstance(payload["source_text"], str)
        assert len(payload["source_text"]) > 0
        # Phase 02: final event payload source_text contains punctuation
        assert any(p in payload["source_text"] for p in "。？！，.!?"), (
            f"final event source_text lacks punctuation: "
            f"'{payload['source_text']}'"
        )
        assert isinstance(payload["translated_text"], str)
        # Task 123: if real translation model enabled, verify non-placeholder
        if is_translation_model_enabled():
            from backend.services.speech_stream_service import stream_service
            if stream_service.ensure_speech_module():
                assert payload["translated_text"] != NOT_AVAILABLE
        assert payload["source_type"] == "speech_ws"

    def test_asr_empty_result_raises_error(self, tsvc):
        """process_final_array with silence/tone raises ASR_EMPTY_RESULT."""
        self._ensure_speech_available(tsvc)
        audio = _make_test_audio(duration_s=2.0)

        with pytest.raises(ValidationError) as excinfo:
            tsvc.process_final_array(
                audio=audio, sr=16000,
                meeting_id=1, seat_id=1,
                utterance_id="utt_1_1_000003",
                source_type="speech_ws",
            )

        assert excinfo.value.error_code == "ASR_EMPTY_RESULT", (
            f"Expected ASR_EMPTY_RESULT, got error_code={excinfo.value.error_code}: "
            f"{excinfo.value.message}"
        )

    def test_records_without_explicit_source_type(self, tsvc):
        """Records without explicit source_type get the default 'speech_ws'."""
        # Insert a record directly (skip process_final_array)
        from backend.repositories.translation_repository import TranslationRepository

        repo = TranslationRepository(tsvc.db)
        record = repo.create(
            meeting_id=1, seat_id=2,
            source_lang="zh", target_lang="en",
            source_text="默认 source_type 测试",
            translated_text="Default source_type test",
            utterance_id=None,
        )

        # server_default should set it to 'speech_ws'
        assert record.utterance_id is None
        assert record.source_type == "speech_ws"

        # Verify it's still queryable
        records = repo.list_by_meeting(1)
        assert len(records) >= 1
        assert records[0].source_text == "默认 source_type 测试"

    def test_record_visible_via_translation_api(self, tsvc):
        """Record created via process_final_array is returned by get_history."""
        self._ensure_speech_available(tsvc)
        audio = _load_real_speech_audio()

        tsvc.process_final_array(
            audio=audio, sr=16000,
            meeting_id=1, seat_id=1,
            utterance_id="utt_1_1_000004",
            source_type="speech_ws",
        )

        history = tsvc.get_history(meeting_id=1)
        assert len(history) >= 1
        latest = history[0]
        assert latest.utterance_id == "utt_1_1_000004"
        assert latest.source_type == "speech_ws"

    def test_process_final_array_with_mocked_translation_model(self, tsvc, event_bus, monkeypatch):
        """Mock real translation model → DB and payload contain mocked translated_text.

        This test monkeypatches the translation layer at the service level so
        that the real OPUS-MT model is never loaded. Instead, a fixed string is
        returned.

        Verifies:
            - translated_text == mocked value in DB record
            - translated_text == mocked value in translation_final payload
            - source_lang/target_lang still correctly detected as zh/en
        """
        # Arrange: monkeypatch the two entry points used by TranslationService
        import backend.services.translation_service as ts

        monkeypatch.setattr(ts, "is_translation_model_enabled", lambda: True)

        mock_result = "Hello, welcome to SmartDesk."

        class _MockModelService:
            def translate(self, text: str) -> str:
                return mock_result

        monkeypatch.setattr(
            ts.TranslationModelService, "get_instance",
            lambda: _MockModelService(),
        )

        # Ensure speech ASR is loaded
        self._ensure_speech_available(tsvc)

        # Subscribe to capture the event
        received_events = []

        def _capture(event):
            received_events.append(event)

        event_bus.subscribe("translation_final", _capture)

        # Act
        audio = _load_real_speech_audio()
        record = tsvc.process_final_array(
            audio=audio, sr=16000,
            meeting_id=1, seat_id=1,
            utterance_id="utt_1_1_000010",
            source_type="speech_ws",
        )

        # Assert DB
        assert record.translated_text == mock_result, (
            f"DB translated_text expected '{mock_result}', "
            f"got '{record.translated_text}'"
        )
        assert record.source_lang == "zh"
        assert record.target_lang == "en"

        # Assert event payload
        assert len(received_events) == 1, (
            f"Expected 1 event, got {len(received_events)}"
        )
        payload = received_events[0].payload
        assert payload["translated_text"] == mock_result, (
            f"Event translated_text expected '{mock_result}', "
            f"got '{payload['translated_text']}'"
        )
        assert payload["source_lang"] == "zh"
        assert payload["target_lang"] == "en"
        assert payload["utterance_id"] == "utt_1_1_000010"


class TestMigrationIdempotency:
    """SQLite column migration is idempotent."""

    def test_migration_runs_twice_safely(self):
        """ensure_translation_record_columns can be called twice."""
        from backend.migrations import ensure_translation_record_columns

        # First call
        ensure_translation_record_columns(TEST_ENGINE)

        # Second call — must not raise
        ensure_translation_record_columns(TEST_ENGINE)

        # Verify columns exist
        inspector = inspect(TEST_ENGINE)
        columns = {c["name"] for c in inspector.get_columns("translation_records")}
        assert "utterance_id" in columns
        assert "source_type" in columns

    def test_new_tables_have_columns(self):
        """Tables created after model update still have Phase 4 columns."""
        Base.metadata.drop_all(bind=TEST_ENGINE)
        Base.metadata.create_all(bind=TEST_ENGINE)

        from backend.migrations import ensure_translation_record_columns
        ensure_translation_record_columns(TEST_ENGINE)

        inspector = inspect(TEST_ENGINE)
        columns = {c["name"] for c in inspector.get_columns("translation_records")}
        assert "utterance_id" in columns
        assert "source_type" in columns
