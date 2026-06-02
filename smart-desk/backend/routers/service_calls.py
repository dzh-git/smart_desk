from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ServiceCall
from backend.schemas import ServiceCallCreate, ServiceCallUpdate, ServiceCallOut
from backend.services.event_bus import event_bus, BaseEvent

router = APIRouter(prefix="/api/service-calls", tags=["service_calls"])


def persist_service_call(meeting_id: int, seat_id: int, service_type: str) -> ServiceCall:
    """Create a service call from WS. Returns the created ServiceCall."""
    from backend.database import SessionLocal
    from backend.models import Attendee
    db = SessionLocal()
    try:
        # Look up the attendee at this seat to link the service call
        attendee = db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id, Attendee.seat_id == seat_id
        ).first()
        sc = ServiceCall(
            meeting_id=meeting_id,
            seat_id=seat_id,
            attendee_id=attendee.id if attendee else None,
            service_type=service_type,
            status="pending",
        )
        db.add(sc)
        db.commit()
        db.refresh(sc)
        event_bus.publish(BaseEvent(
            name="service_call_created",
            payload={
                "meeting_id": meeting_id,
                "seat_id": seat_id,
                "service_type": service_type,
            },
        ))
        return sc
    finally:
        db.close()


@router.get("/{meeting_id}", response_model=List[ServiceCallOut])
def list_service_calls(meeting_id: int, db: Session = Depends(get_db)):
    return db.query(ServiceCall).filter(
        ServiceCall.meeting_id == meeting_id
    ).order_by(ServiceCall.created_at.desc()).all()


@router.post("/{meeting_id}", response_model=ServiceCallOut, status_code=201)
def create_service_call(meeting_id: int, data: ServiceCallCreate, db: Session = Depends(get_db)):
    sc = ServiceCall(meeting_id=meeting_id, seat_id=data.seat_id, attendee_id=data.attendee_id, service_type=data.service_type)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    event_bus.publish(BaseEvent(
        name="service_call_created",
        payload={"meeting_id": meeting_id, "seat_id": data.seat_id},
    ))
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
