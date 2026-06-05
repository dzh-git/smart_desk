from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from backend.database import get_db
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.event_bus import event_bus
from backend.services.service_call_service import (
    ServiceCallService, ServiceCallNotFoundError, DuplicatePendingCallError,
    ServiceCallNotPendingError,
)
from backend.utils import _ok

router = APIRouter(prefix="/api/service-calls", tags=["service_calls"])


class ServiceCallCreateRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=10)
    service_type: str = Field(..., pattern="^(coffee|tea|water|other)$")
    custom_text: str | None = None


def _sc_out(sc):
    return {
        "id": sc.id, "meeting_id": sc.meeting_id, "seat_id": sc.seat_id,
        "service_type": sc.service_type, "custom_text": sc.custom_text,
        "status": sc.status, "cancel_reason": sc.cancel_reason,
        "created_at": str(sc.created_at) if sc.created_at else None,
    }


def _get_service(db: Session):
    return ServiceCallService(event_bus, ServiceCallRepository(db))


@router.get("")
def list_service_calls(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    calls = svc.list_by_meeting(meeting_id)
    return _ok([_sc_out(c) for c in calls])


@router.get("/current")
def get_current_call(meeting_id: int, seat_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    sc = svc.get_pending_by_seat(meeting_id, seat_id)
    return _ok(_sc_out(sc) if sc else None)


@router.post("", status_code=201)
def create_service_call(data: ServiceCallCreateRequest, meeting_id: int,
                         db: Session = Depends(get_db)):
    svc = _get_service(db)
    try:
        sc = svc.create(meeting_id, data.seat_id, data.service_type, data.custom_text)
    except ValueError:
        raise HTTPException(400, detail="INVALID_SERVICE_TYPE")
    except DuplicatePendingCallError:
        raise HTTPException(409, detail="SERVICE_CALL_ALREADY_PENDING")
    return _ok(_sc_out(sc))


@router.post("/{call_id}/resolve")
def resolve_call(call_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    try:
        sc = svc.resolve(call_id)
    except ServiceCallNotFoundError:
        raise HTTPException(404, detail="SERVICE_CALL_NOT_FOUND")
    except ServiceCallNotPendingError:
        raise HTTPException(400, detail="SERVICE_CALL_NOT_PENDING")
    return _ok(_sc_out(sc))


@router.post("/{call_id}/cancel")
def cancel_call(call_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    try:
        sc = svc.cancel(call_id, reason="manual")
    except ServiceCallNotFoundError:
        raise HTTPException(404, detail="SERVICE_CALL_NOT_FOUND")
    except ServiceCallNotPendingError:
        raise HTTPException(400, detail="SERVICE_CALL_NOT_PENDING")
    return _ok(_sc_out(sc))
