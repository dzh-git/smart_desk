from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


# ── Meeting ──
class MeetingCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: str = ""

class MeetingUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None

class MeetingOut(BaseModel):
    id: int
    title: str
    description: str
    status: str
    created_at: datetime
    attendee_count: int = 0
    checked_in_count: int = 0

    model_config = {"from_attributes": True}


# ── Agenda ──
class AgendaCreate(BaseModel):
    title: str = Field(..., max_length=500)
    sort_order: int = 0

class AgendaOut(BaseModel):
    id: int
    meeting_id: int
    title: str
    sort_order: int

    model_config = {"from_attributes": True}


# ── Attendee ──
class AttendeeCreate(BaseModel):
    name: str = Field(..., max_length=100)
    title: str = ""
    seat_id: int = Field(default=0, ge=0, le=10)

class AttendeeOut(BaseModel):
    id: int
    meeting_id: int
    name: str
    title: str
    checked_in: bool
    seat_id: int

    model_config = {"from_attributes": True}


# ── Check-in (UI确认签到, no RFID) ──
class CheckInRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=10)


# ── Vote ──
class VoteCreate(BaseModel):
    title: str = Field(..., max_length=500)
    options: list[str] = Field(..., min_length=2)

class VoteCast(BaseModel):
    attendee_id: int
    option: str

class VoteResult(BaseModel):
    option: str
    count: int

class VoteOut(BaseModel):
    id: int
    meeting_id: int
    title: str
    options: list[str]
    status: str
    results: list[VoteResult] = []

    model_config = {"from_attributes": True}


# ── Service Call ──
class ServiceCallCreate(BaseModel):
    seat_id: int = Field(..., ge=1, le=10)
    service_type: str = Field(..., pattern="^(coffee|tea|water|other)$")

class ServiceCallUpdate(BaseModel):
    status: str = Field(..., pattern="^(acknowledged|completed)$")

class ServiceCallOut(BaseModel):
    id: int
    meeting_id: int
    seat_id: int
    service_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Translation (C-tier, keep stubbed) ──
class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "zh"
    target_lang: str = "en"

class TranslationOut(BaseModel):
    original: str
    translated: str
    source_lang: str
    target_lang: str


# ── WebSocket messages ──
class WSMessage(BaseModel):
    type: str
    payload: dict = {}


# ── Seat state ──
class SeatState(BaseModel):
    seat_id: int
    occupied: bool = False
    checked_in: bool = False
    attendee_name: str = ""
