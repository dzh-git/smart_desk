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

import os
import logging
from typing import List

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import ConflictError, NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.seat import (
    SeatStateResponse,
    CheckInRequest,
    IdentityCheckInRequest,
    TabletVacateRequest,
    SpeakerSeatResponse,
    SetSpeakerRequest,
)
from backend.services.seat_service import SeatService
from backend.services.meeting_service import MeetingService
from backend.security.rate_limit import (
    SlidingWindowRateLimiter,
    bounded_env_int,
)
from backend.security.structured_log import log_security_event

logger = logging.getLogger(__name__)
identity_rate_limiter = SlidingWindowRateLimiter()

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


@router.post(
    "/{seat_id}/identity-checkin",
    response_model=ApiResponse[SeatStateResponse],
)
def identity_check_in(
    seat_id: int,
    body: IdentityCheckInRequest,
    db: Session = Depends(get_db),
    device_token: str | None = Header(
        default=None,
        alias="X-SmartDesk-Device-Token",
    ),
):
    """Resolve a verified stable person and delegate to SeatService.check_in.

    PROTOTYPE results remain blocked by default. Development-only testing may
    opt in with SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN=true.
    """
    allow_prototype = (
        os.environ.get(
            "SMARTDESK_ALLOW_PROTOTYPE_IDENTITY_CHECKIN",
            "",
        ).lower()
        == "true"
    )
    rate_decision = identity_rate_limiter.check(
        f"{body.device_id}:{seat_id}",
        limit=bounded_env_int(
            "SMARTDESK_IDENTITY_RATE_LIMIT_PER_MINUTE",
            60,
            minimum=1,
            maximum=600,
        ),
        window_seconds=60,
    )
    if not rate_decision.allowed:
        log_security_event(
            logger,
            event="identity_checkin_rate_limited",
            level=logging.WARNING,
            device_id=body.device_id,
            seat_id=seat_id,
            result="rejected",
        )
        response = _to_json(
            ApiResponse.fail(
                "Identity check-in rate limit exceeded",
                "RATE_LIMITED",
            ),
            429,
        )
        response.headers["Retry-After"] = str(
            rate_decision.retry_after_seconds
        )
        return response
    try:
        seat = _service(db).identity_check_in(
            seat_id=seat_id,
            device_seat_id=body.device_seat_id,
            device_id=body.device_id,
            device_token=device_token,
            event_id=body.event_id,
            event_timestamp=body.event_timestamp,
            person_id=body.person_id,
            identity_status=body.status,
            threshold_status=body.threshold_status,
            verification_level=body.verification_level,
            similarity=body.similarity,
            model_version=body.model_version,
            allow_prototype=allow_prototype,
        )
    except ConflictError as error:
        _log_identity_result(body, seat_id, error.error_code)
        return _to_json(
            ApiResponse.fail(error.message, error.error_code),
            409,
        )
    except NotFoundError as error:
        _log_identity_result(body, seat_id, error.error_code)
        return _to_json(
            ApiResponse.fail(error.message, error.error_code),
            404,
        )
    except ValidationError as error:
        _log_identity_result(body, seat_id, error.error_code)
        return _to_json(
            ApiResponse.fail(error.message, error.error_code),
            400,
        )
    _log_identity_result(body, seat_id, "OK")
    return ApiResponse.ok(data=SeatStateResponse.model_validate(seat))


@router.post(
    "/{seat_id}/manual-admit",
    response_model=ApiResponse[SeatStateResponse],
)
def manual_admit(seat_id: int, db: Session = Depends(get_db)):
    """Host fallback: admit the attendee assigned to this seat."""
    svc = _service(db)
    meeting_id = _active_meeting_id(db)
    assigned = svc.get_assigned_attendee(seat_id, meeting_id)
    try:
        seat = svc.manual_admit(seat_id)
    except ConflictError as error:
        status_code = 409
        failure = error
    except NotFoundError as error:
        status_code = 404
        failure = error
    except ValidationError as error:
        status_code = 400
        failure = error
    else:
        log_security_event(
            logger,
            event="manual_admit",
            meeting_id=meeting_id,
            seat_id=seat_id,
            attendee_id=assigned.id if assigned else None,
            result="OK",
        )
        return ApiResponse.ok(data=SeatStateResponse.model_validate(seat))

    log_security_event(
        logger,
        event="manual_admit",
        level=logging.WARNING,
        meeting_id=meeting_id,
        seat_id=seat_id,
        attendee_id=assigned.id if assigned else None,
        result=failure.error_code,
    )
    return _to_json(
        ApiResponse.fail(failure.message, failure.error_code),
        status_code,
    )


@router.post(
    "/{seat_id}/tablet-vacate",
    response_model=ApiResponse[SeatStateResponse],
)
def tablet_vacate(
    seat_id: int,
    body: TabletVacateRequest,
    db: Session = Depends(get_db),
    device_token: str | None = Header(
        default=None,
        alias="X-SmartDesk-Device-Token",
    ),
):
    """Release a seat using the bound Android tablet's credential."""
    try:
        seat = _service(db).tablet_vacate(
            seat_id=seat_id,
            device_seat_id=body.device_seat_id,
            device_id=body.device_id,
            device_token=device_token,
        )
    except ConflictError as error:
        status_code = 409
        failure = error
    except NotFoundError as error:
        status_code = 404
        failure = error
    except ValidationError as error:
        status_code = 400
        failure = error
    else:
        log_security_event(
            logger,
            event="tablet_vacate",
            device_id=body.device_id,
            seat_id=seat_id,
            result="OK",
        )
        return ApiResponse.ok(data=SeatStateResponse.model_validate(seat))

    log_security_event(
        logger,
        event="tablet_vacate",
        level=logging.WARNING,
        device_id=body.device_id,
        seat_id=seat_id,
        result=failure.error_code,
    )
    return _to_json(
        ApiResponse.fail(failure.message, failure.error_code),
        status_code,
    )


def _log_identity_result(
    body: IdentityCheckInRequest,
    seat_id: int,
    result: str,
) -> None:
    log_security_event(
        logger,
        event="identity_checkin",
        level=(logging.INFO if result == "OK" else logging.WARNING),
        device_id=body.device_id,
        seat_id=seat_id,
        event_id=body.event_id,
        result=result,
    )


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
