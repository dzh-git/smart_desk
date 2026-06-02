# Task 014: Refactor Votes + Service Calls Routers

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Refactor `backend/routers/votes.py` and `backend/routers/service_calls.py` to use `VoteService` and `ServiceCallService` respectively. Use unified response format. Add vote statistics endpoint accessible to Seat tablets. Add service call resolve/cancel endpoints following spec paths.

This is Task 14 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\votes.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\service_calls.py`

- [ ] **Step 1: Rewrite votes.py router**

```python
# backend/routers/votes.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from backend.database import get_db
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import event_bus
from backend.services.vote_service import VoteService

router = APIRouter(prefix="/api/votes", tags=["votes"])


class VoteCreateRequest(BaseModel):
    meeting_id: int
    title: str = Field(..., max_length=500)
    options: list[str] = Field(..., min_length=2)
    is_anonymous: bool = False


class VoteCastRequest(BaseModel):
    attendee_id: int
    option: str


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


def _get_service(db: Session):
    return VoteService(db, event_bus, VoteRepository(db))


def _vote_out(v):
    results = VoteRepository(v._sa_instance_state.session if hasattr(v, '_sa_instance_state') else None)
    return {
        "id": v.id, "meeting_id": v.meeting_id, "title": v.title,
        "options": v.options, "status": v.status,
        "is_anonymous": v.is_anonymous,
    }


@router.get("/active")
def get_active_vote(meeting_id: int, db: Session = Depends(get_db)):
    repo = VoteRepository(db)
    v = repo.get_active(meeting_id)
    if not v:
        return _ok(None)
    return _ok(_vote_out(v))


@router.post("", status_code=201)
def create_vote(data: VoteCreateRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.create(data.meeting_id, data.title, data.options, data.is_anonymous)
    return _ok(_vote_out(v))


@router.get("/{vote_id}")
def get_vote(vote_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.get_by_id(vote_id)
    if not v:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    return _ok(_vote_out(v))


@router.post("/{vote_id}/submit")
def cast_vote(vote_id: int, data: VoteCastRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.get_by_id(vote_id)
    if not v:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    result = svc.cast(v.meeting_id, vote_id, data.attendee_id, data.option)
    if result is None:
        raise HTTPException(400, detail="VOTE_CLOSED")
    return _ok(_vote_out(v))


@router.get("/{vote_id}/statistics")
def get_vote_statistics(vote_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    stats = svc.get_statistics(vote_id)
    if not stats:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    return _ok(stats)


@router.post("/{vote_id}/close")
def close_vote(vote_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.get_by_id(vote_id)
    if not v:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    svc.close(v.meeting_id, vote_id)
    return _ok(_vote_out(v))
```

- [ ] **Step 2: Rewrite service_calls.py router**

```python
# backend/routers/service_calls.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from backend.database import get_db
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.event_bus import event_bus
from backend.services.service_call_service import ServiceCallService

router = APIRouter(prefix="/api/service-calls", tags=["service_calls"])


class ServiceCallCreateRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=10)
    service_type: str = Field(..., pattern="^(coffee|tea|water|other)$")
    custom_text: str | None = None


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


def _sc_out(sc):
    return {
        "id": sc.id, "meeting_id": sc.meeting_id, "seat_id": sc.seat_id,
        "service_type": sc.service_type, "custom_text": sc.custom_text,
        "status": sc.status, "cancel_reason": sc.cancel_reason,
        "created_at": str(sc.created_at) if sc.created_at else None,
    }


def _get_service(db: Session):
    return ServiceCallService(db, event_bus, ServiceCallRepository(db))


@router.get("")
def list_service_calls(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    calls = svc.list_by_meeting(meeting_id)
    return _ok([_sc_out(c) for c in calls])


@router.get("/current")
def get_current_call(meeting_id: int, seat_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    sc = svc.get_pending_by_seat(meeting_id, seat_id)
    return _ok(_sc_out(sc) if sc else None)


@router.post("", status_code=201)
def create_service_call(data: ServiceCallCreateRequest, meeting_id: int,
                         db: Session = Depends(get_db)):
    svc = _get_service(db)
    sc = svc.create(meeting_id, data.seat_id, data.service_type, data.custom_text)
    if sc is None:
        raise HTTPException(409, detail="SERVICE_CALL_ALREADY_PENDING")
    return _ok(_sc_out(sc))


@router.post("/{call_id}/resolve")
def resolve_call(call_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    sc = svc.resolve(call_id)
    if not sc:
        raise HTTPException(404, detail="SERVICE_CALL_NOT_FOUND")
    return _ok(_sc_out(sc))


@router.post("/{call_id}/cancel")
def cancel_call(call_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    sc = svc.cancel(call_id, reason="manual")
    if not sc:
        raise HTTPException(404, detail="SERVICE_CALL_NOT_FOUND")
    return _ok(_sc_out(sc))
```

- [ ] **Step 3: Remove persist_* functions from old routers**

Remove `persist_vote_cast` from votes.py (now handled by VoteService).
Remove `persist_service_call` from service_calls.py (now handled by ServiceCallService).

- [ ] **Step 4: Write integration tests**

```python
# tests/test_votes_router.py
from fastapi.testclient import TestClient
from backend.main import app
client = TestClient(app)

def test_create_vote():
    # First create meeting
    resp = client.post("/api/meetings", json={"title": "VM", "description": "test"})
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Test Vote",
        "options": ["Yes", "No"], "is_anonymous": False
    })
    assert resp.status_code == 201
    assert resp.json()["success"] is True
```

Run: `pytest tests/test_votes_router.py -v`
Expected: PASS
