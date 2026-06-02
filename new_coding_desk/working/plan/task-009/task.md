# Task 009: VoteService + ServiceCallService

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Implement `VoteService` (vote CRUD, cast validation, close, statistics with anonymous/named distinction) and `ServiceCallService` (call CRUD, pending-per-seat enforcement, timeout auto-cancel). Both publish events via EventBus.

This is Task 9 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\vote_service.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\services\service_call_service.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_vote_service.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_service_call_service.py`

- [ ] **Step 1: Write failing test — VoteService.create**

```python
# tests/test_vote_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import EventBus
from backend.services.vote_service import VoteService


@pytest.fixture
def vote_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    ar = AttendeeRepository(db)
    a = ar.create(m.id, "John", seat_id=1)
    bus = EventBus()
    vr = VoteRepository(db)
    svc = VoteService(db, bus, vr)
    yield svc, bus, m.id, a.id
    db.close()


def test_create_vote(vote_services):
    svc, bus, meeting_id, _ = vote_services
    events = []
    bus.subscribe("vote_started", lambda e: events.append(e))
    v = svc.create(meeting_id, "Budget", ["Yes", "No"], is_anonymous=False)
    assert v.title == "Budget"
    assert len(events) == 1
```

Run: `pytest tests/test_vote_service.py::test_create_vote -v`
Expected: FAIL

- [ ] **Step 2: Implement VoteService**

```python
# backend/services/vote_service.py
from __future__ import annotations
from sqlalchemy.orm import Session
from backend.services.event_bus import EventBus, BaseEvent


class VoteService:
    def __init__(self, db: Session, event_bus: EventBus, vote_repo):
        self.db = db
        self.bus = event_bus
        self.vote_repo = vote_repo

    def create(self, meeting_id: int, title: str, options: list[str], is_anonymous: bool = False):
        v = self.vote_repo.create(meeting_id, title, options, is_anonymous)
        self.bus.publish(BaseEvent(
            name="vote_started",
            payload={"vote_id": v.id, "title": title},
        ))
        return v

    def get_by_id(self, vote_id: int, meeting_id: int | None = None):
        return self.vote_repo.get_by_id(vote_id, meeting_id)

    def list_by_meeting(self, meeting_id: int):
        return self.vote_repo.list_by_meeting(meeting_id)

    def cast(self, meeting_id: int, vote_id: int, attendee_id: int, option: str):
        v = self.vote_repo.get_by_id(vote_id, meeting_id)
        if not v or v.status != "open":
            return None  # VOTE_NOT_FOUND or VOTE_CLOSED
        if option not in v.options:
            return None  # INVALID_VOTE_OPTION
        ok = self.vote_repo.cast(vote_id, attendee_id, option)
        if ok:
            self.bus.publish(BaseEvent(
                name="vote_updated",
                payload={"vote_id": vote_id},
            ))
        return ok

    def close(self, meeting_id: int, vote_id: int):
        v = self.vote_repo.close(vote_id)
        if v:
            self.bus.publish(BaseEvent(
                name="vote_closed",
                payload={"vote_id": vote_id},
            ))
        return v

    def get_statistics(self, vote_id: int):
        v = self.vote_repo.get_by_id(vote_id)
        if not v:
            return None
        results = self.vote_repo.get_results(vote_id)
        if v.is_anonymous:
            return {"vote_id": vote_id, "is_anonymous": True, "results": results}
        else:
            voters = self.vote_repo.get_voter_ids(vote_id)
            named = {}
            for opt in v.options:
                named[opt] = [aid for aid, o in voters if o == opt]
            return {"vote_id": vote_id, "is_anonymous": False, "results": named}
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_vote_service.py -v`
Expected: PASS

- [ ] **Step 4: Write more vote service tests**

```python
def test_cast_and_close(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"])
    # Reset events
    events = []
    bus.subscribe("vote_updated", lambda e: events.append(e))
    bus.subscribe("vote_closed", lambda e: events.append(e))
    svc.cast(meeting_id, v.id, attendee_id, "A")
    assert len(events) >= 1  # vote_updated fired
    svc.close(meeting_id, v.id)
    # Check close event fired
    close_events = [e for e in events if e.name == "vote_closed"]
    assert len(close_events) == 1

def test_statistics_anonymous(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"], is_anonymous=True)
    svc.cast(meeting_id, v.id, attendee_id, "A")
    stats = svc.get_statistics(v.id)
    assert stats["is_anonymous"] is True
    assert isinstance(stats["results"], dict)
```

Run: `pytest tests/test_vote_service.py -v`
Expected: PASS

- [ ] **Step 5: Write failing test — ServiceCallService.create**

```python
# tests/test_service_call_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.event_bus import EventBus
from backend.services.service_call_service import ServiceCallService


@pytest.fixture
def sc_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    bus = EventBus()
    scr = ServiceCallRepository(db)
    svc = ServiceCallService(db, bus, scr)
    yield svc, bus, m.id
    db.close()


def test_create_service_call(sc_services):
    svc, bus, meeting_id = sc_services
    events = []
    bus.subscribe("service_call_created", lambda e: events.append(e))
    sc = svc.create(meeting_id, seat_id=4, service_type="coffee")
    assert sc.status == "pending"
    assert len(events) == 1
```

Run: `pytest tests/test_service_call_service.py::test_create_service_call -v`
Expected: FAIL

- [ ] **Step 6: Implement ServiceCallService**

```python
# backend/services/service_call_service.py
from __future__ import annotations
from sqlalchemy.orm import Session
from backend.services.event_bus import EventBus, BaseEvent


class ServiceCallService:
    def __init__(self, db: Session, event_bus: EventBus, service_call_repo):
        self.db = db
        self.bus = event_bus
        self.repo = service_call_repo

    def create(self, meeting_id: int, seat_id: int, service_type: str, custom_text: str | None = None):
        # Enforce: one pending call per seat
        existing = self.repo.get_pending_by_seat(meeting_id, seat_id)
        if existing:
            return None  # Caller returns 409
        sc = self.repo.create(meeting_id, seat_id, service_type, custom_text)
        self.bus.publish(BaseEvent(
            name="service_call_created",
            payload={"call_id": sc.id, "seat_id": seat_id, "service_type": service_type},
        ))
        return sc

    def list_by_meeting(self, meeting_id: int):
        return self.repo.list_by_meeting(meeting_id)

    def get_pending_by_seat(self, meeting_id: int, seat_id: int):
        return self.repo.get_pending_by_seat(meeting_id, seat_id)

    def resolve(self, call_id: int):
        sc = self.repo.resolve(call_id)
        if sc:
            self.bus.publish(BaseEvent(
                name="service_call_resolved",
                payload={"call_id": call_id},
            ))
        return sc

    def cancel(self, call_id: int, reason: str = "manual"):
        sc = self.repo.cancel(call_id, reason)
        if sc:
            self.bus.publish(BaseEvent(
                name="service_call_cancelled",
                payload={"call_id": call_id, "reason": reason},
            ))
        return sc

    def cancel_expired(self, timeout_seconds: int = 300):
        expired = self.repo.cancel_expired(timeout_seconds)
        for sc in expired:
            self.bus.publish(BaseEvent(
                name="service_call_cancelled",
                payload={"call_id": sc.id, "reason": "TIMEOUT"},
            ))
        return expired
```

- [ ] **Step 7: Run tests**

Run: `pytest tests/test_service_call_service.py -v`
Expected: PASS

- [ ] **Step 8: Write more service call tests**

```python
def test_duplicate_pending_rejected(sc_services):
    svc, bus, meeting_id = sc_services
    svc.create(meeting_id, 4, "coffee")
    sc2 = svc.create(meeting_id, 4, "tea")
    assert sc2 is None  # rejected

def test_resolve_then_cancel(sc_services):
    svc, bus, meeting_id = sc_services
    sc = svc.create(meeting_id, 5, "water")
    svc.resolve(sc.id)
    sc = svc.list_by_meeting(meeting_id)[0]
    assert sc.status == "resolved"
    sc2 = svc.create(meeting_id, 5, "tea")
    svc.cancel(sc2.id)
    sc2 = svc.list_by_meeting(meeting_id)[1]
    assert sc2.status == "cancelled"
```

Run: `pytest tests/test_service_call_service.py -v`
Expected: PASS
