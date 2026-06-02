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

from fastapi import FastAPI, WebSocket, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

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
    allow_credentials=False,
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


# ── Root page ──────────────────────────────────────────────────────────────────

ROOT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Desk</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
        .card { background: #1e293b; border-radius: 16px; padding: 48px; max-width: 480px; width: 90%; text-align: center; box-shadow: 0 25px 50px rgba(0,0,0,0.4); }
        h1 { font-size: 28px; margin-bottom: 8px; }
        .status { display: inline-flex; align-items: center; gap: 6px; background: #064e3b; color: #6ee7b7; padding: 6px 16px; border-radius: 20px; font-size: 14px; margin: 16px 0 24px; }
        .dot { width: 8px; height: 8px; background: #34d399; border-radius: 50%; animation: pulse 2s infinite; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        .links { display: flex; flex-direction: column; gap: 10px; }
        a { display: block; padding: 12px 20px; background: #334155; color: #e2e8f0; text-decoration: none; border-radius: 8px; transition: background 0.2s; }
        a:hover { background: #475569; }
        a.primary { background: #2563eb; }
        a.primary:hover { background: #3b82f6; }
        .footer { margin-top: 24px; font-size: 12px; color: #64748b; }
    </style>
</head>
<body>
    <div class="card">
        <h1>🪑 Smart Desk</h1>
        <div class="status"><span class="dot"></span> Server Running</div>
        <div class="links">
            <a class="primary" href="/docs">📖 API 文档 (Swagger)</a>
            <a href="/api/health">❤️ 健康检查</a>
            <a href="/api/meetings">📋 会议列表</a>
            <a href="/api/seats">💺 座位状态</a>
        </div>
        <div class="footer">Smart Desk v1.0.0 &middot; FastAPI</div>
    </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return ROOT_HTML


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
