"""Tests for TranslationService including CR-001 through CR-004 coverage."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import TranslationRecord
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.translation_repository import TranslationRepository
from backend.services.event_bus import EventBus
from backend.services.translation_service import TranslationService


class MockSpeechModule:
    """Mock speech module with configurable ready state."""
    def __init__(self, ready=True):
        self._ready = ready
        self._preload_called = False
        self._translate_calls = []
        self._transcribe_calls = []
        self._interim_calls = []
        self._reset_calls = []
        self._utterance_calls = []

    @property
    def ready(self):
        return self._ready

    def preload(self):
        self._preload_called = True

    def translate_text(self, text):
        self._translate_calls.append(text)
        return text, f"translated:{text}"

    def transcribe(self, audio_path):
        self._transcribe_calls.append(audio_path)
        return f"transcribed:{audio_path}"

    def process_interim_chunk(self, audio_path, session_key):
        self._interim_calls.append((audio_path, session_key))
        return f"interim:{audio_path}"

    def reset_interim(self, session_key):
        self._reset_calls.append(session_key)

    def start_utterance(self, session_key):
        self._utterance_calls.append(session_key)


class MockMTEngine:
    """Mock MT engine with configurable ready state."""
    def __init__(self, ready=True):
        self._ready = ready

    @property
    def ready(self):
        return self._ready


@pytest.fixture
def trans_services():
    """Base fixture: service without speech_module (unit test mode)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    bus = EventBus()
    tr = TranslationRepository(db)
    svc = TranslationService(db, bus, tr)
    yield svc, bus, m.id, db
    db.close()


@pytest.fixture
def trans_with_speech():
    """Service with mock speech_module and mock mt_engine."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("TestWithSpeech")
    bus = EventBus()
    tr = TranslationRepository(db)
    speech = MockSpeechModule(ready=True)
    mt = MockMTEngine(ready=True)
    svc = TranslationService(db, bus, tr, speech_module=speech, mt_engine=mt)
    yield svc, bus, m.id, db, speech, mt
    db.close()


# ── CR-004: self.mt referenced in ready property ─────────────────────────

def test_ready_false_without_speech_module(trans_services):
    """ready returns False when no speech_module is provided."""
    svc, _bus, _mid, _db = trans_services
    assert svc.ready is False


def test_ready_true_with_speech_and_mt(trans_with_speech):
    """ready returns True when speech and mt are both ready."""
    svc, _bus, _mid, _db, _speech, _mt = trans_with_speech
    assert svc.ready is True


def test_ready_false_when_speech_not_ready(trans_with_speech):
    """ready returns False when speech_module.ready is False."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    speech._ready = False
    assert svc.ready is False


def test_ready_false_when_mt_not_ready(trans_with_speech):
    """CR-004: ready returns False when mt_engine.ready is False."""
    svc, _bus, _mid, _db, _speech, mt = trans_with_speech
    mt._ready = False
    assert svc.ready is False


def test_ready_true_when_mt_is_none():
    """ready is True when speech is ready and mt is None (optional)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    bus = EventBus()
    tr = TranslationRepository(db)
    speech = MockSpeechModule(ready=True)
    svc = TranslationService(db, bus, tr, speech_module=speech, mt_engine=None)
    assert svc.ready is True
    db.close()


# ── Degraded mode: no speech_module ──────────────────────────────────────

def test_translate_text_no_speech(trans_services):
    """translate_text returns ("", "") when no speech_module."""
    svc, _bus, _mid, _db = trans_services
    result = svc.translate_text("hello")
    assert result == ("", "")


def test_transcribe_audio_no_speech(trans_services):
    """transcribe_audio returns "" when no speech_module."""
    svc, _bus, _mid, _db = trans_services
    result = svc.transcribe_audio("/tmp/test.wav")
    assert result == ""


def test_process_interim_no_speech(trans_services):
    """process_interim returns "" when no speech_module."""
    svc, _bus, _mid, _db = trans_services
    result = svc.process_interim("/tmp/chunk.wav", "seat_3")
    assert result == ""


def test_reset_interim_no_speech_does_not_crash(trans_services):
    """reset_interim does not raise when no speech_module."""
    svc, _bus, _mid, _db = trans_services
    svc.reset_interim("seat_3")  # should not raise


def test_start_utterance_no_speech_does_not_crash(trans_services):
    """start_utterance does not raise when no speech_module."""
    svc, _bus, _mid, _db = trans_services
    svc.start_utterance("seat_3")  # should not raise


def test_preload_no_speech_does_not_crash(trans_services):
    """preload does not raise when no speech_module."""
    svc, _bus, _mid, _db = trans_services
    svc.preload()  # should not raise


# ── Delegation to speech_module ──────────────────────────────────────────

def test_translate_text_delegates(trans_with_speech):
    """translate_text delegates to speech_module and returns result."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    result = svc.translate_text("hello")
    assert result[0] == "hello"
    assert "translated" in result[1]
    assert "hello" in speech._translate_calls


def test_transcribe_audio_delegates(trans_with_speech):
    """transcribe_audio delegates to speech_module.transcribe."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    result = svc.transcribe_audio("/tmp/audio.wav")
    assert "transcribed" in result
    assert "/tmp/audio.wav" in speech._transcribe_calls


def test_process_interim_delegates(trans_with_speech):
    """process_interim delegates to speech_module.process_interim_chunk."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    result = svc.process_interim("/tmp/chunk.wav", "seat_5")
    assert "interim" in result
    assert ("/tmp/chunk.wav", "seat_5") in speech._interim_calls


def test_reset_interim_delegates(trans_with_speech):
    """reset_interim delegates to speech_module."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    svc.reset_interim("seat_7")
    assert "seat_7" in speech._reset_calls


def test_start_utterance_delegates(trans_with_speech):
    """start_utterance delegates to speech_module."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    svc.start_utterance("seat_7")
    assert "seat_7" in speech._utterance_calls


def test_preload_delegates(trans_with_speech):
    """preload delegates to speech_module.preload."""
    svc, _bus, _mid, _db, speech, _mt = trans_with_speech
    svc.preload()
    assert speech._preload_called is True


# ── History operations ───────────────────────────────────────────────────

def test_on_translation_final(trans_services):
    """on_translation_final persists record and publishes event."""
    svc, bus, meeting_id, db = trans_services
    events = []
    bus.subscribe("translation_final", lambda e: events.append(e))
    svc.on_translation_final(meeting_id, 3, "你好世界", "Hello World", segment_id=1)
    assert len(events) == 1
    assert events[0].payload["zh"] == "你好世界"


def test_get_history(trans_services):
    """get_history returns records for the meeting."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "你好", "Hello", segment_id=1)
    history = svc.get_history(meeting_id)
    assert len(history) == 1


def test_delete_history(trans_services):
    """delete_history removes all records for the meeting and returns count."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "你好", "Hello", segment_id=1)
    count = svc.delete_history(meeting_id)
    assert count == 1
    assert len(svc.get_history(meeting_id)) == 0


def test_get_history_by_seat(trans_services):
    """get_history with seat_id filter returns only matching records."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "AAA", "aaa", segment_id=1)
    svc.on_translation_final(meeting_id, 5, "BBB", "bbb", segment_id=2)
    history = svc.get_history(meeting_id, seat_id=3)
    assert len(history) == 1
    assert history[0].seat_id == 3


def test_get_history_seat_id_none_is_not_none_check(trans_services):
    """CR-003: seat_id=None does not trigger the falsy branch."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "AAA", "aaa", segment_id=1)
    svc.on_translation_final(meeting_id, 5, "BBB", "bbb", segment_id=2)
    history = svc.get_history(meeting_id, seat_id=None)
    assert len(history) == 2


def test_get_history_seat_id_zero_is_not_none_check(trans_services):
    """CR-003: seat_id=0 passes through to repository (is-not-None check)."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "AAA", "aaa", segment_id=1)
    history = svc.get_history(meeting_id, seat_id=0)
    assert len(history) == 0  # No records with seat_id=0


def test_cleanup_expired_delegates(trans_services):
    """cleanup_expired delegates to repo.cleanup_expired."""
    svc, bus, meeting_id, db = trans_services
    count = svc.cleanup_expired(retention_days=30)
    assert count == 0  # No records in fresh DB


# ── CR-001: Explicit source_lang / target_lang ──────────────────────────

def test_on_translation_final_explicit_langs(trans_services):
    """CR-001: Explicit source_lang/target_lang are used for persistence."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(
        meeting_id, 3, "Hello", "你好",
        source_lang="en", target_lang="zh", segment_id=1,
    )
    record = db.query(TranslationRecord).filter(
        TranslationRecord.meeting_id == meeting_id,
        TranslationRecord.seat_id == 3,
    ).first()
    assert record is not None
    assert record.source_lang == "en"
    assert record.target_lang == "zh"
    assert record.source_text == "Hello"
    assert record.translated_text == "你好"


def test_on_translation_final_default_langs(trans_services):
    """CR-001: Default source_lang/target_lang are 'zh'/'en' (matching param names)."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "你好世界", "Hello World", segment_id=1)
    record = db.query(TranslationRecord).filter(
        TranslationRecord.meeting_id == meeting_id,
        TranslationRecord.seat_id == 3,
    ).first()
    assert record is not None
    assert record.source_lang == "zh"
    assert record.target_lang == "en"


# ── CR-002: meeting_id in event payload ─────────────────────────────────

def test_on_translation_final_includes_meeting_id(trans_services):
    """CR-002: translation_final event payload includes meeting_id."""
    svc, bus, meeting_id, db = trans_services
    events = []
    bus.subscribe("translation_final", lambda e: events.append(e))
    svc.on_translation_final(meeting_id, 3, "你好世界", "Hello World", segment_id=1)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == meeting_id


# ── Edge cases ──────────────────────────────────────────────────────────

def test_on_translation_final_empty_zh_sets_source_zh(trans_services):
    """When zh is empty but source_lang defaults to 'zh', still persists correctly."""
    svc, bus, meeting_id, db = trans_services
    svc.on_translation_final(meeting_id, 3, "", "Hello", segment_id=1)
    record = db.query(TranslationRecord).filter(
        TranslationRecord.meeting_id == meeting_id,
        TranslationRecord.seat_id == 3,
    ).first()
    assert record is not None
    assert record.source_lang == "zh"
    assert record.target_lang == "en"


# -- CR-008: Unsafe getattr fallback default ---------------------------------

def test_ready_false_when_mt_missing_ready_attr():
    """CR-008: ready returns False when mt_engine has no 'ready' attribute."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    bus = EventBus()
    tr = TranslationRepository(db)
    speech = MockSpeechModule(ready=True)

    class MTWithoutReady:
        """An mt-like object that lacks the ready property."""
        pass

    mt_broken = MTWithoutReady()
    svc = TranslationService(db, bus, tr, speech_module=speech, mt_engine=mt_broken)
    # CR-008: should default to False (conservative) not True
    assert svc.ready is False
    db.close()
