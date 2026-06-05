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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.services.service_call_service import ServiceCallService
from backend.utils import _ok

router = APIRouter(prefix="/api/service-calls", tags=["service_calls"])


# ── Request models ────────────────────────────────────────────────────────────


class ServiceCallCreateRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=10)
    service_type: str = Field(..., pattern="^(coffee|tea|water|other)$")
    custom_text: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _sc_out(sc) -> dict:
    """Serialize ServiceCall ORM object to API response dict."""
    return {
        "id": sc.id,
        "meeting_id": sc.meeting_id,
        "seat_id": sc.seat_id,
        "service_type": sc.service_type,
        "status": sc.status,
        "created_at": str(sc.created_at) if sc.created_at else None,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
def list_service_calls(meeting_id: int, db: Session = Depends(get_db)):
    """GET /api/service-calls — list all service calls for a meeting."""
    svc = ServiceCallService(db, event_bus)
    calls = svc.list_calls(meeting_id)
    return _ok([_sc_out(c) for c in calls])


@router.get("/current")
def get_current_call(meeting_id: int, seat_id: int, db: Session = Depends(get_db)):
    """GET /api/service-calls/current — get pending call for a seat."""
    svc = ServiceCallService(db, event_bus)
    sc = svc.get_current(meeting_id, seat_id)
    return _ok(_sc_out(sc) if sc else None)


@router.post("", status_code=201)
def create_service_call(
    data: ServiceCallCreateRequest,
    meeting_id: int,
    db: Session = Depends(get_db),
):
    """POST /api/service-calls — create a new service call.

    Publishes: service_call_created event.
    """
    svc = ServiceCallService(db, event_bus)
    try:
        sc = svc.create_call(
            meeting_id=meeting_id,
            seat_id=data.seat_id,
            service_type=data.service_type,
        )
    except ConflictError as e:
        raise HTTPException(409, detail=e.error_code)
    return _ok(_sc_out(sc))


@router.post("/{call_id}/resolve")
def resolve_call(call_id: int, db: Session = Depends(get_db)):
    """POST /api/service-calls/{call_id}/resolve — resolve a pending call.

    Publishes: service_call_resolved event.
    """
    svc = ServiceCallService(db, event_bus)
    try:
        sc = svc.resolve_call(call_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=e.error_code)
    except ValidationError as e:
        raise HTTPException(400, detail=e.error_code)
    return _ok(_sc_out(sc))


@router.post("/{call_id}/cancel")
def cancel_call(call_id: int, db: Session = Depends(get_db)):
    """POST /api/service-calls/{call_id}/cancel — cancel a pending call.

    Publishes: service_call_cancelled event.
    """
    svc = ServiceCallService(db, event_bus)
    try:
        sc = svc.cancel_call(call_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=e.error_code)
    except ValidationError as e:
        raise HTTPException(400, detail=e.error_code)
    return _ok(_sc_out(sc))
