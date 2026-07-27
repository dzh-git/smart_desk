"""
Seat module — Request/Response DTOs.

Per API_SPEC §7:
    Seat status, check-in, speaker seat schemas.
"""
from __future__ import annotations

from datetime import datetime
from pydantic import AliasChoices, BaseModel, Field


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


class IdentityCheckInRequest(BaseModel):
    """Locally verified identity submitted by the bound Android tablet."""

    person_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        validation_alias=AliasChoices(
            "personCode",
            "personId",
            "person_code",
        ),
        serialization_alias="personCode",
    )
    event_id: str = Field(
        ...,
        min_length=8,
        max_length=64,
        pattern=r"^[A-Za-z0-9._:-]+$",
        alias="eventId",
    )
    device_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        alias="deviceId",
    )
    device_seat_id: int = Field(..., ge=1, le=9, alias="deviceSeatId")
    status: str = Field(..., min_length=1, max_length=32)
    similarity: float = Field(..., ge=0, le=1)
    threshold_status: str = Field(
        ...,
        min_length=1,
        max_length=32,
        alias="thresholdStatus",
    )
    verification_level: str = Field(
        ...,
        min_length=1,
        max_length=32,
        alias="verificationLevel",
    )
    model_version: str | None = Field(
        ...,
        min_length=1,
        max_length=100,
        alias="modelVersion",
    )
    event_timestamp: int = Field(
        ...,
        ge=0,
        alias="eventTimestamp",
    )

    model_config = {"populate_by_name": True}


class SpeakerSeatResponse(BaseModel):
    """Speaker seat data returned to clients."""
    seat_id: int | None

    model_config = {"from_attributes": True}


class SetSpeakerRequest(BaseModel):
    """POST /api/seats/speaker request body."""
    seat_id: int = Field(..., ge=1, le=9)
