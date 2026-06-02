# Task 010: TranslationService + DashboardService

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement `TranslationService` (orchestrates STT/MT via SpeechModule, persists history via TranslationRepository, publishes `translation_final` event) and `DashboardService` (aggregates meeting + speaker_seat + active_vote + pending_service_calls + seats from repositories).

This is Task 10 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\translation_service.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\dashboard_service.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_translation_service.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_dashboard_service.py`

- [ ] **Step 1: Implement TranslationService**

```python
# backend/services/translation_service.py
from __future__ import annotations
from sqlalchemy.orm import Session
from backend.services.event_bus import EventBus, BaseEvent


class TranslationService:
    """Orchestrates translation: delegates STT/MT to SpeechModule, persists via Repository, publishes events."""

    def __init__(self, db: Session, event_bus: EventBus, translation_repo,
                 speech_module=None, mt_engine=None):
        self.db = db
        self.bus = event_bus
        self.repo = translation_repo
        self.speech = speech_module
        self.mt = mt_engine

    @property
    def ready(self) -> bool:
        if self.speech:
            return self.speech.ready
        return False

    def preload(self):
        """Trigger model preload (called by meeting_started subscriber)."""
        if self.speech:
            self.speech.preload()

    def translate_text(self, text: str):
        if not self.speech or not self.speech.ready:
            return "", ""
        return self.speech.translate_text(text)

    def transcribe_audio(self, audio_path: str):
        if not self.speech or not self.speech.ready:
            return ""
        return self.speech.transcribe(audio_path)

    def process_interim(self, audio_path: str, session_key: str):
        if not self.speech or not self.speech.ready:
            return ""
        return self.speech.process_interim_chunk(audio_path, session_key)

    def reset_interim(self, session_key: str):
        if self.speech:
            self.speech.reset_interim(session_key)

    def start_utterance(self, session_key: str):
        if self.speech:
            self.speech.start_utterance(session_key)

    def get_history(self, meeting_id: int, seat_id: int | None = None, limit: int = 500):
        if seat_id:
            return self.repo.list_by_meeting_seat(meeting_id, seat_id, limit)
        return self.repo.list_by_meeting(meeting_id, limit)

    def delete_history(self, meeting_id: int):
        return self.repo.delete_by_meeting(meeting_id)

    def on_translation_final(self, meeting_id: int, seat_id: int,
                              zh: str, en: str, segment_id: int = 0):
        """Persist and broadcast final translation."""
        source_lang = "zh" if any('一' <= c <= '鿿' for c in zh) else "en"
        target_lang = "en" if source_lang == "zh" else "zh"
        self.repo.upsert(
            meeting_id=meeting_id, seat_id=seat_id,
            source_lang=source_lang, target_lang=target_lang,
            source_text=zh, translated_text=en,
        )
        self.bus.publish(BaseEvent(
            name="translation_final",
            payload={
                "zh": zh, "en": en, "seat_id": seat_id,
                "segment_id": segment_id, "is_final": True,
            },
        ))

    def cleanup_expired(self, retention_days: int = 180):
        return self.repo.cleanup_expired(retention_days)
```

- [ ] **Step 2: Write TranslationService test**

```python
# tests/test_translation_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.translation_repository import TranslationRepository
from backend.services.event_bus import EventBus
from backend.services.translation_service import TranslationService


@pytest.fixture
def trans_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    bus = EventBus()
    tr = TranslationRepository(db)
    svc = TranslationService(db, bus, tr)  # No speech_module for unit test
    yield svc, bus, m.id
    db.close()


def test_on_translation_final(trans_services):
    svc, bus, meeting_id = trans_services
    events = []
    bus.subscribe("translation_final", lambda e: events.append(e))
    svc.on_translation_final(meeting_id, 3, "你好世界", "Hello World", segment_id=1)
    assert len(events) == 1
    assert events[0].payload["zh"] == "你好世界"

def test_get_history(trans_services):
    svc, bus, meeting_id = trans_services
    svc.on_translation_final(meeting_id, 3, "你好", "Hello", segment_id=1)
    history = svc.get_history(meeting_id)
    assert len(history) == 1

def test_delete_history(trans_services):
    svc, bus, meeting_id = trans_services
    svc.on_translation_final(meeting_id, 3, "你好", "Hello", segment_id=1)
    count = svc.delete_history(meeting_id)
    assert count == 1
    assert len(svc.get_history(meeting_id)) == 0
```

Run: `pytest tests/test_translation_service.py -v`
Expected: PASS

- [ ] **Step 3: Implement DashboardService**

```python
# backend/services/dashboard_service.py
from __future__ import annotations
from sqlalchemy.orm import Session


class DashboardService:
    """Aggregates meeting + speaker_seat + active_vote + pending_service_calls + seats."""

    def __init__(self, db: Session, meeting_repo, attendee_repo, seat_repo,
                 vote_repo, service_call_repo):
        self.db = db
        self.meeting_repo = meeting_repo
        self.attendee_repo = attendee_repo
        self.seat_repo = seat_repo
        self.vote_repo = vote_repo
        self.service_call_repo = service_call_repo

    def get_dashboard(self, meeting_id: int) -> dict:
        meeting = self.meeting_repo.get_by_id(meeting_id)
        speaker_seat = self.seat_repo.get_speaker_seat()
        active_vote = self.vote_repo.get_active(meeting_id)
        pending_calls = self.service_call_repo.get_pending_all(meeting_id)
        seats = self.seat_repo.get_all_seats()

        return {
            "meeting": {
                "id": meeting.id, "title": meeting.title,
                "status": meeting.status, "created_at": str(meeting.created_at),
            } if meeting else None,
            "speaker_seat": speaker_seat.seat_id if speaker_seat else None,
            "active_vote": {
                "id": active_vote.id, "title": active_vote.title,
                "options": active_vote.options, "status": active_vote.status,
            } if active_vote else None,
            "pending_service_calls": [
                {"id": sc.id, "seat_id": sc.seat_id, "service_type": sc.service_type,
                 "custom_text": sc.custom_text, "created_at": str(sc.created_at)}
                for sc in pending_calls
            ],
            "seats": [
                {"seat_id": s.seat_id, "status": s.status, "attendee_id": s.attendee_id}
                for s in seats
            ],
        }
```

- [ ] **Step 4: Write DashboardService test**

```python
# tests/test_dashboard_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import SeatState, SpeakerSeat
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.dashboard_service import DashboardService


@pytest.fixture
def dash_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    for sid in range(1, 11):
        db.add(SeatState(seat_id=sid, status="vacant"))
    db.add(SpeakerSeat(id=1, seat_id=None))
    db.commit()
    ar = AttendeeRepository(db)
    sr = SeatRepository(db)
    vr = VoteRepository(db)
    scr = ServiceCallRepository(db)
    svc = DashboardService(db, mr, ar, sr, vr, scr)
    yield svc, m.id
    db.close()


def test_dashboard_returns_all_blocks(dash_services):
    svc, meeting_id = dash_services
    result = svc.get_dashboard(meeting_id)
    assert "meeting" in result
    assert "speaker_seat" in result
    assert "active_vote" in result
    assert "pending_service_calls" in result
    assert "seats" in result
    assert len(result["seats"]) == 10
```

Run: `pytest tests/test_dashboard_service.py -v`
Expected: PASS
