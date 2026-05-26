from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Meeting, Agenda, Attendee
from schemas import (
    MeetingCreate, MeetingUpdate, MeetingOut,
    AgendaCreate, AgendaOut,
    AttendeeCreate, AttendeeOut, CheckInRequest,
)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


# ── Meeting CRUD ──
@router.get("", response_model=List[MeetingOut])
def list_meetings(db: Session = Depends(get_db)):
    return db.query(Meeting).order_by(Meeting.created_at.desc()).all()


@router.post("", response_model=MeetingOut)
def create_meeting(data: MeetingCreate, db: Session = Depends(get_db)):
    meeting = Meeting(title=data.title, description=data.description)
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


@router.get("/{meeting_id}", response_model=MeetingOut)
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).get(meeting_id)
    if not meeting:
        raise HTTPException(404, "会议不存在")
    return meeting


@router.put("/{meeting_id}", response_model=MeetingOut)
def update_meeting(meeting_id: int, data: MeetingUpdate, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).get(meeting_id)
    if not meeting:
        raise HTTPException(404, "会议不存在")
    if data.title is not None:
        meeting.title = data.title
    if data.description is not None:
        meeting.description = data.description
    if data.status is not None:
        meeting.status = data.status
    db.commit()
    db.refresh(meeting)
    return meeting


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    meeting = db.query(Meeting).get(meeting_id)
    if not meeting:
        raise HTTPException(404, "会议不存在")
    db.delete(meeting)
    db.commit()
    return {"ok": True}


# ── Agendas ──
@router.get("/{meeting_id}/agendas", response_model=List[AgendaOut])
def list_agendas(meeting_id: int, db: Session = Depends(get_db)):
    return db.query(Agenda).filter(Agenda.meeting_id == meeting_id).order_by(Agenda.sort_order).all()


@router.post("/{meeting_id}/agendas", response_model=AgendaOut)
def add_agenda(meeting_id: int, data: AgendaCreate, db: Session = Depends(get_db)):
    agenda = Agenda(meeting_id=meeting_id, title=data.title, sort_order=data.sort_order)
    db.add(agenda)
    db.commit()
    db.refresh(agenda)
    return agenda


@router.delete("/{meeting_id}/agendas/{agenda_id}")
def remove_agenda(meeting_id: int, agenda_id: int, db: Session = Depends(get_db)):
    agenda = db.query(Agenda).filter(Agenda.id == agenda_id, Agenda.meeting_id == meeting_id).first()
    if not agenda:
        raise HTTPException(404, "议程不存在")
    db.delete(agenda)
    db.commit()
    return {"ok": True}


# ── Attendees ──
@router.get("/{meeting_id}/attendees", response_model=List[AttendeeOut])
def list_attendees(meeting_id: int, db: Session = Depends(get_db)):
    return db.query(Attendee).filter(Attendee.meeting_id == meeting_id).all()


@router.post("/{meeting_id}/attendees", response_model=AttendeeOut)
def add_attendee(meeting_id: int, data: AttendeeCreate, db: Session = Depends(get_db)):
    attendee = Attendee(
        meeting_id=meeting_id,
        name=data.name,
        title=data.title,
        rfid_card=data.rfid_card,
        seat_id=data.seat_id,
    )
    db.add(attendee)
    db.commit()
    db.refresh(attendee)
    return attendee


@router.delete("/{meeting_id}/attendees/{attendee_id}")
def remove_attendee(meeting_id: int, attendee_id: int, db: Session = Depends(get_db)):
    attendee = db.query(Attendee).filter(Attendee.id == attendee_id, Attendee.meeting_id == meeting_id).first()
    if not attendee:
        raise HTTPException(404, "参会者不存在")
    db.delete(attendee)
    db.commit()
    return {"ok": True}


@router.post("/{meeting_id}/checkin", response_model=AttendeeOut)
def checkin(meeting_id: int, data: CheckInRequest, db: Session = Depends(get_db)):
    attendee = db.query(Attendee).filter(
        Attendee.meeting_id == meeting_id,
        Attendee.rfid_card == data.rfid_card,
    ).first()
    if not attendee:
        raise HTTPException(404, "未找到匹配的参会者")
    attendee.checked_in = True
    db.commit()
    db.refresh(attendee)
    return attendee
