"""
Smart Desk — NUC backend entry point.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.database import engine, Base, SessionLocal
from backend.models import Meeting, Agenda, Attendee, Vote, VoteRecord, ServiceCall
from backend.routers import meetings, votes, service_calls, checkin, translation
from backend.services.serial_service import serial_svc
from backend.services.ws_service import ws_svc
from backend.services.desk_coordinator import desk

# Helpers imported for WS handler delegation
from backend.routers.votes import persist_vote_cast
from backend.routers.service_calls import persist_service_call


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

        db.add(ServiceCall(meeting_id=m.id, seat_id=1, service_type="coffee", status="completed"))
        db.add(ServiceCall(meeting_id=m.id, seat_id=3, service_type="tea", status="pending"))
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _seed_demo()
    serial_svc.start()
    yield
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
app.include_router(votes.router)
app.include_router(service_calls.router)
app.include_router(checkin.router)
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
    if action == "occupied":
        serial_svc.stub_seat_occupied(seat_id)
    elif action == "vacant":
        serial_svc.stub_seat_vacant(seat_id)
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
                    persist_vote_cast(meeting_id, vid, seat, opt)
                await room.broadcast({
                    "type": "vote_update",
                    "payload": {"vote_id": vid},
                })

            elif msg_type == "service_call":
                payload = msg.get("payload", {})
                svc_type = payload.get("service_type", "other")
                persist_service_call(meeting_id, seat, svc_type)
                await room.broadcast({
                    "type": "service_update",
                    "payload": {"seat_id": seat},
                })

            elif msg_type in ("led_sync",):
                await room.broadcast(msg, exclude_seat=seat)

    finally:
        if registered:
            desk.unregister_seat(seat)
