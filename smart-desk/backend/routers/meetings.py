from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.models import Meeting
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import event_bus
from backend.services.meeting_service import MeetingService
from backend.schemas import MeetingCreate, MeetingUpdate, MeetingOut, AgendaCreate, AgendaOut

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _get_service(db: Session):
    return MeetingService(
        db, event_bus,
        MeetingRepository(db), AttendeeRepository(db),
        SeatRepository(db), VoteRepository(db),
    )


def _meeting_out(m: Meeting, db: Session) -> MeetingOut:
    attendee_repo = AttendeeRepository(db)
    total = attendee_repo.count_by_meeting(m.id)
    checked = attendee_repo.count_checked_in(m.id)
    return MeetingOut(
        id=m.id, title=m.title, description=m.description or "",
        status=m.status, created_at=m.created_at,
        attendee_count=total, checked_in_count=checked,
    )


def _ok(data):
    return {"success": True, "message": "OK", "data": data}


@router.get("")
def list_meetings(db: Session = Depends(get_db)):
    svc = _get_service(db)
    meetings = svc.list_all()
    return _ok([_meeting_out(m, db) for m in meetings])


@router.post("", status_code=201)
def create_meeting(data: MeetingCreate, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.create(data.title, data.description)
    if m is None:
        raise HTTPException(400, detail="ACTIVE_MEETING_EXISTS")
    return _ok(_meeting_out(m, db))


@router.get("/active")
def get_active_meeting(db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.get_active()
    if not m:
        return _ok(None)
    return _ok(_meeting_out(m, db))


@router.get("/{meeting_id}")
def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.get_by_id(meeting_id)
    if not m:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    return _ok(_meeting_out(m, db))


@router.patch("/{meeting_id}")
def update_meeting(meeting_id: int, data: MeetingUpdate, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.get_by_id(meeting_id)
    if not m:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    if data.title is not None:
        m.title = data.title
    if data.description is not None:
        m.description = data.description
    db.commit()
    db.refresh(m)
    return _ok(_meeting_out(m, db))


@router.post("/{meeting_id}/start")
def start_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.start(meeting_id)
    if not m:
        raise HTTPException(400, detail="ACTIVE_MEETING_EXISTS")
    return _ok(_meeting_out(m, db))


@router.post("/{meeting_id}/end")
def end_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    m = svc.end(meeting_id)
    if not m:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    return _ok(_meeting_out(m, db))


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    ok = svc.delete(meeting_id)
    if not ok:
        raise HTTPException(404, detail="MEETING_NOT_FOUND")
    return _ok(None)


# Agendas (delegated to service)
@router.get("/{meeting_id}/agendas")
def list_agendas(meeting_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    agendas = svc.list_agendas(meeting_id)
    return _ok([AgendaOut.model_validate(a) for a in agendas])


@router.post("/{meeting_id}/agendas", status_code=201)
def add_agenda(meeting_id: int, data: AgendaCreate, db: Session = Depends(get_db)):
    svc = _get_service(db)
    a = svc.add_agenda(meeting_id, data.title, data.sort_order)
    return _ok(AgendaOut.model_validate(a))


@router.delete("/{meeting_id}/agendas/{agenda_id}")
def remove_agenda(meeting_id: int, agenda_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    ok = svc.remove_agenda(meeting_id, agenda_id)
    if not ok:
        raise HTTPException(404, detail="AGENDA_NOT_FOUND")
    return _ok(None)
