"""
Meeting module — Request/Response DTOs.

Per API_SPEC §4-6:
    Meeting, Agenda, Attendee create/response schemas.
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from backend.schemas.person import PERSON_ID_PATTERN


# ── Meeting ─────────────────────────────────────────────────────────────────

class MeetingCreate(BaseModel):
    """POST /api/meetings request body."""
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class MeetingResponse(BaseModel):
    """Meeting data returned to clients."""
    id: int
    title: str
    description: str | None
    status: str
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None

    model_config = {"from_attributes": True}


# ── Agenda ──────────────────────────────────────────────────────────────────

class AgendaCreate(BaseModel):
    """POST /api/meetings/{meeting_id}/agendas request body."""
    title: str = Field(..., min_length=1, max_length=500)
    sort_order: int = Field(default=0, ge=0)


class AgendaResponse(BaseModel):
    """Agenda data returned to clients.

    Phase 1: extended with status, started_at, completed_at, skipped_at.
    """
    id: int
    meeting_id: int
    title: str
    sort_order: int
    status: str = "pending"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    skipped_at: datetime | None = None

    model_config = {"from_attributes": True}


class AgendaStateResponse(BaseModel):
    """Agenda state machine mutation response."""
    meeting_id: int
    current_agenda: AgendaResponse | None = None
    agendas: list[AgendaResponse] = []
    progress: dict | None = None


# ── Attendee ────────────────────────────────────────────────────────────────

class AttendeeCreate(BaseModel):
    """POST /api/meetings/{meeting_id}/attendees request body."""
    name: str = Field(..., min_length=1, max_length=100)
    title: str = Field(default="", max_length=100)
    person_id: str | None = Field(
        default=None,
        pattern=PERSON_ID_PATTERN,
        alias="personId",
    )

    model_config = {"populate_by_name": True}


class AttendeeResponse(BaseModel):
    """Attendee data returned to clients."""
    id: int
    meeting_id: int
    person_id: str | None
    name: str
    title: str
    seat_id: int | None
    checked_in: bool

    model_config = {"from_attributes": True}
