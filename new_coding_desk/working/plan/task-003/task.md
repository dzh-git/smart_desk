# Task 003: MeetingRepository + AttendeeRepository

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement `MeetingRepository` (manages `meetings` + `agendas` tables) and `AttendeeRepository` (manages `attendees` table). These are the first two of six Repository classes. Each Repository takes a SQLAlchemy Session and provides CRUD methods. Tests use in-memory SQLite.

This is Task 3 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\__init__.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\meeting_repository.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\attendee_repository.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_meeting_repository.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_attendee_repository.py`

- [ ] **Step 1: Write failing test — MeetingRepository.create_meeting**

```python
# tests/test_meeting_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_meeting(db_session):
    repo = MeetingRepository(db_session)
    meeting = repo.create("Test Meeting", "A description")
    assert meeting.id is not None
    assert meeting.title == "Test Meeting"
    assert meeting.status == "pending"
```

Run: `pytest tests/test_meeting_repository.py::test_create_meeting -v`
Expected: FAIL (MeetingRepository not defined)

- [ ] **Step 2: Implement MeetingRepository.create**

```python
# backend/repositories/meeting_repository.py
from __future__ import annotations
from sqlalchemy.orm import Session
from backend.models import Meeting, Agenda


class MeetingRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, title: str, description: str = "") -> Meeting:
        m = Meeting(title=title, description=description, status="pending")
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return m

    def get_by_id(self, meeting_id: int) -> Meeting | None:
        return self.db.query(Meeting).filter(Meeting.id == meeting_id).first()

    def list_all(self) -> list[Meeting]:
        return self.db.query(Meeting).order_by(Meeting.created_at.desc()).all()

    def get_active(self) -> Meeting | None:
        return self.db.query(Meeting).filter(Meeting.status == "active").first()

    def update_status(self, meeting_id: int, status: str) -> Meeting | None:
        m = self.get_by_id(meeting_id)
        if m:
            from datetime import datetime
            m.status = status
            if status == "active":
                m.started_at = datetime.utcnow()
            elif status == "finished":
                m.ended_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(m)
        return m

    def delete(self, meeting_id: int) -> bool:
        m = self.get_by_id(meeting_id)
        if m:
            self.db.delete(m)
            self.db.commit()
            return True
        return False

    # Agenda methods
    def add_agenda(self, meeting_id: int, title: str, sort_order: int = 0) -> Agenda:
        a = Agenda(meeting_id=meeting_id, title=title, sort_order=sort_order)
        self.db.add(a)
        self.db.commit()
        self.db.refresh(a)
        return a

    def list_agendas(self, meeting_id: int) -> list[Agenda]:
        return self.db.query(Agenda).filter(
            Agenda.meeting_id == meeting_id
        ).order_by(Agenda.sort_order).all()

    def remove_agenda(self, meeting_id: int, agenda_id: int) -> bool:
        a = self.db.query(Agenda).filter(
            Agenda.id == agenda_id, Agenda.meeting_id == meeting_id
        ).first()
        if a:
            self.db.delete(a)
            self.db.commit()
            return True
        return False
```

Add `started_at` and `ended_at` columns to the Meeting model if they don't exist:
```python
# In models.py, add to Meeting:
started_at = Column(DateTime, nullable=True)
ended_at = Column(DateTime, nullable=True)
```

- [ ] **Step 3: Run test to verify**

Run: `pytest tests/test_meeting_repository.py::test_create_meeting -v`
Expected: PASS

- [ ] **Step 4: Write tests for remaining MeetingRepository methods**

```python
def test_get_active_returns_none_when_no_active(db_session):
    repo = MeetingRepository(db_session)
    assert repo.get_active() is None

def test_get_active_returns_active_meeting(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Active Meeting")
    repo.update_status(m.id, "active")
    active = repo.get_active()
    assert active is not None
    assert active.id == m.id

def test_list_all_returns_desc_order(db_session):
    repo = MeetingRepository(db_session)
    m1 = repo.create("First")
    m2 = repo.create("Second")
    meetings = repo.list_all()
    assert len(meetings) == 2
    assert meetings[0].title == "Second"

def test_update_status(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Test")
    updated = repo.update_status(m.id, "finished")
    assert updated.status == "finished"
    assert updated.ended_at is not None
```

Run: `pytest tests/test_meeting_repository.py -v`
Expected: 5 PASS

- [ ] **Step 5: Write failing test — AttendeeRepository.create**

```python
# tests/test_attendee_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.meeting_repository import MeetingRepository


@pytest.fixture
def db_session_with_meeting():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    meeting = mr.create("Test Meeting")
    yield session, meeting.id
    session.close()


def test_create_attendee(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "John", "CEO", seat_id=1)
    assert a.id is not None
    assert a.name == "John"
    assert a.checked_in is False
```

Run: `pytest tests/test_attendee_repository.py::test_create_attendee -v`
Expected: FAIL

- [ ] **Step 6: Implement AttendeeRepository**

```python
# backend/repositories/attendee_repository.py
from __future__ import annotations
from sqlalchemy.orm import Session
from backend.models import Attendee


class AttendeeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, meeting_id: int, name: str, title: str = "", seat_id: int | None = None) -> Attendee:
        a = Attendee(meeting_id=meeting_id, name=name, title=title, seat_id=seat_id)
        self.db.add(a)
        self.db.commit()
        self.db.refresh(a)
        return a

    def get_by_id(self, attendee_id: int) -> Attendee | None:
        return self.db.query(Attendee).filter(Attendee.id == attendee_id).first()

    def list_by_meeting(self, meeting_id: int) -> list[Attendee]:
        return self.db.query(Attendee).filter(Attendee.meeting_id == meeting_id).all()

    def get_by_seat(self, meeting_id: int, seat_id: int) -> Attendee | None:
        return self.db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id, Attendee.seat_id == seat_id
        ).first()

    def check_in(self, attendee_id: int) -> Attendee | None:
        a = self.get_by_id(attendee_id)
        if a:
            a.checked_in = True
            self.db.commit()
            self.db.refresh(a)
        return a

    def count_by_meeting(self, meeting_id: int) -> int:
        return self.db.query(Attendee).filter(Attendee.meeting_id == meeting_id).count()

    def count_checked_in(self, meeting_id: int) -> int:
        return self.db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id, Attendee.checked_in == True
        ).count()

    def delete(self, attendee_id: int) -> bool:
        a = self.get_by_id(attendee_id)
        if a:
            self.db.delete(a)
            self.db.commit()
            return True
        return False

    def has_history(self, meeting_id: int, attendee_id: int) -> bool:
        """Check if attendee has participated (checked in, voted, or made service calls)."""
        from backend.models import VoteRecord, ServiceCall
        a = self.get_by_id(attendee_id)
        if not a:
            return False
        if a.checked_in:
            return True
        has_vote = self.db.query(VoteRecord).filter(
            VoteRecord.attendee_id == attendee_id
        ).first() is not None
        has_call = self.db.query(ServiceCall).filter(
            ServiceCall.seat_id == a.seat_id, ServiceCall.meeting_id == meeting_id
        ).first() is not None
        return has_vote or has_call
```

- [ ] **Step 7: Run attendee tests**

Run: `pytest tests/test_attendee_repository.py -v`
Expected: PASS

- [ ] **Step 8: Write remaining attendee tests**

```python
def test_list_by_meeting(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    repo.create(meeting_id, "Alice")
    repo.create(meeting_id, "Bob")
    attendees = repo.list_by_meeting(meeting_id)
    assert len(attendees) == 2

def test_check_in(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "John")
    checked = repo.check_in(a.id)
    assert checked.checked_in is True

def test_has_history(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "John")
    assert repo.has_history(meeting_id, a.id) is False
    repo.check_in(a.id)
    assert repo.has_history(meeting_id, a.id) is True
```

Run: `pytest tests/test_attendee_repository.py -v`
Expected: 4 PASS
