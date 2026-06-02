# Task 021: Main.py Cleanup — Remove desk_coordinator, Integrate Services

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Refactor `backend/main.py` to remove direct dependency on `desk_coordinator`. The coordinator's responsibilities are now split across SeatService, MeetingService, VoteService, ServiceCallService and the EventBus → WS bridge. The WebSocket endpoint now delegates to Services instead of desk_coordinator. Update the lifespan to wire everything together cleanly.

This is Task 21 of 26.

---

**Files:**
- Modify: `D:\learning\smart_desktop\smart-desk\backend\main.py`
- Modify: `D:\learning\smart_desktop\smart-desk\backend\services\desk_coordinator.py` (simplify or mark deprecated)
- Modify: `D:\learning\smart_desktop\smart-desk\backend\routers\translation.py` (remove desk coordinator usage)

- [ ] **Step 1: Rewrite main.py lifespan**

```python
# backend/main.py
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Query

from backend.database import engine, Base, SessionLocal
from backend.models import Meeting, Agenda, Attendee, Vote, VoteRecord, ServiceCall
from backend.routers import meetings, attendees, seats, votes, service_calls, translation, dashboard
from backend.services.serial_service import serial_svc
from backend.services.ws_service import ws_svc
from backend.services.event_bus import event_bus
from backend.services.ws_event_bridge import register_ws_bridge
from backend.services.background_tasks import (
    setup_file_logging, service_call_timeout_loop, translation_cleanup_loop,
    get_logger,
)


def _seed_demo():
    logger = get_logger()
    db = SessionLocal()
    try:
        if db.query(Meeting).count() > 0:
            return
        m = Meeting(title="季度产品评审会", description="讨论Q2产品路线图与资源分配", status="active")
        db.add(m)
        db.flush()
        for i, title in enumerate([
            "Q1业绩回顾与数据分析", "Q2产品路线图提案讨论",
            "研发资源与预算分配表决", "竞品分析与市场策略调整",
        ]):
            db.add(Agenda(meeting_id=m.id, title=title, sort_order=i))
        names = ["张伟", "李娜", "王磊", "陈静", "赵明", "杨辉", "刘洋", "周婷"]
        titles = ["CEO", "产品总监", "技术负责人", "市场总监", "财务总监", "UX总监", "运营总监", "HR总监"]
        for i, (name, title) in enumerate(zip(names, titles)):
            db.add(Attendee(meeting_id=m.id, name=name, title=title, seat_id=i + 1))
        v = Vote(meeting_id=m.id, title="请对提案一：Q2产品路线图进行表决")
        v.options = ["同意", "反对", "弃权"]
        db.add(v)
        db.flush()
        db.add(VoteRecord(vote_id=v.id, attendee_id=1, option="同意"))
        db.add(VoteRecord(vote_id=v.id, attendee_id=2, option="同意"))
        db.add(VoteRecord(vote_id=v.id, attendee_id=3, option="反对"))
        db.add(ServiceCall(meeting_id=m.id, seat_id=1, service_type="coffee", status="completed"))
        db.add(ServiceCall(meeting_id=m.id, seat_id=3, service_type="tea", status="pending"))
        db.commit()
        logger.info("Demo data seeded")
    finally:
        db.close()


def _seed_system_data():
    from backend.models import SeatState, SpeakerSeat
    db = SessionLocal()
    try:
        for sid in range(1, 11):
            existing = db.query(SeatState).filter(SeatState.seat_id == sid).first()
            if not existing:
                db.add(SeatState(seat_id=sid, status="vacant"))
        existing_sp = db.query(SpeakerSeat).filter(SpeakerSeat.id == 1).first()
        if not existing_sp:
            db.add(SpeakerSeat(id=1, seat_id=None))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize
    Base.metadata.create_all(bind=engine)
    setup_file_logging()
    logger = get_logger()
    logger.info("SmartDesk starting up...")
    _seed_system_data()
    _seed_demo()
    register_ws_bridge()
    serial_svc.start()

    # Background tasks
    timeout_task = asyncio.create_task(service_call_timeout_loop(timeout_seconds=300))
    cleanup_task = asyncio.create_task(translation_cleanup_loop(retention_days=180))

    logger.info("SmartDesk ready")
    yield

    # Shutdown
    logger.info("SmartDesk shutting down...")
    timeout_task.cancel()
    cleanup_task.cancel()
    serial_svc.stop()


app = FastAPI(title="Smart Desk API", version="1.0.0", lifespan=lifespan)

# Routers
app.include_router(meetings.router)
app.include_router(attendees.router)
app.include_router(seats.router)
app.include_router(votes.router)
app.include_router(service_calls.router)
app.include_router(translation.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug/state")
def debug_state():
    """Return current desk state for debugging."""
    from backend.database import SessionLocal
    from backend.repositories.seat_repository import SeatRepository
    db = SessionLocal()
    try:
        sr = SeatRepository(db)
        seats = sr.get_all_seats()
        sp = sr.get_speaker_seat()
        return {
            "seats": [{"seat_id": s.seat_id, "status": s.status,
                        "attendee_id": s.attendee_id} for s in seats],
            "speaker_seat": sp.seat_id if sp else None,
            "serial_stub": serial_svc.stub,
        }
    finally:
        db.close()


@app.post("/api/debug/simulate/{seat_id}")
def debug_simulate(seat_id: int, action: str = Query("occupied")):
    if action == "occupied":
        serial_svc.stub_seat_occupied(seat_id)
    elif action == "vacant":
        serial_svc.stub_seat_vacant(seat_id)
    return {"ok": True, "seat_id": seat_id, "action": action}


@app.websocket("/ws/{meeting_id}")
async def ws_endpoint(ws: WebSocket, meeting_id: int, seat: int = Query(0)):
    try:
        async for msg in ws_svc.handle(ws, meeting_id, seat):
            msg_type = msg.get("type", "")
            room = ws_svc.get_or_create(meeting_id)

            if msg_type == "ping":
                await room.send_to_seat(seat, {"type": "pong"})
            elif msg_type == "seat_occupied":
                serial_svc.stub_seat_occupied(seat)
            elif msg_type == "seat_vacant":
                serial_svc.stub_seat_vacant(seat)
            elif msg_type == "vote_cast":
                payload = msg.get("payload", {})
                vid = payload.get("vote_id")
                opt = payload.get("option")
                if vid and opt:
                    from backend.database import SessionLocal
                    from backend.repositories.vote_repository import VoteRepository
                    from backend.services.vote_service import VoteService
                    db2 = SessionLocal()
                    try:
                        vs = VoteService(db2, event_bus, VoteRepository(db2))
                        vs.cast(meeting_id, vid, seat, opt)
                    finally:
                        db2.close()
            elif msg_type == "service_call":
                payload = msg.get("payload", {})
                svc_type = payload.get("service_type", "other")
                custom_text = payload.get("custom_text")
                from backend.database import SessionLocal
                from backend.repositories.service_call_repository import ServiceCallRepository
                from backend.services.service_call_service import ServiceCallService
                db2 = SessionLocal()
                try:
                    scs = ServiceCallService(db2, event_bus, ServiceCallRepository(db2))
                    scs.create(meeting_id, seat, svc_type, custom_text)
                finally:
                    db2.close()
    except Exception:
        pass
```

- [ ] **Step 2: Mark desk_coordinator.py as deprecated**

Add a comment at the top of `desk_coordinator.py`:
```python
# DEPRECATED: desk_coordinator is being replaced by Service layer + EventBus bridge.
# Functions are gradually migrating to:
#   - SeatService (on_seat_occupied, on_seat_vacant, checkin, speaker seat)
#   - MeetingService (meeting start/end)
#   - VoteService (vote start/close)
#   - TranslationService (translation results)
#   - ws_event_bridge.py (EventBus → WebSocket broadcast)
# This file is retained for backward compatibility during migration.
```

- [ ] **Step 3: Update serial→seat occupied/vacant handling**

Currently `serial_svc.on_message(desk._on_serial)` wires serial events to desk_coordinator. Update to use SeatService directly:

```python
# In main.py lifespan, replace:
# serial_svc.on_message(desk._on_serial)
# With a callback that uses SeatService:

def _on_serial(seat_id, msg):
    from backend.database import SessionLocal
    from backend.repositories.seat_repository import SeatRepository
    from backend.repositories.attendee_repository import AttendeeRepository
    from backend.services.seat_service import SeatService

    msg_type = msg.get("type", "")
    if msg_type not in ("seat_occupied", "seat_vacant"):
        return

    db = SessionLocal()
    try:
        svc = SeatService(db, event_bus, SeatRepository(db), AttendeeRepository(db))
        # Determine meeting_id from active meeting
        from backend.repositories.meeting_repository import MeetingRepository
        mr = MeetingRepository(db)
        active = mr.get_active()
        if not active:
            # Log but don't process if no active meeting (spec C7)
            get_logger().info(f"Ignoring {msg_type} for seat {seat_id}: no active meeting")
            return
        if msg_type == "seat_occupied":
            svc.on_seat_occupied(active.id, seat_id)
        elif msg_type == "seat_vacant":
            svc.on_seat_vacant(active.id, seat_id)
    finally:
        db.close()

serial_svc.on_message(_on_serial)
```

- [ ] **Step 4: Verify app starts cleanly**

```bash
cd D:\learning\smart_desktop\smart-desk && python -c "from backend.main import app; print('OK, routes:', len(app.routes))"
```

- [ ] **Step 5: Run full test suite**

```bash
cd D:\learning\smart_desktop\smart-desk && pytest tests/ -v --tb=short
```
Expected: All tests pass or have clear failure reasons to address
