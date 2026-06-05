"""
Smart Desk — NUC backend entry point.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Query, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.database import engine, Base, SessionLocal
from backend.models import Meeting, Agenda, Attendee, Vote, VoteRecord, ServiceCall, SeatState, SpeakerSeat
from backend.routers import meetings, attendees, votes, service_calls, seats, translation, dashboard
from backend.services.serial_service import serial_svc
from backend.services.ws_service import ws_svc
from backend.services.event_bus import event_bus, BaseEvent
from backend.services.vote_service import VoteService, VoteError
from backend.services.service_call_service import ServiceCallService, ServiceCallError
from backend.services.background_tasks import (
    setup_file_logging,
    service_call_timeout_loop,
    translation_cleanup_loop,
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

        db.add(ServiceCall(meeting_id=m.id, seat_id=1, attendee_id=1, service_type="coffee", status="completed"))
        db.add(ServiceCall(meeting_id=m.id, seat_id=3, attendee_id=3, service_type="tea", status="pending"))
        db.commit()
        logger.info("Demo data seeded")
    finally:
        db.close()


def _seed_system_data():
    db = SessionLocal()
    try:
        # Seed seat_states 1-10
        for sid in range(1, 11):
            existing = db.query(SeatState).filter(SeatState.seat_id == sid).first()
            if not existing:
                db.add(SeatState(seat_id=sid, status="vacant"))

        # Seed speaker_seat single row
        existing_sp = db.query(SpeakerSeat).filter(SpeakerSeat.id == 1).first()
        if not existing_sp:
            db.add(SpeakerSeat(id=1, seat_id=None))

        db.commit()
    finally:
        db.close()


def _on_serial(seat_id: int, msg: dict):
    """Callback for serial events — uses SeatService directly instead of desk_coordinator.

    CR-017: DB persist failures are caught and logged but do not prevent EventBus
    publishing. This matches the old desk_coordinator behavior where
    _persist_seat_state caught DB exceptions internally and EventBus publish
    always proceeded.
    """
    from backend.repositories.seat_repository import SeatRepository
    from backend.repositories.attendee_repository import AttendeeRepository
    from backend.repositories.meeting_repository import MeetingRepository
    from backend.services.seat_service import SeatService

    msg_type = msg.get("type", "")
    if msg_type not in ("seat_occupied", "seat_vacant"):
        return

    db = SessionLocal()
    try:
        svc = SeatService(db, event_bus, SeatRepository(db), AttendeeRepository(db))
        mr = MeetingRepository(db)
        active = mr.get_active()
        if not active:
            get_logger().info(f"Ignoring {msg_type} for seat {seat_id}: no active meeting")
            return
        meeting_id = active.id

        # CR-014: Persist DB state BEFORE EventBus publish so handlers
        # querying DB during event handling see the updated state.
        # CR-017: DB errors are caught and logged but not propagated.
        # EventBus publish always proceeds so tablets receive seat state
        # changes even when DB persistence temporarily fails.
        try:
            if msg_type == "seat_occupied":
                svc.on_seat_occupied(meeting_id, seat_id)
            elif msg_type == "seat_vacant":
                svc.on_seat_vacant(meeting_id, seat_id)
        except Exception:
            get_logger().exception(
                "Failed to persist seat state: seat_id=%d action=%s meeting_id=%d",
                seat_id, msg_type, meeting_id,
            )

        event_bus.publish(BaseEvent(
            name=msg_type,
            payload={"meeting_id": meeting_id, "seat_id": seat_id},
        ))
    except Exception:
        get_logger().exception(
            "Unexpected error in _on_serial: seat_id=%d msg_type=%s", seat_id, msg_type
        )
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

    # Wire serial callback BEFORE serial starts (replaces desk._on_serial)
    serial_svc.on_message(_on_serial)

    from backend.services.ws_event_bridge import register_ws_bridge
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


app = FastAPI(title="Smart Desk API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def unified_error_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "error_code": exc.detail,
            "data": None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Request validation failed",
            "error_code": "VALIDATION_ERROR",
            "data": None,
        },
    )


app.include_router(meetings.router)
app.include_router(attendees.router)
app.include_router(votes.router)
app.include_router(service_calls.router)
app.include_router(seats.router)
app.include_router(translation.router)
app.include_router(dashboard.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug/state")
def debug_state():
    """Return current desk state for debugging."""
    from backend.repositories.seat_repository import SeatRepository
    from backend.repositories.vote_repository import VoteRepository
    db = SessionLocal()
    try:
        sr = SeatRepository(db)
        seats = sr.get_all_seats()
        sp = sr.get_speaker_seat()

        # Find active meeting's open vote for debug info
        from backend.repositories.meeting_repository import MeetingRepository
        mr = MeetingRepository(db)
        active = mr.get_active()
        vote_info = None
        if active:
            vr = VoteRepository(db)
            open_vote = vr.get_active(active.id)
            if open_vote:
                vote_info = {
                    "id": open_vote.id,
                    "title": open_vote.title,
                    "phase": open_vote.status,
                }

        return {
            "seats": [{"seat_id": s.seat_id, "status": s.status,
                       "attendee_id": s.attendee_id} for s in seats],
            "speaker_seat": sp.seat_id if sp else None,
            "vote": vote_info,
            "serial_stub": serial_svc.stub,
        }
    finally:
        db.close()


@app.post("/api/debug/simulate/{seat_id}")
def debug_simulate(seat_id: int, action: str = Query("occupied")):
    """Simulate hardware events without Arduino. action: occupied|vacant.

    CR-011: The new _on_serial callback now persists DB state and publishes
    EventBus events for both the WebSocket stub path and the hardware serial
    path. So debug_simulate triggers the same path as hardware TOF.
    """
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
                    from backend.repositories.vote_repository import VoteRepository
                    db2 = SessionLocal()
                    try:
                        att = db2.query(Attendee).filter(
                            Attendee.meeting_id == meeting_id, Attendee.seat_id == seat
                        ).first()
                        if att:
                            vs = VoteService(event_bus, VoteRepository(db2))
                            vs.cast(meeting_id, vid, att.id, opt)
                    except VoteError:
                        pass
                    finally:
                        db2.close()

            elif msg_type == "service_call":
                payload = msg.get("payload", {})
                svc_type = payload.get("service_type", "other")
                from backend.repositories.service_call_repository import ServiceCallRepository
                db2 = SessionLocal()
                try:
                    att = db2.query(Attendee).filter(
                        Attendee.meeting_id == meeting_id, Attendee.seat_id == seat
                    ).first()
                    aid = att.id if att else None
                    scs = ServiceCallService(event_bus, ServiceCallRepository(db2))
                    scs.create(meeting_id, seat, svc_type, attendee_id=aid)
                except (ValueError, ServiceCallError):
                    pass
                finally:
                    db2.close()

            elif msg_type in ("led_sync",):
                await room.broadcast(msg, exclude_seat=seat)

    except Exception:
        pass
