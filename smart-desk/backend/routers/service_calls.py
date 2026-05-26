from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ServiceCall
from backend.schemas import ServiceCallCreate, ServiceCallUpdate, ServiceCallOut

router = APIRouter(prefix="/api/service-calls", tags=["service_calls"])


@router.get("/{meeting_id}", response_model=List[ServiceCallOut])
def list_service_calls(meeting_id: int, db: Session = Depends(get_db)):
    return db.query(ServiceCall).filter(
        ServiceCall.meeting_id == meeting_id
    ).order_by(ServiceCall.created_at.desc()).all()


@router.post("/{meeting_id}", response_model=ServiceCallOut, status_code=201)
def create_service_call(meeting_id: int, data: ServiceCallCreate, db: Session = Depends(get_db)):
    sc = ServiceCall(meeting_id=meeting_id, seat_id=data.seat_id, service_type=data.service_type)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return sc


@router.patch("/{meeting_id}/{call_id}", response_model=ServiceCallOut)
def update_call_status(meeting_id: int, call_id: int, data: ServiceCallUpdate, db: Session = Depends(get_db)):
    sc = db.query(ServiceCall).filter(
        ServiceCall.id == call_id, ServiceCall.meeting_id == meeting_id
    ).first()
    if not sc:
        raise HTTPException(404, "Service call not found")
    sc.status = data.status
    db.commit()
    db.refresh(sc)
    return sc
