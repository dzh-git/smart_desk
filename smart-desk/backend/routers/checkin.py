"""
Check-in router — UI-based seat confirmation (no RFID).
"""
from __future__ import annotations
import asyncio
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Attendee
from backend.schemas import CheckInRequest, AttendeeOut
from backend.services.ws_service import ws_svc

router = APIRouter(prefix="/api/checkin", tags=["checkin"])


@router.post("/{meeting_id}", response_model=AttendeeOut)
async def check_in(meeting_id: int, data: CheckInRequest, db: Session = Depends(get_db)):
    """Confirm attendance for a seat. Creates anonymous attendee if none assigned."""
    attendee = db.query(Attendee).filter(
        Attendee.meeting_id == meeting_id,
        Attendee.seat_id == data.seat_id,
    ).first()

    if attendee:
        attendee.checked_in = True
    else:
        attendee = Attendee(
            meeting_id=meeting_id,
            name=f"座位 {data.seat_id}",
            seat_id=data.seat_id,
            checked_in=True,
        )
        db.add(attendee)

    db.commit()
    db.refresh(attendee)

    # Broadcast to all tablets in this meeting
    room = ws_svc.get_or_create(meeting_id)
    await room.broadcast({
        "type": "check_in",
        "payload": {"seat_id": data.seat_id, "name": attendee.name},
    })

    return attendee
