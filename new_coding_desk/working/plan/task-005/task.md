# Task 005: VoteRepository

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement `VoteRepository` — manages `votes` and `vote_records` tables. Provides CRUD for vote definitions and vote record submission with UNIQUE constraint enforcement.

This is Task 5 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\vote_repository.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_vote_repository.py`

- [ ] **Step 1: Write failing test — create vote**

```python
# tests/test_vote_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.vote_repository import VoteRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    meeting = mr.create("Test")
    ar = AttendeeRepository(session)
    att = ar.create(meeting.id, "John", seat_id=1)
    yield session, meeting.id, att.id
    session.close()


def test_create_vote(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Approve Budget", ["Agree", "Reject", "Abstain"])
    assert v.id is not None
    assert v.title == "Approve Budget"
    assert v.status == "open"
    assert v.options == ["Agree", "Reject", "Abstain"]
```

Run: `pytest tests/test_vote_repository.py::test_create_vote -v`
Expected: FAIL

- [ ] **Step 2: Implement VoteRepository**

```python
# backend/repositories/vote_repository.py
from __future__ import annotations
import json
from sqlalchemy.orm import Session
from backend.models import Vote, VoteRecord


class VoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, meeting_id: int, title: str, options: list[str], is_anonymous: bool = False) -> Vote:
        v = Vote(meeting_id=meeting_id, title=title, is_anonymous=is_anonymous)
        v.options = options
        self.db.add(v)
        self.db.commit()
        self.db.refresh(v)
        return v

    def get_by_id(self, vote_id: int, meeting_id: int | None = None) -> Vote | None:
        q = self.db.query(Vote).filter(Vote.id == vote_id)
        if meeting_id is not None:
            q = q.filter(Vote.meeting_id == meeting_id)
        return q.first()

    def list_by_meeting(self, meeting_id: int) -> list[Vote]:
        return self.db.query(Vote).filter(Vote.meeting_id == meeting_id).all()

    def get_active(self, meeting_id: int) -> Vote | None:
        return self.db.query(Vote).filter(
            Vote.meeting_id == meeting_id, Vote.status == "open"
        ).first()

    def close(self, vote_id: int) -> Vote | None:
        v = self.get_by_id(vote_id)
        if v:
            from datetime import datetime
            v.status = "closed"
            v.closed_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(v)
        return v

    def close_all_open(self, meeting_id: int) -> int:
        count = self.db.query(Vote).filter(
            Vote.meeting_id == meeting_id, Vote.status == "open"
        ).update({"status": "closed"})
        self.db.commit()
        return count

    def get_all_open(self, meeting_id: int) -> list[Vote]:
        """Return all open votes for a meeting (used by end() for per-vote close events)."""
        return self.db.query(Vote).filter(
            Vote.meeting_id == meeting_id, Vote.status == "open"
        ).all()

    # -- Vote Records --
    def cast(self, vote_id: int, attendee_id: int, option: str) -> bool:
        existing = self.db.query(VoteRecord).filter(
            VoteRecord.vote_id == vote_id, VoteRecord.attendee_id == attendee_id
        ).first()
        if existing:
            existing.option = option
        else:
            self.db.add(VoteRecord(vote_id=vote_id, attendee_id=attendee_id, option=option))
        self.db.commit()
        return True

    def get_results(self, vote_id: int) -> dict[str, int]:
        records = self.db.query(VoteRecord).filter(VoteRecord.vote_id == vote_id).all()
        counts: dict[str, int] = {}
        for r in records:
            counts[r.option] = counts.get(r.option, 0) + 1
        return counts

    def get_voter_ids(self, vote_id: int) -> list[tuple[int, str]]:
        records = self.db.query(VoteRecord).filter(VoteRecord.vote_id == vote_id).all()
        return [(r.attendee_id, r.option) for r in records]
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_vote_repository.py::test_create_vote -v`
Expected: PASS

- [ ] **Step 4: Add is_anonymous and closed_at to Vote model if missing**

In `backend/models.py`, add to `Vote`:
```python
is_anonymous = Column(Boolean, default=False)
closed_at = Column(DateTime, nullable=True)
```

- [ ] **Step 5: Write remaining tests**

```python
def test_cast_vote(db_session):
    db, meeting_id, attendee_id = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Test", ["Yes", "No"])
    ok = repo.cast(v.id, attendee_id, "Yes")
    assert ok is True
    results = repo.get_results(v.id)
    assert results["Yes"] == 1

def test_duplicate_cast_updates(db_session):
    db, meeting_id, attendee_id = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Test", ["Yes", "No"])
    repo.cast(v.id, attendee_id, "Yes")
    repo.cast(v.id, attendee_id, "No")
    results = repo.get_results(v.id)
    assert results["Yes"] == 0
    assert results["No"] == 1

def test_close_vote(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Test", ["Yes"])
    closed = repo.close(v.id)
    assert closed.status == "closed"
    assert closed.closed_at is not None

def test_close_all_open(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    repo.create(meeting_id, "V1", ["A"])
    repo.create(meeting_id, "V2", ["B"])
    count = repo.close_all_open(meeting_id)
    assert count == 2

def test_get_active(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    assert repo.get_active(meeting_id) is None
    v = repo.create(meeting_id, "V", ["A"])
    assert repo.get_active(meeting_id).id == v.id
```

Run: `pytest tests/test_vote_repository.py -v`
Expected: 6 PASS
