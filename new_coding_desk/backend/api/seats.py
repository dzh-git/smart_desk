"""
Seat API — seat states, check-in, speaker seat.

Per API_SPEC §7:
    GET    /api/seats                  → SeatService
    POST   /api/seats/{seat_id}/checkin → SeatService  + check_in event
    GET    /api/seats/speaker          → SeatService
    POST   /api/seats/speaker          → SeatService  + speaker_seat_set event
    DELETE /api/seats/speaker          → SeatService  + speaker_seat_clear event
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.seat import (
    SeatStateResponse,
    CheckInRequest,
    SpeakerSeatResponse,
    SetSpeakerRequest,
)
from backend.services.seat_service import SeatService
from backend.services.meeting_service import MeetingService

router = APIRouter(prefix="/api/seats", tags=["seats"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _service(db: Session) -> SeatService:
    return SeatService(db, event_bus)


def _to_json(api_response: ApiResponse, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        content=api_response.model_dump(),
        status_code=status_code,
    )


def _active_meeting_id(db: Session) -> int | None:
    """Return the active meeting's ID, or None if none is active."""
    meeting = MeetingService(db, event_bus).get_active_meeting()
    return meeting.id if meeting else None


# ── Seat List ────────────────────────────────────────────────────────────────


@router.get("", response_model=ApiResponse[List[SeatStateResponse]])
def list_seats(db: Session = Depends(get_db)):
    """GET /api/seats — list all seat states."""
    seats = _service(db).list_seats()
    return ApiResponse.ok(
        data=[SeatStateResponse.model_validate(s) for s in seats]
    )


# ── Check-in ─────────────────────────────────────────────────────────────────

# NOTE: /speaker routes must come BEFORE /{seat_id} to avoid route conflict.

@router.post(
    "/{seat_id}/checkin", response_model=ApiResponse[SeatStateResponse]
)
def check_in(
    seat_id: int, body: CheckInRequest, db: Session = Depends(get_db)
):
    """POST /api/seats/{seat_id}/checkin — confirm attendee check-in.

    The active meeting ID is automatically injected into events.
    Publishes: check_in event.
    """
    svc = _service(db)
    mid = _active_meeting_id(db)
    try:
        seat = svc.check_in(seat_id=seat_id, attendee_id=body.attendee_id, meeting_id=mid)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=SeatStateResponse.model_validate(seat))


# ── Speaker Seat ─────────────────────────────────────────────────────────────


@router.get("/speaker", response_model=ApiResponse[SpeakerSeatResponse])
def get_speaker_seat(db: Session = Depends(get_db)):
    """GET /api/seats/speaker — get current speaker seat."""
    speaker = _service(db).get_speaker_seat()
    return ApiResponse.ok(data=SpeakerSeatResponse.model_validate(speaker))


@router.post("/speaker", response_model=ApiResponse[SpeakerSeatResponse])
def set_speaker_seat(
    body: SetSpeakerRequest, db: Session = Depends(get_db)
):
    """POST /api/seats/speaker — set the speaker seat.

    The active meeting ID is automatically injected into events.
    Publishes: speaker_seat_set event.
    """
    svc = _service(db)
    mid = _active_meeting_id(db)
    try:
        speaker = svc.set_speaker_seat(seat_id=body.seat_id, meeting_id=mid)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    return ApiResponse.ok(data=SpeakerSeatResponse.model_validate(speaker))


@router.delete("/speaker", response_model=ApiResponse[SpeakerSeatResponse])
def clear_speaker_seat(db: Session = Depends(get_db)):
    """DELETE /api/seats/speaker — clear the speaker seat.

    The active meeting ID is automatically injected into events.
    Publishes: speaker_seat_clear event.
    """
    svc = _service(db)
    mid = _active_meeting_id(db)
    speaker = svc.clear_speaker_seat(meeting_id=mid)
    return ApiResponse.ok(data=SpeakerSeatResponse.model_validate(speaker))
