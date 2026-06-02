from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.event_bus import event_bus
from backend.services.meeting_service import MeetingService
from backend.schemas import AttendeeCreate, AttendeeOut

router = APIRouter(prefix="/api/meetings/{meeting_id}/attendees", tags=["attendees"])


def _get_meeting_service(db: Session = Depends(get_db)):
    return MeetingService(
        db, event_bus,
        MeetingRepository(db), AttendeeRepository(db),
        None, None  # seat_repo and vote_repo not needed for attendee ops
    )


@router.get("")
def list_attendees(meeting_id: int, db: Session = Depends(get_db)):
    repo = AttendeeRepository(db)
    attendees = repo.list_by_meeting(meeting_id)
    return {"success": True, "message": "OK", "data": [AttendeeOut.model_validate(a) for a in attendees]}


@router.post("", status_code=201)
def add_attendee(meeting_id: int, data: AttendeeCreate, db: Session = Depends(get_db)):
    repo = AttendeeRepository(db)
    a = repo.create(meeting_id, data.name, data.title, data.seat_id)
    return {"success": True, "message": "OK", "data": AttendeeOut.model_validate(a)}


@router.delete("/{attendee_id}", status_code=200)
def remove_attendee(meeting_id: int, attendee_id: int, db: Session = Depends(get_db)):
    svc = _get_meeting_service(db)
    ok = svc.remove_attendee(meeting_id, attendee_id)
    if not ok:
        raise HTTPException(400, detail="ATTENDEE_HAS_HISTORY")
    return {"success": True, "message": "OK", "data": None}
