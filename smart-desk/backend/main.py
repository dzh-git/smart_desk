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


app = FastAPI(title="Smart Desk API", version="0.2.0", lifespan=lifespan)

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


@app.websocket("/ws/{meeting_id}")
async def ws_endpoint(ws: WebSocket, meeting_id: int, seat: int = Query(0)):
    async for msg in ws_svc.handle(ws, meeting_id, seat):
        msg_type = msg.get("type", "")
        room = ws_svc.get_or_create(meeting_id)

        if msg_type == "ping":
            await room.send_to_seat(seat, {"type": "pong"})

        elif msg_type == "seat_occupied":
            await room.broadcast({"type": "seat_occupied", "payload": {"seat_id": seat}})

        elif msg_type == "check_in":
            await room.broadcast({"type": "check_in", "payload": {"seat_id": seat}})

        elif msg_type in ("vote_cast", "service_call", "seat_vacant", "led_sync"):
            await room.broadcast(msg, exclude_seat=seat)
