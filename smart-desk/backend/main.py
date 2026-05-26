from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from database import engine, get_db, Base
from models import Meeting, Vote, VoteRecord, Attendee, ServiceCall
from routers import meetings, voting, services, translation
from ws_manager import manager

Base.metadata.create_all(bind=engine)


def _seed_demo_data():
    """Seed demo data if database is empty."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        if db.query(Meeting).count() > 0:
            return

        # Demo meeting
        m = Meeting(title="季度产品评审会", description="讨论Q2产品路线图与资源分配", status="active")
        db.add(m)
        db.flush()

        # Agendas
        from models import Agenda
        for i, title in enumerate([
            "Q1业绩回顾与数据分析",
            "Q2产品路线图提案讨论",
            "研发资源与预算分配表决",
            "竞品分析与市场策略调整",
        ]):
            db.add(Agenda(meeting_id=m.id, title=title, sort_order=i))

        # Attendees
        attendees_data = [
            ("张伟", "CEO", "CARD001", 1),
            ("李娜", "产品总监", "CARD002", 2),
            ("王磊", "技术负责人", "CARD003", 3),
            ("陈静", "市场总监", "CARD004", 4),
            ("赵明", "财务总监", "CARD005", 5),
            ("杨辉", "UX总监", "CARD006", 6),
            ("刘洋", "运营总监", "CARD007", 7),
            ("周婷", "HR总监", "CARD008", 8),
        ]
        for name, title, rfid, seat in attendees_data:
            db.add(Attendee(meeting_id=m.id, name=name, title=title, rfid_card=rfid, seat_id=seat))

        # Vote
        v = Vote(meeting_id=m.id, title="请对提案一：Q2产品路线图进行表决", options=["同意", "反对", "弃权"], status="open")
        db.add(v)
        db.flush()
        db.add(VoteRecord(vote_id=v.id, attendee_id=1, option="同意"))
        db.add(VoteRecord(vote_id=v.id, attendee_id=2, option="同意"))
        db.add(VoteRecord(vote_id=v.id, attendee_id=3, option="反对"))

        # Service calls
        db.add(ServiceCall(meeting_id=m.id, seat_id=1, service_type="coffee", status="completed"))
        db.add(ServiceCall(meeting_id=m.id, seat_id=3, service_type="tea", status="pending"))

        db.commit()
    finally:
        db.close()


app = FastAPI(title="智能会议桌 API")


@app.on_event("startup")
def on_startup():
    _seed_demo_data()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meetings.router)
app.include_router(voting.router)
app.include_router(services.router)
app.include_router(translation.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.websocket("/ws/{meeting_id}")
async def ws_endpoint(websocket: WebSocket, meeting_id: str):
    await manager.connect(meeting_id, websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # client can ping; server keeps connection alive
            if raw == '{"type":"ping"}':
                await websocket.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        manager.disconnect(meeting_id, websocket)
    except Exception:
        manager.disconnect(meeting_id, websocket)


# ── Convenience: endpoint that also broadcasts WS (async) ──

@app.post("/api/meetings/{meeting_id}/attendees/{attendee_id}/checkin-ws")
async def checkin_with_ws(meeting_id: int, attendee_id: int, db: Session = Depends(get_db)):
    """RFID-style check-in that also broadcasts via WebSocket."""
    attendee = db.query(Attendee).get(attendee_id)
    if not attendee:
        return {"error": "not found"}
    attendee.checked_in = True
    db.commit()
    db.refresh(attendee)

    payload = {
        "attendee_id": attendee.id,
        "name": attendee.name,
        "title": attendee.title,
        "seat_id": attendee.seat_id,
    }
    await manager.broadcast(str(meeting_id), "checkin", payload)
    return {"ok": True, "attendee": payload}
