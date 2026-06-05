"""
Translation module — Request/Response DTOs.

Per API_SPEC §10:
    TranslationInterimResponse, TranslationRecordResponse, TranslationHistoryResponse.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


# ── Interim ────────────────────────────────────────────────────────────────────


class TranslationInterimResponse(BaseModel):
    """Interim result returned directly via HTTP (T1: no event, no WebSocket)."""
    text: str


# ── Record ─────────────────────────────────────────────────────────────────────


class TranslationRecordResponse(BaseModel):
    """Translation record returned to clients."""
    id: int
    meeting_id: int
    seat_id: int
    source_lang: str
    target_lang: str
    source_text: str
    translated_text: str
    created_at: datetime
    # Phase 4: speech WS traceability
    utterance_id: str | None = None
    source_type: str | None = None

    model_config = {"from_attributes": True}


# ── History ────────────────────────────────────────────────────────────────────


class TranslationHistoryResponse(BaseModel):
    """History query result (T3: from translation_records table)."""
    meeting_id: int
    entries: list[TranslationRecordResponse]
