from __future__ import annotations
import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Meeting, Agenda, Attendee
from backend.schemas import (
    MeetingCreate, MeetingUpdate, MeetingOut,
    AgendaCreate, AgendaOut,
    AttendeeCreate, AttendeeOut,
)
from backend.services.ws_service import ws_svc
from backend.services.desk_coordinator import desk

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _meeting_out(m: Meeting, db: Session) -> MeetingOut:
    total = db.query(Attendee).filter(Attendee.meeting_id == m.id).count()
    checked = db.query(Attendee).filter(
        Attendee.meeting_id == m.id, Attendee.checked_in == True
    ).count()
    return MeetingOut(
        id=m.id, title=m.title, description=m.description,
        status=m.status, created_at=m.created_at,
        attendee_count=total, checked_in_count=checked,
    )


@router.get("", response_model=List[MeetingOut])
def list_meetings(db: Session = Depends(get_db)):
    return [_meeting_out(m, db) for m in db.query(Meeting).order_by(Meeting.created_at.desc()).all()]


@router.post("", response_model=MeetingOut, status_code=201)
def create_meeting(data: MeetingCreate, db: Session = Depends(get_db)):
    m = Meeting(title=data.title, description=data.description)
    db.add(m)
    db.commit()
    db.refresh(m)
    return _meeting_out(m, db)


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    m = db.query(Meeting).get(meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    return _meeting_out(m, db)


@router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(meeting_id: int, data: MeetingUpdate, db: Session = Depends(get_db)):
    m = db.query(Meeting).get(meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    if data.title is not None:
        m.title = data.title
    if data.description is not None:
        m.description = data.description
    new_status = None
    if data.status is not None:
        new_status = data.status
        m.status = data.status
    db.commit()
    db.refresh(m)
    # Broadcast meeting status change
    if new_status == "finished":
        await desk.on_meeting_end(meeting_id)
    elif new_status == "active":
        # Fire-and-forget model preload for translation
        from backend.routers.translation import preload_models
        asyncio.create_task(preload_models())
        await ws_svc.get_or_create(meeting_id).broadcast(
            {"type": "meeting_started", "payload": {}}
        )
    return _meeting_out(m, db)


@router.delete("/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    m = db.query(Meeting).get(meeting_id)
    if not m:
        raise HTTPException(404, "Meeting not found")
    db.delete(m)
    db.commit()


# ── Agendas ──

@router.get("/{meeting_id}/agendas", response_model=List[AgendaOut])
def list_agendas(meeting_id: int, db: Session = Depends(get_db)):
    return db.query(Agenda).filter(Agenda.meeting_id == meeting_id).order_by(Agenda.sort_order).all()


@router.post("/{meeting_id}/agendas", response_model=AgendaOut, status_code=201)
def add_agenda(meeting_id: int, data: AgendaCreate, db: Session = Depends(get_db)):
    a = Agenda(meeting_id=meeting_id, title=data.title, sort_order=data.sort_order)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{meeting_id}/agendas/{agenda_id}", status_code=204)
def remove_agenda(meeting_id: int, agenda_id: int, db: Session = Depends(get_db)):
    a = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.meeting_id == meeting_id).first()
    if not a:
        raise HTTPException(404, "Agenda not found")
    db.delete(a)
    db.commit()


# ── Attendees ──

@router.get("/{meeting_id}/attendees", response_model=List[AttendeeOut])
def list_attendees(meeting_id: int, db: Session = Depends(get_db)):
    return db.query(Attendee).filter(Attendee.meeting_id == meeting_id).all()


@router.post("/{meeting_id}/attendees", response_model=AttendeeOut, status_code=201)
def add_attendee(meeting_id: int, data: AttendeeCreate, db: Session = Depends(get_db)):
    a = Attendee(meeting_id=meeting_id, name=data.name, title=data.title, seat_id=data.seat_id)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/{meeting_id}/attendees/{attendee_id}", status_code=204)
def remove_attendee(meeting_id: int, attendee_id: int, db: Session = Depends(get_db)):
    a = db.query(Attendee).filter(Attendee.id == attendee_id, Attendee.meeting_id == meeting_id).first()
    if not a:
        raise HTTPException(404, "Attendee not found")
    db.delete(a)
    db.commit()
