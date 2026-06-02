"""
Smart Desk — NUC backend entry point.
"""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.database import engine, Base, SessionLocal
from backend.models import Meeting, Agenda, Attendee, Vote, VoteRecord, ServiceCall, SeatState, SpeakerSeat
from backend.routers import meetings, attendees, votes, service_calls, seats, translation
from backend.services.serial_service import serial_svc
from backend.services.ws_service import ws_svc
from backend.services.desk_coordinator import desk
from backend.services.event_bus import event_bus


def _seed_demo():
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_system_data()
    _seed_demo()
    serial_svc.start()
    from backend.services.ws_event_bridge import register_ws_bridge
    register_ws_bridge()
    from backend.services.desk_coordinator import set_main_loop
    set_main_loop()
    # Preload STT+MT models in background — non-blocking
    from backend.routers.translation import preload_models
    asyncio.ensure_future(preload_models())
    yield
    from backend.routers.translation import history_store
    history_store.close()
    serial_svc.stop()


app = FastAPI(title="Smart Desk API", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings.router)
app.include_router(attendees.router)
app.include_router(votes.router)
app.include_router(service_calls.router)
app.include_router(seats.router)
app.include_router(translation.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug/state")
def debug_state():
    """Return current desk state machine + serial status."""
    return {
        "seats": desk.state.all_seats_state,
        "vote": {
            "id": desk.state.active_vote.vote_id if desk.state.active_vote else None,
            "title": desk.state.active_vote.title if desk.state.active_vote else None,
            "phase": desk.state.active_vote.phase.value if desk.state.active_vote else "none",
        } if desk.state.active_vote else None,
        "serial_stub": serial_svc.stub,
        "checked_in": desk.state.checked_in_count,
        "occupied": desk.state.occupied_count,
    }


@app.post("/api/debug/simulate/{seat_id}")
def debug_simulate(seat_id: int, action: str = Query("occupied")):
    """Simulate hardware events without Arduino. action: occupied|vacant."""
    # Update in-memory state machine + LED (existing behavior)
    if action == "occupied":
        serial_svc.stub_seat_occupied(seat_id)
    elif action == "vacant":
        serial_svc.stub_seat_vacant(seat_id)

    # Also update DB SeatState so routers querying the DB see the change
    from backend.repositories.meeting_repository import MeetingRepository
    from backend.repositories.seat_repository import SeatRepository
    from backend.repositories.attendee_repository import AttendeeRepository
    from backend.services.seat_service import SeatService
    db = SessionLocal()
    try:
        mr = MeetingRepository(db)
        active = mr.get_active()
        if active:
            svc = SeatService(db, event_bus, SeatRepository(db), AttendeeRepository(db))
            if action == "occupied":
                svc.on_seat_occupied(active.id, seat_id)
            elif action == "vacant":
                svc.on_seat_vacant(active.id, seat_id)
    finally:
        db.close()

    return {"ok": True, "seat_id": seat_id, "action": action}


@app.websocket("/ws/{meeting_id}")
async def ws_endpoint(ws: WebSocket, meeting_id: int, seat: int = Query(0)):
    registered = False
    try:
        async for msg in ws_svc.handle(ws, meeting_id, seat):
            if not registered:
                desk.register_seat(seat, meeting_id)
                registered = True

            msg_type = msg.get("type", "")
            room = ws_svc.get_or_create(meeting_id)

            if msg_type == "ping":
                await room.send_to_seat(seat, {"type": "pong"})

            elif msg_type == "seat_occupied":
                # Dev mode: simulate TOF detection via tablet click
                serial_svc.stub_seat_occupied(seat)

            elif msg_type == "seat_vacant":
                serial_svc.stub_seat_vacant(seat)

            elif msg_type == "vote_cast":
                payload = msg.get("payload", {})
                vid = payload.get("vote_id")
                opt = payload.get("option")
                if vid and opt:
                    from backend.services.vote_service import VoteService, VoteError
                    from backend.repositories.vote_repository import VoteRepository
                    from backend.database import SessionLocal
                    from backend.models import Attendee
                    db2 = SessionLocal()
                    try:
                        att = db2.query(Attendee).filter(
                            Attendee.meeting_id == meeting_id, Attendee.seat_id == seat
                        ).first()
                        aid = att.id if att else seat
                        vs = VoteService(event_bus, VoteRepository(db2))
                        vs.cast(meeting_id, vid, aid, opt)
                    except VoteError:
                        pass  # Silently ignore bad votes to keep WS connection alive
                    finally:
                        db2.close()
                # EventBridge handles broadcast via vote_updated event

            elif msg_type == "service_call":
                payload = msg.get("payload", {})
                svc_type = payload.get("service_type", "other")
                from backend.services.service_call_service import ServiceCallService
                from backend.repositories.service_call_repository import ServiceCallRepository
                from backend.database import SessionLocal
                from backend.models import Attendee
                db2 = SessionLocal()
                try:
                    # Resolve attendee via seat lookup to track who requested the service
                    att = db2.query(Attendee).filter(
                        Attendee.meeting_id == meeting_id, Attendee.seat_id == seat
                    ).first()
                    aid = att.id if att else None
                    scs = ServiceCallService(event_bus, ServiceCallRepository(db2))
                    scs.create(meeting_id, seat, svc_type, attendee_id=aid)
                finally:
                    db2.close()
                # EventBridge handles broadcast via service_call_created event

            elif msg_type in ("led_sync",):
                await room.broadcast(msg, exclude_seat=seat)

    finally:
        if registered:
            desk.unregister_seat(seat)
