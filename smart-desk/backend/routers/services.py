from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import ServiceCall
from schemas import ServiceCallCreate, ServiceCallOut

router = APIRouter(prefix="/api/services", tags=["services"])


@router.post("", response_model=ServiceCallOut)
def create_service_call(data: ServiceCallCreate, meeting_id: int, db: Session = Depends(get_db)):
    call = ServiceCall(
        meeting_id=meeting_id,
        seat_id=data.seat_id,
        service_type=data.service_type,
    )
    db.add(call)
    db.commit()
    db.refresh(call)
    from ws_manager import manager
    manager.broadcast_sync(str(meeting_id), "service_update", {"call_id": call.id})
    return call


@router.get("/meeting/{meeting_id}", response_model=List[ServiceCallOut])
def list_service_calls(meeting_id: int, db: Session = Depends(get_db)):
    return (
        db.query(ServiceCall)
        .filter(ServiceCall.meeting_id == meeting_id)
        .order_by(ServiceCall.created_at.desc())
        .all()
    )


@router.put("/{call_id}/status", response_model=ServiceCallOut)
def update_call_status(call_id: int, status: str, db: Session = Depends(get_db)):
    call = db.query(ServiceCall).get(call_id)
    if not call:
        raise HTTPException(404, "服务呼叫不存在")
    call.status = status
    db.commit()
    db.refresh(call)
    return call
