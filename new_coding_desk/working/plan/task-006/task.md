# Task 006: ServiceCallRepository + TranslationRepository

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement the final two Repository classes: `ServiceCallRepository` (service_calls with custom_text, cancel_reason support) and `TranslationRepository` (translation_records with history cleanup). This also updates the ServiceCall model to include new columns and migrates translation history from `speech_history.db` to the unified `smart_desk.db`.

This is Task 6 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\service_call_repository.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\translation_repository.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\models.py` (add columns to ServiceCall)
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_service_call_repository.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_translation_repository.py`

- [ ] **Step 1: Update ServiceCall model with new columns**

In `backend/models.py`, add to ServiceCall class:
```python
custom_text = Column(Text, nullable=True)  # used when service_type='other'
cancel_reason = Column(String(50), nullable=True)  # TIMEOUT | manual
resolved_at = Column(DateTime, nullable=True)
```

- [ ] **Step 2: Write failing test — ServiceCallRepository.create**

```python
# tests/test_service_call_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.service_call_repository import ServiceCallRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    m = MeetingRepository(session).create("Test")
    yield session, m.id
    session.close()


def test_create_service_call(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, seat_id=4, service_type="coffee")
    assert sc.id is not None
    assert sc.status == "pending"
    assert sc.service_type == "coffee"
```

Run: `pytest tests/test_service_call_repository.py::test_create_service_call -v`
Expected: FAIL

- [ ] **Step 3: Implement ServiceCallRepository**

```python
# backend/repositories/service_call_repository.py
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models import ServiceCall


class ServiceCallRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, meeting_id: int, seat_id: int, service_type: str, custom_text: str | None = None) -> ServiceCall:
        sc = ServiceCall(
            meeting_id=meeting_id, seat_id=seat_id,
            service_type=service_type, custom_text=custom_text, status="pending"
        )
        self.db.add(sc)
        self.db.commit()
        self.db.refresh(sc)
        return sc

    def get_by_id(self, call_id: int) -> ServiceCall | None:
        return self.db.query(ServiceCall).filter(ServiceCall.id == call_id).first()

    def list_by_meeting(self, meeting_id: int) -> list[ServiceCall]:
        return self.db.query(ServiceCall).filter(
            ServiceCall.meeting_id == meeting_id
        ).order_by(ServiceCall.created_at.desc()).all()

    def get_pending_by_seat(self, meeting_id: int, seat_id: int) -> ServiceCall | None:
        return self.db.query(ServiceCall).filter(
            ServiceCall.meeting_id == meeting_id,
            ServiceCall.seat_id == seat_id,
            ServiceCall.status == "pending"
        ).first()

    def get_pending_all(self, meeting_id: int) -> list[ServiceCall]:
        return self.db.query(ServiceCall).filter(
            ServiceCall.meeting_id == meeting_id, ServiceCall.status == "pending"
        ).all()

    def resolve(self, call_id: int) -> ServiceCall | None:
        sc = self.get_by_id(call_id)
        if sc:
            sc.status = "resolved"
            sc.resolved_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(sc)
        return sc

    def cancel(self, call_id: int, reason: str = "manual") -> ServiceCall | None:
        sc = self.get_by_id(call_id)
        if sc:
            sc.status = "cancelled"
            sc.cancel_reason = reason
            self.db.commit()
            self.db.refresh(sc)
        return sc

    def cancel_expired(self, timeout_seconds: int = 300) -> list[ServiceCall]:
        cutoff = datetime.utcnow().timestamp() - timeout_seconds
        expired = self.db.query(ServiceCall).filter(
            ServiceCall.status == "pending"
        ).all()
        result = []
        for sc in expired:
            if sc.created_at.timestamp() < cutoff:
                sc.status = "cancelled"
                sc.cancel_reason = "TIMEOUT"
                result.append(sc)
        if result:
            self.db.commit()
        return result
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_service_call_repository.py::test_create_service_call -v`
Expected: PASS

- [ ] **Step 5: Write remaining service call tests**

```python
def test_get_pending_by_seat(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    repo.create(meeting_id, 4, "coffee")
    pending = repo.get_pending_by_seat(meeting_id, 4)
    assert pending is not None
    assert repo.get_pending_by_seat(meeting_id, 5) is None

def test_resolve_and_cancel(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, 4, "tea")
    repo.resolve(sc.id)
    sc = repo.get_by_id(sc.id)
    assert sc.status == "resolved"
    assert sc.resolved_at is not None
    sc2 = repo.create(meeting_id, 5, "water")
    repo.cancel(sc2.id, reason="TIMEOUT")
    sc2 = repo.get_by_id(sc2.id)
    assert sc2.status == "cancelled"
    assert sc2.cancel_reason == "TIMEOUT"
```

Run: `pytest tests/test_service_call_repository.py -v`
Expected: 3 PASS

- [ ] **Step 6: Write failing test — TranslationRepository.upsert**

```python
# tests/test_translation_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.translation_repository import TranslationRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    m = MeetingRepository(session).create("Test")
    yield session, m.id
    session.close()


def test_upsert_translation(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    t = repo.upsert(meeting_id=meeting_id, seat_id=3,
                    source_lang="zh", target_lang="en",
                    source_text="你好", translated_text="Hello")
    assert t.id is not None
    assert t.source_text == "你好"
    assert t.translated_text == "Hello"
```

Run: `pytest tests/test_translation_repository.py::test_upsert_translation -v`
Expected: FAIL

- [ ] **Step 7: Implement TranslationRepository**

```python
# backend/repositories/translation_repository.py
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from backend.models import TranslationRecord


class TranslationRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, meeting_id: int, seat_id: int,
               source_lang: str, target_lang: str,
               source_text: str, translated_text: str) -> TranslationRecord:
        t = TranslationRecord(
            meeting_id=meeting_id, seat_id=seat_id,
            source_lang=source_lang, target_lang=target_lang,
            source_text=source_text, translated_text=translated_text,
        )
        self.db.add(t)
        self.db.commit()
        self.db.refresh(t)
        return t

    def list_by_meeting(self, meeting_id: int, limit: int = 500) -> list[TranslationRecord]:
        return self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id
        ).order_by(TranslationRecord.created_at.desc()).limit(limit).all()

    def list_by_meeting_seat(self, meeting_id: int, seat_id: int, limit: int = 50) -> list[TranslationRecord]:
        return self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id,
            TranslationRecord.seat_id == seat_id,
        ).order_by(TranslationRecord.created_at.desc()).limit(limit).all()

    def delete_by_meeting(self, meeting_id: int) -> int:
        count = self.db.query(TranslationRecord).filter(
            TranslationRecord.meeting_id == meeting_id
        ).delete()
        self.db.commit()
        return count

    def cleanup_expired(self, retention_days: int = 180) -> int:
        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        count = self.db.query(TranslationRecord).filter(
            TranslationRecord.created_at < cutoff
        ).delete()
        self.db.commit()
        return count
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_translation_repository.py -v`
Expected: PASS

- [ ] **Step 9: Write cleanup test**

```python
def test_cleanup_expired(db_session):
    db, meeting_id = db_session
    repo = TranslationRepository(db)
    t = repo.upsert(meeting_id=meeting_id, seat_id=1,
                    source_lang="zh", target_lang="en",
                    source_text="test", translated_text="test")
    # Force old date
    from datetime import timedelta
    old = datetime.utcnow() - timedelta(days=200)
    db.execute("UPDATE translation_records SET created_at = :dt WHERE id = :id",
               {"dt": old, "id": t.id})
    db.commit()
    count = repo.cleanup_expired(180)
    assert count >= 1
```

Run: `pytest tests/test_translation_repository.py -v`
Expected: 2 PASS
