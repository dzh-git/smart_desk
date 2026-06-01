"""
SmartDesk — FastAPI entry point.

Per system_architecture §3, §7:
    HTTP API routes registered here.
    WebSocket endpoint: /ws/{meeting_id}
    EventBus ↔ WebSocket integration wired at startup.

Layers (strict top-down dependency):
    api/        → Router  (param validation, calls Service)
    services/   → Service (business logic, publishes Events)
    repositories/ → Repository (database access, no logic)
    events/     → EventBus (module decoupling)

Start:
    uvicorn backend.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.database import engine, Base, SessionLocal
from backend.events import event_bus
from backend.repositories.seat_repository import SeatRepository
from backend.websocket import ws_service, WebSocketEventHandler
from backend.api import (
    dashboard,
    meetings,
    seats,
    votes,
    service_calls,
    translations,
)


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables, seed data, register EventBus→WS handler."""
    # DB: create all tables declared on Base
    Base.metadata.create_all(bind=engine)

    # Seed: initialize seat_states (1..10) and speaker_seat (id=1)
    db = SessionLocal()
    try:
        SeatRepository.init_seats(db)
    finally:
        db.close()

    # EventBus → WebSocket: register handler for all 15 broadcast events
    WebSocketEventHandler.register_all(event_bus)

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Smart Desk API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(dashboard.router)
app.include_router(meetings.router)
app.include_router(seats.router)
app.include_router(votes.router)
app.include_router(service_calls.router)
app.include_router(translations.router)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ── WebSocket ─────────────────────────────────────────────────────────────────


@app.websocket("/ws/{meeting_id}")
async def ws_endpoint(ws: WebSocket, meeting_id: int, seat: int = Query(0)):
    """Per WEBSOCKET_PROTOCOL §2: /ws/{meeting_id}

    V1: server→client broadcast only. Client messages are ignored
    (business operations go through HTTP API).
    """
    async for _msg in ws_service.handle(ws, meeting_id, seat):
        # V1: client→server messages not processed.
        # Business operations → HTTP API only.
        pass
