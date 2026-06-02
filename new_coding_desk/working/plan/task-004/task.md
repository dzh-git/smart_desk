# Task 004: SeatRepository

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement `SeatRepository` — manages `seat_states` (seat status transitions) and `speaker_seat` (persistent speaker seat in DB, replacing the in-memory `_speaker_seats` dict). This addresses migration item A4 (Speaker Seat DB persistence).

This is Task 4 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\repositories\seat_repository.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_seat_repository.py`

- [ ] **Step 1: Write failing test — seed data exists**

```python
# tests/test_seat_repository.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import SeatState, SpeakerSeat
from backend.repositories.seat_repository import SeatRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Seed required data
    for sid in range(1, 11):
        session.add(SeatState(seat_id=sid, status="vacant"))
    session.add(SpeakerSeat(id=1, seat_id=None))
    session.commit()
    yield session
    session.close()


def test_get_seat_state(db_session):
    repo = SeatRepository(db_session)
    state = repo.get_seat_state(1)
    assert state is not None
    assert state.seat_id == 1
    assert state.status == "vacant"
```

Run: `pytest tests/test_seat_repository.py::test_get_seat_state -v`
Expected: FAIL

- [ ] **Step 2: Implement SeatRepository**

```python
# backend/repositories/seat_repository.py
from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Session
from backend.models import SeatState, SpeakerSeat


class SeatRepository:
    def __init__(self, db: Session):
        self.db = db

    # -- Seat States --

    def get_seat_state(self, seat_id: int) -> SeatState | None:
        return self.db.query(SeatState).filter(SeatState.seat_id == seat_id).first()

    def get_all_seats(self) -> list[SeatState]:
        return self.db.query(SeatState).order_by(SeatState.seat_id).all()

    def update_seat(self, seat_id: int, status: str, attendee_id: int | None = None) -> SeatState | None:
        s = self.get_seat_state(seat_id)
        if s:
            s.status = status
            s.attendee_id = attendee_id
            s.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(s)
        return s

    def reset_all_seats(self) -> None:
        self.db.query(SeatState).update({
            "status": "vacant", "attendee_id": None,
            "updated_at": datetime.utcnow()
        })
        self.db.commit()

    # -- Speaker Seat --

    def get_speaker_seat(self) -> SpeakerSeat:
        return self.db.query(SpeakerSeat).filter(SpeakerSeat.id == 1).first()

    def set_speaker_seat(self, seat_id: int) -> SpeakerSeat:
        sp = self.get_speaker_seat()
        if sp:
            sp.seat_id = seat_id
            sp.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(sp)
        return sp

    def clear_speaker_seat(self) -> SpeakerSeat:
        sp = self.get_speaker_seat()
        if sp:
            sp.seat_id = None
            sp.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(sp)
        return sp
```

- [ ] **Step 3: Run test**

Run: `pytest tests/test_seat_repository.py::test_get_seat_state -v`
Expected: PASS

- [ ] **Step 4: Write remaining tests**

```python
def test_update_seat_status(db_session):
    repo = SeatRepository(db_session)
    s = repo.update_seat(3, "occupied_unchecked", attendee_id=5)
    assert s.status == "occupied_unchecked"
    assert s.attendee_id == 5

def test_reset_all_seats(db_session):
    repo = SeatRepository(db_session)
    repo.update_seat(1, "checked_in", attendee_id=1)
    repo.update_seat(2, "occupied_unchecked", attendee_id=2)
    repo.reset_all_seats()
    for sid in range(1, 11):
        s = repo.get_seat_state(sid)
        assert s.status == "vacant"
        assert s.attendee_id is None

def test_get_all_seats(db_session):
    repo = SeatRepository(db_session)
    all_seats = repo.get_all_seats()
    assert len(all_seats) == 10

def test_speaker_seat_lifecycle(db_session):
    repo = SeatRepository(db_session)
    sp = repo.get_speaker_seat()
    assert sp.seat_id is None
    repo.set_speaker_seat(5)
    sp = repo.get_speaker_seat()
    assert sp.seat_id == 5
    repo.clear_speaker_seat()
    sp = repo.get_speaker_seat()
    assert sp.seat_id is None
```

Run: `pytest tests/test_seat_repository.py -v`
Expected: 5 PASS
