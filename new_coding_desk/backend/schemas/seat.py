"""
Seat module — Request/Response DTOs.

Per API_SPEC §7:
    Seat status, check-in, speaker seat schemas.
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


class SeatStateResponse(BaseModel):
    """Seat state returned to clients."""
    seat_id: int
    status: str
    attendee_id: int | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class CheckInRequest(BaseModel):
    """POST /api/seats/{seat_id}/checkin request body."""
    attendee_id: int = Field(..., gt=0)


class SpeakerSeatResponse(BaseModel):
    """Speaker seat data returned to clients."""
    seat_id: int | None

    model_config = {"from_attributes": True}


class SetSpeakerRequest(BaseModel):
    """POST /api/seats/speaker request body."""
    seat_id: int = Field(..., ge=1, le=10)
