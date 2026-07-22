"""
Translation module — Request/Response DTOs.

Per API_SPEC §10:
    TranslationInterimResponse, TranslationRecordResponse, TranslationHistoryResponse.
"""
from __future__ import annotations

from datetime import datetime

from typing import Literal

from pydantic import BaseModel, model_validator


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
    translation_status: Literal["ok", "unavailable"] = "ok"
    translation_error: str | None = None
    created_at: datetime
    # Phase 4: speech WS traceability
    utterance_id: str | None = None
    source_type: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def derive_translation_status(self):
        normalized = self.translated_text.strip().lower()
        if not normalized or normalized.startswith("[translation not available"):
            self.translation_status = "unavailable"
            self.translation_error = self.translation_error or "Local translation model unavailable"
        return self


# ── History ────────────────────────────────────────────────────────────────────


class TranslationHistoryResponse(BaseModel):
    """History query result (T3: from translation_records table)."""
    meeting_id: int
    entries: list[TranslationRecordResponse]
