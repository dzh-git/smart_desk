# Task 013: Refactor checkin.py to seats.py Router

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Replace `backend/routers/checkin.py` with `backend/routers/seats.py`. New router uses `SeatService`, enforces pre-assigned attendee (no anonymous auto-create), uses unified response format, and provides speaker seat endpoints at `/api/seats/speaker`. Addresses migration items B1 (API path rename) and B3 (pre-assignment requirement).

This is Task 13 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\backend\routers\seats.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py` (swap router)
- Delete: `D:\learning\smart_desktop\smart-desk\backend\routers\checkin.py`

- [ ] **Step 1: Create seats.py router**

```python
# backend/routers/seats.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from backend.database import get_db
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.event_bus import event_bus
from backend.services.seat_service import SeatService

router = APIRouter(prefix="/api/seats", tags=["seats"])


class CheckInRequest(BaseModel):
    attendee_id: int = Field(..., gt=0)


class SpeakerSeatRequest(BaseModel):
    seat_id: int = Field(..., ge=0, le=10)  # 0 = clear


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


def _get_service(db: Session):
    return SeatService(db, event_bus, SeatRepository(db), AttendeeRepository(db))


@router.get("")
def list_seats(db: Session = Depends(get_db)):
    repo = SeatRepository(db)
    seats = repo.get_all_seats()
    return _ok([{"seat_id": s.seat_id, "status": s.status,
                  "attendee_id": s.attendee_id} for s in seats])


@router.post("/{seat_id}/checkin")
def checkin(seat_id: int, data: CheckInRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    # Verify attendee is pre-assigned to this seat
    attendee_repo = AttendeeRepository(db)
    att = attendee_repo.get_by_id(data.attendee_id)
    if not att:
        raise HTTPException(404, detail="ATTENDEE_NOT_FOUND")
    if att.seat_id != seat_id:
        raise HTTPException(400, detail="ATTENDEE_NOT_ASSIGNED_TO_THIS_SEAT")

    result = svc.checkin(att.meeting_id, seat_id, data.attendee_id)
    if result is None:
        raise HTTPException(409, detail="SEAT_ALREADY_CHECKED_IN")
    return _ok({"seat_id": seat_id, "status": result.status})


@router.get("/speaker")
def get_speaker_seat(db: Session = Depends(get_db)):
    repo = SeatRepository(db)
    sp = repo.get_speaker_seat()
    return _ok({"seat_id": sp.seat_id} if sp else {"seat_id": None})


@router.post("/speaker")
def set_speaker_seat(data: SpeakerSeatRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    # Determine meeting_id from active meeting
    from backend.repositories.meeting_repository import MeetingRepository
    mr = MeetingRepository(db)
    active = mr.get_active()
    if not active:
        raise HTTPException(400, detail="NO_ACTIVE_MEETING")
    if data.seat_id == 0:
        svc.clear_speaker_seat(active.id)
    else:
        svc.set_speaker_seat(active.id, data.seat_id)
    sp = svc.get_speaker_seat()
    return _ok({"seat_id": sp.seat_id} if sp else {"seat_id": None})


@router.delete("/speaker")
def clear_speaker_seat(db: Session = Depends(get_db)):
    svc = _get_service(db)
    from backend.repositories.meeting_repository import MeetingRepository
    mr = MeetingRepository(db)
    active = mr.get_active()
    if active:
        svc.clear_speaker_seat(active.id)
    return _ok({"seat_id": None})
```

- [ ] **Step 2: Update main.py imports**

In `backend/main.py`, change:
```python
from backend.routers import checkin
```
to:
```python
from backend.routers import seats
```

And:
```python
app.include_router(checkin.router)
```
to:
```python
app.include_router(seats.router)
```

Also update the WebSocket handler that uses checkin-related functions — replace `persist_vote_cast` and `persist_service_call` imports:
```python
# Remove these from main.py imports:
# from backend.routers.votes import persist_vote_cast
# from backend.routers.service_calls import persist_service_call
```

- [ ] **Step 3: Write router integration test**

```python
# tests/test_seats_router.py
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_list_seats():
    resp = client.get("/api/seats")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    data = resp.json()["data"]
    assert len(data) == 10


def test_get_speaker_seat():
    resp = client.get("/api/seats/speaker")
    assert resp.status_code == 200
    assert resp.json()["data"]["seat_id"] is None


def test_checkin_requires_attendee_id():
    resp = client.post("/api/seats/3/checkin", json={"attendee_id": 999})
    assert resp.status_code == 404  # ATTENDEE_NOT_FOUND
```

Run: `pytest tests/test_seats_router.py -v`
Expected: PASS

- [ ] **Step 4: Delete old checkin.py**

```bash
rm D:\learning\smart_desktop\smart-desk\backend\routers\checkin.py
```

- [ ] **Step 5: Update ws_endpoint in main.py**

The WebSocket handler in `main.py` references `persist_vote_cast` and `persist_service_call` from routers. Replace those with Service calls:

In `ws_endpoint`:
```python
elif msg_type == "vote_cast":
    # Delegate to VoteService via desk coordinator (will be replaced later)
    payload = msg.get("payload", {})
    vid = payload.get("vote_id")
    opt = payload.get("option")
    if vid and opt:
        from backend.services.vote_service import VoteService
        from backend.repositories.vote_repository import VoteRepository
        from backend.database import SessionLocal
        db2 = SessionLocal()
        try:
            vs = VoteService(db2, event_bus, VoteRepository(db2))
            vs.cast(meeting_id, vid, seat, opt)
        finally:
            db2.close()
```

Similarly for `service_call` message type — use `ServiceCallService`.

- [ ] **Step 6: Verify app starts**

Run: `cd D:\learning\smart_desktop\smart-desk && python -c "from backend.main import app; print('OK')"`
Expected: OK
