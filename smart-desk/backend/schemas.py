from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field


# ── Meeting ──
class MeetingCreate(BaseModel):
    title: str
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

    model_config = {"from_attributes": True}


# ── Agenda ──
class AgendaCreate(BaseModel):
    title: str
    sort_order: int = 0


class AgendaOut(BaseModel):
    id: int
    meeting_id: int
    title: str
    sort_order: int

    model_config = {"from_attributes": True}


# ── Attendee ──
class AttendeeCreate(BaseModel):
    name: str
    title: str = ""
    rfid_card: str = ""
    seat_id: int = 0


class AttendeeOut(BaseModel):
    id: int
    meeting_id: int
    name: str
    title: str
    rfid_card: str
    checked_in: bool
    seat_id: int

    model_config = {"from_attributes": True}


class CheckInRequest(BaseModel):
    rfid_card: str


# ── Vote ──
class VoteCreate(BaseModel):
    title: str
    options: list[str]


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


# ── Service ──
class ServiceCallCreate(BaseModel):
    seat_id: int = 1
    service_type: str  # coffee / tea / water


class ServiceCallOut(BaseModel):
    id: int
    meeting_id: int
    seat_id: int
    service_type: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Translation ──
class TranslationRequest(BaseModel):
    text: str
    source_lang: str = "zh"
    target_lang: str = "en"


class TranslationOut(BaseModel):
    original: str
    translated: str
    source_lang: str
    target_lang: str


# ── WebSocket message ──
class WSMessage(BaseModel):
    type: str
    data: dict = {}
