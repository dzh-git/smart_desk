"""
Dev API — demo/development-only endpoints.

Per Phase 03:
    POST /api/dev/seats/{seat_id}/occupy
    POST /api/dev/seats/{seat_id}/vacate

These endpoints exist ONLY to support quick-showcase/demo workflows.
They are NOT part of the production API contract and MUST NOT be
relied upon by the frontend.

Controlled by the ENABLE_DEMO_SEAT_API environment variable (default off).
When disabled all endpoints return 404.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.seat import SeatStateResponse
from backend.services.seat_service import SeatService
from backend.services.meeting_service import MeetingService

router = APIRouter(prefix="/api/dev", tags=["dev"])

ENABLED = os.environ.get("ENABLE_DEMO_SEAT_API", "").lower() == "true"


def _service(db: Session) -> SeatService:
    return SeatService(db, event_bus)


def _to_json(api_response: ApiResponse, status_code: int = 200) -> JSONResponse:
    """Serialize ApiResponse to JSONResponse."""
    return JSONResponse(
        content=api_response.model_dump(),
        status_code=status_code,
    )


def _active_meeting_id(db: Session) -> int | None:
    """Return the active meeting's ID, or None."""
    meeting = MeetingService(db, event_bus).get_active_meeting()
    return meeting.id if meeting else None


@router.post(
    "/seats/{seat_id}/occupy",
    response_model=ApiResponse[SeatStateResponse],
    include_in_schema=False,
)
def dev_occupy(seat_id: int, db: Session = Depends(get_db)):
    """Occupy a seat (vacant → occupied_unchecked).

    Only available when ENABLE_DEMO_SEAT_API=true.
    Not part of the production API contract.
    """
    if not ENABLED:
        return JSONResponse(content={"detail": "Not Found"}, status_code=404)

    svc = _service(db)
    mid = _active_meeting_id(db)
    try:
        seat = svc.seat_occupied(seat_id, meeting_id=mid)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=SeatStateResponse.model_validate(seat))


@router.post(
    "/seats/{seat_id}/vacate",
    response_model=ApiResponse[SeatStateResponse],
    include_in_schema=False,
)
def dev_vacate(seat_id: int, db: Session = Depends(get_db)):
    """Vacate a seat (any state → vacant).

    Only available when ENABLE_DEMO_SEAT_API=true.
    Not part of the production API contract.
    """
    if not ENABLED:
        return JSONResponse(content={"detail": "Not Found"}, status_code=404)

    svc = _service(db)
    mid = _active_meeting_id(db)
    try:
        seat = svc.seat_vacant(seat_id, meeting_id=mid)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    return ApiResponse.ok(data=SeatStateResponse.model_validate(seat))
