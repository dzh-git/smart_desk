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

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from backend.database import engine, Base, SessionLocal
from backend.events import event_bus
from backend.repositories.seat_repository import SeatRepository
from backend.websocket import ws_service, WebSocketEventHandler
from backend.websocket.speech_ws import handle_speech_ws
from backend.seed_demo import seed_demo_data
from backend.api import (
    dashboard,
    dev,
    meetings,
    seats,
    votes,
    service_calls,
    translations,
)

logger = logging.getLogger(__name__)


# ── Startup dependency / model check ──────────────────────────────────────────


def _check_required_deps() -> list[str]:
    """Check required speech packages (streaming ASR will not work without these).

    Returns a list of error messages (empty = all good).
    """
    errors: list[str] = []
    required = [
        ("numpy", "numpy"),
        ("torch", "torch"),
        ("funasr", "funasr"),
        ("scipy", "scipy"),
        ("soundfile", "soundfile"),
    ]
    for name, import_name in required:
        try:
            __import__(import_name)
        except ImportError as exc:
            errors.append(f"  {name}: import failed — {exc}")
    return errors


def _check_optional_deps() -> list[str]:
    """Check optional speech packages (file-based transcribe only).

    Returns a list of info messages (empty = all installed).
    """
    infos: list[str] = []
    optional = [
        ("pydub", "pydub"),
    ]
    for name, import_name in optional:
        try:
            __import__(import_name)
        except ImportError as exc:
            infos.append(f"  {name}: import failed — {exc} (optional, file transcoding only)")
    return infos


def _check_models() -> list[str]:
    """Check that speech models exist in local cache directories.

    Each model type is checked independently against both HF cache and
    ModelScope cache. Returns a list of missing-model messages.
    """
    import os
    import glob as _glob
    errors: list[str] = []

    # ── Helper: check one model type ──────────────────────────────────────
    def _check_one(hf_basename: str, ms_suffix: str, label: str) -> None:
        """Check HF cache snapshot dir or ModelScope path."""
        # HF cache: models/models--funasr--{hf_basename}/snapshots/
        hf_dir = os.path.join("models", f"models--funasr--{hf_basename}", "snapshots")
        found_hf = os.path.isdir(hf_dir) and any(
            os.path.isdir(os.path.join(hf_dir, d))
            for d in os.listdir(hf_dir)
        ) if os.path.isdir(hf_dir) else False

        # ModelScope cache: models/iic/{ms_suffix}/
        ms_dir = os.path.join("models", "iic", ms_suffix)
        found_ms = os.path.isdir(ms_dir)

        if not found_hf and not found_ms:
            errors.append(
                f"  {label}: NOT found\n"
                f"    HF cache:     {hf_dir}\n"
                f"    ModelScope:   {ms_dir}\n"
                f"    Download: cd models && git clone "
                f"https://huggingface.co/funasr/{hf_basename}"
            )

    _check_one(
        "paraformer-zh-streaming",
        "speech_paraformer_asr_nat-zh-cn-16k-common-vocab8404-online",
        "Paraformer Streaming",
    )
    _check_one(
        "Paraformer-large",
        "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "Paraformer-large",
    )
    _check_one(
        "fsmn-vad",
        "",
        "FSMN-VAD",
    )

    return errors


def _run_startup_checks() -> bool:
    """Run all startup checks. Log results. Return True if all OK."""
    print("── SmartDesk Startup Checks ──────────────────────────────")
    print()

    # 1. Python version
    print(f"  Python {sys.version}")
    print()

    # 2. Required dependencies (streaming ASR)
    req_errors = _check_required_deps()
    if req_errors:
        print("  [FAIL] Required speech packages (streaming ASR unavailable):")
        for e in req_errors:
            print(f"    {e}")
        print("  → Run: pip install -r requirements.txt")
    else:
        print("  Required speech packages: all OK")
    print()

    # 3. Optional dependencies (file transcoding only)
    opt_infos = _check_optional_deps()
    if opt_infos:
        print("  [INFO] Optional speech packages (file transcoding only):")
        for i in opt_infos:
            print(f"    {i}")
    else:
        print("  Optional speech packages: all OK")
    print()

    # 4. Speech models
    model_errors = _check_models()
    if model_errors:
        print("  [WARN] Speech models:")
        for e in model_errors:
            for line in e.split("\n"):
                print(f"    {line}")
        print("  → See working/demo-runbook.md for model download instructions.")
    else:
        print("  Speech models: found")
    print()

    print("───────────────────────────────────────────────────────────")
    print()

    speech_available = len(req_errors) == 0 and len(model_errors) == 0
    return speech_available


# ── Lifespan ──────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: run checks, create tables, seed data, register EventBus→WS."""
    # Phase 8: dependency and model checks
    _run_startup_checks()

    # DB: create all tables declared on Base
    Base.metadata.create_all(bind=engine)

    # Phase 4: idempotent column additions for translation_records
    from backend.migrations import ensure_translation_record_columns
    ensure_translation_record_columns(engine)

    # Seed: initialize seat_states (1..10), speaker_seat (id=1), and demo data
    db = SessionLocal()
    try:
        SeatRepository.init_seats(db)
        seed_demo_data(db)
    finally:
        db.close()

    # EventBus → WebSocket: capture the main event loop, then register
    # handler for all 17 broadcast events
    WebSocketEventHandler.capture_loop()
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
app.include_router(dev.router)
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


@app.websocket("/ws/speech/{meeting_id}")
async def speech_ws_endpoint(
    ws: WebSocket,
    meeting_id: int,
    seat: int = Query(..., description="Speaker Seat ID"),
):
    """Per WEBSOCKET_PROTOCOL §3: /ws/speech/{meeting_id}?seat=N

    Only the current Speaker Seat may connect. Validates:
        - Meeting exists and is active
        - Seat ID is between 1 and 10
        - Seat ID equals the persisted Speaker Seat

    Phase 2: connection + permission + start control message only.
    """
    await handle_speech_ws(ws, meeting_id, seat)
