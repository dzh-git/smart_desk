"""
Translation API — audio upload, ASR, translation, history.

Per API_SPEC §10:
    POST /api/translations       → TranslationService  + translation_final event
    GET  /api/translations       → TranslationService  (history query)

Business rules:
    T1: final=false → process_interim() → direct HTTP return (no event, no WebSocket).
    T2: final=true  → process_final()   → persist + translation_final event.
    T3: GET         → query translation_records table.
"""
from __future__ import annotations

import os
import tempfile
from typing import List

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import ValidationError
from backend.schemas import ApiResponse
from backend.schemas.translation import (
    TranslationHistoryResponse,
    TranslationInterimResponse,
    TranslationRecordResponse,
)
from backend.services.translation_service import TranslationService

router = APIRouter(prefix="/api/translations", tags=["translations"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _service(db: Session) -> TranslationService:
    return TranslationService(db, event_bus)


def _to_json(api_response: ApiResponse, status_code: int = 200) -> JSONResponse:
    """Serialize ApiResponse to JSONResponse with the given HTTP status."""
    return JSONResponse(
        content=api_response.model_dump(mode="json"),
        status_code=status_code,
    )


def _save_temp(audio: UploadFile) -> str:
    """Save UploadFile to a temp WAV file, return path. Caller cleans up."""
    suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(path, "wb") as f:
        f.write(audio.file.read())
    return path


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("")
async def process_audio(
    audio: UploadFile = File(...),
    meeting_id: int = Form(...),
    seat_id: int = Form(...),
    session_key: str = Form(""),
    final: bool = Form(False),
    db: Session = Depends(get_db),
):
    """POST /api/translations — process audio chunk.

    FormData: audio, meeting_id, seat_id, session_key(opt), final(bool).

    final=false (T1): interim ASR → returns accumulated text directly.
        No database write. No event. No WebSocket broadcast.

    final=true (T2): full offline ASR → translate → persist →
        publish translation_final event → WebSocket broadcast.
    """
    if not session_key:
        session_key = f"{meeting_id}_{seat_id}"

    tmp_path = _save_temp(audio)
    try:
        svc = _service(db)

        if not final:
            # T1: interim — return text directly
            text = svc.process_interim(tmp_path, session_key)
            return ApiResponse.ok(
                data=TranslationInterimResponse(text=text)
            )
        else:
            # T2: final — persist + event
            try:
                record = svc.process_final(tmp_path, meeting_id, seat_id)
            except ValidationError as e:
                return _to_json(ApiResponse.fail(e.message, e.error_code), 500)
            return _to_json(
                ApiResponse.ok(
                    data=TranslationRecordResponse.model_validate(record)
                ),
                201,
            )
    finally:
        _cleanup_temp(tmp_path)


def _cleanup_temp(path: str) -> None:
    """Remove temp file if it exists."""
    try:
        os.unlink(path)
    except OSError:
        pass


@router.get("")
def get_history(
    meeting_id: int = Query(..., description="Meeting ID"),
    seat_id: int | None = Query(None, description="Optional seat filter"),
    db: Session = Depends(get_db),
):
    """GET /api/translations — query translation history (T3).

    Returns records from translation_records table, newest first.
    """
    svc = _service(db)
    records = svc.get_history(meeting_id, seat_id=seat_id)
    entries = [TranslationRecordResponse.model_validate(r) for r in records]
    return ApiResponse.ok(
        data=TranslationHistoryResponse(
            meeting_id=meeting_id,
            entries=entries,
        )
    )
