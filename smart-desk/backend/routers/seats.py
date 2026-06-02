"""
Seat router — seat listing, check-in (pre-assigned only), speaker seat management.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from backend.database import get_db
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.event_bus import event_bus
from backend.services.seat_service import SeatService

router = APIRouter(prefix="/api/seats", tags=["seats"])


class CheckInRequest(BaseModel):
    attendee_id: int = Field(..., gt=0)


class SpeakerSeatRequest(BaseModel):
    seat_id: int = Field(..., ge=0, le=10)  # 0 = clear


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


def _get_service(db: Session):
    return SeatService(db, event_bus, SeatRepository(db), AttendeeRepository(db))


@router.get("")
def list_seats(db: Session = Depends(get_db)):
    repo = SeatRepository(db)
    seats = repo.get_all_seats()
    return _ok([{"seat_id": s.seat_id, "status": s.status,
                  "attendee_id": s.attendee_id} for s in seats])


@router.post("/{seat_id}/checkin")
def checkin(seat_id: int, data: CheckInRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    # Verify attendee is pre-assigned to this seat
    att = svc.attendee_repo.get_by_id(data.attendee_id)
    if not att:
        raise HTTPException(404, detail="ATTENDEE_NOT_FOUND")
    if att.seat_id != seat_id:
        raise HTTPException(400, detail="ATTENDEE_NOT_ASSIGNED_TO_THIS_SEAT")

    result = svc.checkin(att.meeting_id, seat_id, data.attendee_id)
    if result is None:
        raise HTTPException(409, detail="SEAT_ALREADY_CHECKED_IN")
    return _ok({"seat_id": seat_id, "status": result.status})


@router.get("/speaker")
def get_speaker_seat(db: Session = Depends(get_db)):
    repo = SeatRepository(db)
    sp = repo.get_speaker_seat()
    return _ok({"seat_id": sp.seat_id} if sp else {"seat_id": None})


@router.post("/speaker")
def set_speaker_seat(data: SpeakerSeatRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    # Determine meeting_id from active meeting
    from backend.repositories.meeting_repository import MeetingRepository
    mr = MeetingRepository(db)
    active = mr.get_active()
    if not active:
        raise HTTPException(400, detail="NO_ACTIVE_MEETING")
    if data.seat_id == 0:
        svc.clear_speaker_seat(active.id)
    else:
        svc.set_speaker_seat(active.id, data.seat_id)
    sp = svc.get_speaker_seat()
    return _ok({"seat_id": sp.seat_id} if sp else {"seat_id": None})


@router.delete("/speaker")
def clear_speaker_seat(db: Session = Depends(get_db)):
    svc = _get_service(db)
    from backend.repositories.meeting_repository import MeetingRepository
    mr = MeetingRepository(db)
    active = mr.get_active()
    if not active:
        raise HTTPException(400, detail="NO_ACTIVE_MEETING")
    svc.clear_speaker_seat(active.id)
    return _ok({"seat_id": None})
