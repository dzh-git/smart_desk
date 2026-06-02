# Task 012: Refactor Meetings Router to Use MeetingService

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Refactor `backend/routers/meetings.py` to use `MeetingService` instead of inline SQLAlchemy queries. Add missing endpoints: `GET /api/meetings/active`, `POST /api/meetings/{id}/start`, `POST /api/meetings/{id}/end`. Use unified response format `{"success": bool, "message": str, "data": {}}`. Move attendee endpoints to new `attendees.py` router per spec.

This is Task 12 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\meetings.py`
- Create: `D:\learning\smart_desktop\smart-desk\backend\routers\attendees.py`
- Test: `D:\learning\smart_desktop\smart-desk\tests\test_meetings_router.py`

- [ ] **Step 1: Create Attendees router (extract from meetings.py)**

```python
# backend/routers/attendees.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.event_bus import event_bus
from backend.services.meeting_service import MeetingService
from backend.schemas import AttendeeCreate, AttendeeOut

router = APIRouter(prefix="/api/meetings/{meeting_id}/attendees", tags=["attendees"])


def _get_meeting_service(db: Session = Depends(get_db)):
    return MeetingService(
        db, event_bus,
        MeetingRepository(db), AttendeeRepository(db),
        None, None  # seat_repo and vote_repo not needed for attendee ops
    )


@router.get("")
def list_attendees(meeting_id: int, db: Session = Depends(get_db)):
    repo = AttendeeRepository(db)
    attendees = repo.list_by_meeting(meeting_id)
    return {"success": True, "message": "OK", "data": [AttendeeOut.model_validate(a) for a in attendees]}


@router.post("", status_code=201)
def add_attendee(meeting_id: int, data: AttendeeCreate, db: Session = Depends(get_db)):
    repo = AttendeeRepository(db)
    a = repo.create(meeting_id, data.name, data.title, data.seat_id)
    return {"success": True, "message": "OK", "data": AttendeeOut.model_validate(a)}


@router.delete("/{attendee_id}", status_code=200)
def remove_attendee(meeting_id: int, attendee_id: int, db: Session = Depends(get_db)):
    svc = _get_meeting_service(db)
    ok = svc.remove_attendee(meeting_id, attendee_id)
    if not ok:
        raise HTTPException(400, detail="ATTENDEE_HAS_HISTORY")
    return {"success": True, "message": "OK", "data": None}
```

- [ ] **Step 2: Rewrite meetings.py router**

In `backend/routers/meetings.py`, replace the entire file:

```python
# backend/routers/meetings.py
from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Meeting
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import event_bus
from backend.services.meeting_service import MeetingService
from backend.schemas import MeetingCreate, MeetingUpdate, MeetingOut, AgendaCreate, AgendaOut

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _get_service(db: Session):
    return MeetingService(
        db, event_bus,
        MeetingRepository(db), AttendeeRepository(db),
        SeatRepository(db), VoteRepository(db),
    )


def _meeting_out(m: Meeting, db: Session) -> MeetingOut:
    attendee_repo = AttendeeRepository(db)
    total = attendee_repo.count_by_meeting(m.id)
    checked = attendee_repo.count_checked_in(m.id)
    return MeetingOut(
        id=m.id, title=m.title, description=m.description or "",
        status=m.status, created_at=m.created_at,
        attendee_count=total, checked_in_count=checked,
    )


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


@router.get("")
def list_meetings(db: Session = Depends(get_db)):
    svc = _get_service(db)
    meetings = svc.list_all()
    return _ok([_meeting_out(m, db) for m in meetings])


@router.post("", status_code=201)
def create_meeting(data: MeetingCreate, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.create(data.title, data.description)
    if m is None:
        raise HTTPException(400, detail="ACTIVE_MEETING_EXISTS")
    return _ok(_meeting_out(m, db))


@router.get("/active")
def get_active_meeting(db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.get_active()
    if not m:
        return _ok(None)
    return _ok(_meeting_out(m, db))


@router.get("/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.get_by_id(meeting_id)
    if not m:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    return _ok(_meeting_out(m, db))


@router.patch("/{meeting_id}")
def update_meeting(meeting_id: int, data: MeetingUpdate, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.get_by_id(meeting_id)
    if not m:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    if data.title is not None:
        m.title = data.title
    if data.description is not None:
        m.description = data.description
    db.commit()
    db.refresh(m)
    return _ok(_meeting_out(m, db))


@router.post("/{meeting_id}/start")
def start_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.start(meeting_id)
    if not m:
        raise HTTPException(400, detail="ACTIVE_MEETING_EXISTS")
    return _ok(_meeting_out(m, db))


@router.post("/{meeting_id}/end")
def end_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.end(meeting_id)
    if not m:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    return _ok(_meeting_out(m, db))


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    ok = svc.delete(meeting_id)
    if not ok:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    return _ok(None)


# Agendas (delegated to service)
@router.get("/{meeting_id}/agendas")
def list_agendas(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    agendas = svc.list_agendas(meeting_id)
    return _ok([AgendaOut.model_validate(a) for a in agendas])


@router.post("/{meeting_id}/agendas", status_code=201)
def add_agenda(meeting_id: int, data: AgendaCreate, db: Session = Depends(get_db)):
    svc = _get_service(db)
    a = svc.add_agenda(meeting_id, data.title, data.sort_order)
    return _ok(AgendaOut.model_validate(a))


@router.delete("/{meeting_id}/agendas/{agenda_id}")
def remove_agenda(meeting_id: int, agenda_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    ok = svc.remove_agenda(meeting_id, agenda_id)
    if not ok:
        raise HTTPException(404, detail="AGENDA_NOT_FOUND")
    return _ok(None)
```

- [ ] **Step 3: Update main.py router imports**

In `backend/main.py`, add attendee router:
```python
from backend.routers import attendees
app.include_router(attendees.router)
```

- [ ] **Step 4: Write router integration test**

```python
# tests/test_meetings_router.py
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_list_meetings():
    resp = client.get("/api/meetings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_create_and_get_meeting():
    resp = client.post("/api/meetings", json={"title": "Test", "description": "Desc"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    resp2 = client.get(f"/api/meetings/{mid}")
    assert resp2.json()["data"]["title"] == "Test"


def test_start_and_end_meeting():
    resp = client.post("/api/meetings", json={"title": "Test"})
    mid = resp.json()["data"]["id"]
    resp2 = client.post(f"/api/meetings/{mid}/start")
    assert resp2.json()["data"]["status"] == "active"
    resp3 = client.post(f"/api/meetings/{mid}/end")
    assert resp3.json()["data"]["status"] == "finished"


def test_active_meeting():
    resp = client.get("/api/meetings/active")
    assert resp.status_code == 200
```

Run: `pytest tests/test_meetings_router.py -v`
Expected: PASS
