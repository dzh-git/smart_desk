"""
Service call API — tea/coffee/water/other requests.

Per API_SPEC §9:
    POST  /api/service-calls                     → ServiceCallService  + service_call_created event
    GET   /api/service-calls                     → ServiceCallService
    GET   /api/service-calls/current?seat_id=4   → ServiceCallService
    POST  /api/service-calls/{call_id}/resolve   → ServiceCallService  + service_call_resolved event
    POST  /api/service-calls/{call_id}/cancel    → ServiceCallService  + service_call_cancelled event
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.service_call import ServiceCallCreate, ServiceCallResponse
from backend.services.service_call_service import ServiceCallService

router = APIRouter(prefix="/api/service-calls", tags=["service_calls"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _service(db: Session) -> ServiceCallService:
    return ServiceCallService(db, event_bus)


def _to_json(api_response: ApiResponse, status_code: int = 200) -> JSONResponse:
    """Serialize ApiResponse to JSONResponse with the given HTTP status."""
    return JSONResponse(
        content=api_response.model_dump(),
        status_code=status_code,
    )


# ── Service call endpoints ───────────────────────────────────────────────────


@router.post("", response_model=ApiResponse[ServiceCallResponse], status_code=201)
def create_call(body: ServiceCallCreate, db: Session = Depends(get_db)):
    """POST /api/service-calls — create a new service call.

    Publishes: service_call_created event.
    """
    svc = _service(db)
    try:
        call = svc.create_call(
            meeting_id=body.meeting_id,
            seat_id=body.seat_id,
            service_type=body.service_type,
        )
    except ConflictError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 409)
    return ApiResponse.ok(data=ServiceCallResponse.model_validate(call))


@router.get("", response_model=ApiResponse[List[ServiceCallResponse]])
def list_calls(
    meeting_id: int = Query(..., description="Meeting ID"),
    db: Session = Depends(get_db),
):
    """GET /api/service-calls — list all service calls for a meeting."""
    svc = _service(db)
    calls = svc.list_calls(meeting_id)
    results = [ServiceCallResponse.model_validate(c) for c in calls]
    return ApiResponse.ok(data=results)


@router.get(
    "/current", response_model=ApiResponse[ServiceCallResponse]
)
def get_current(
    meeting_id: int = Query(..., description="Meeting ID"),
    seat_id: int = Query(..., description="Seat ID"),
    db: Session = Depends(get_db),
):
    """GET /api/service-calls/current — get pending call for a seat."""
    svc = _service(db)
    call = svc.get_current(meeting_id, seat_id)
    if call is None:
        return ApiResponse.ok(data=None)
    return ApiResponse.ok(data=ServiceCallResponse.model_validate(call))


@router.post(
    "/{call_id}/resolve", response_model=ApiResponse[ServiceCallResponse]
)
def resolve_call(call_id: int, db: Session = Depends(get_db)):
    """POST /api/service-calls/{call_id}/resolve — resolve a pending call.

    Publishes: service_call_resolved event.
    """
    svc = _service(db)
    try:
        call = svc.resolve_call(call_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=ServiceCallResponse.model_validate(call))


@router.post(
    "/{call_id}/cancel", response_model=ApiResponse[ServiceCallResponse]
)
def cancel_call(call_id: int, db: Session = Depends(get_db)):
    """POST /api/service-calls/{call_id}/cancel — cancel a pending call.

    Publishes: service_call_cancelled event.
    """
    svc = _service(db)
    try:
        call = svc.cancel_call(call_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    return ApiResponse.ok(data=ServiceCallResponse.model_validate(call))
