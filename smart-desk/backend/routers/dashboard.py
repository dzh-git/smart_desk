# backend/routers/dashboard.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.dashboard_service import DashboardService
from backend.utils import _ok

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def get_dashboard(meeting_id: int, db: Session = Depends(get_db)):
    svc = DashboardService(
        db,
        MeetingRepository(db), AttendeeRepository(db),
        SeatRepository(db), VoteRepository(db), ServiceCallRepository(db),
    )
    data = svc.get_dashboard(meeting_id)
    if data["meeting"] is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
    return _ok(data)
