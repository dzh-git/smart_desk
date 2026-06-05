from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from backend.database import get_db
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import event_bus
from backend.services.vote_service import (
    VoteService, VoteNotFoundError, VoteClosedError, InvalidVoteOptionError,
    DuplicateOpenVoteError,
)
from backend.utils import _ok

router = APIRouter(prefix="/api/votes", tags=["votes"])


class VoteCreateRequest(BaseModel):
    meeting_id: int
    title: str = Field(..., max_length=500)
    options: list[str] = Field(..., min_length=2)
    is_anonymous: bool = False


class VoteCastRequest(BaseModel):
    attendee_id: int
    option: str


def _get_service(db: Session):
    return VoteService(event_bus, VoteRepository(db))


def _vote_out(v):
    return {
        "id": v.id, "meeting_id": v.meeting_id, "title": v.title,
        "options": v.options, "status": v.status,
        "is_anonymous": v.is_anonymous,
    }


@router.get("/active")
def get_active_vote(meeting_id: int, db: Session = Depends(get_db)):
    repo = VoteRepository(db)
    v = repo.get_active(meeting_id)
    if not v:
        return _ok(None)
    return _ok(_vote_out(v))


@router.post("", status_code=201)
def create_vote(data: VoteCreateRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    try:
        v = svc.create(data.meeting_id, data.title, data.options, data.is_anonymous)
    except DuplicateOpenVoteError:
        raise HTTPException(409, detail="DUPLICATE_OPEN_VOTE")
    except ValueError:
        raise HTTPException(400, detail="INVALID_VOTE_DATA")
    return _ok(_vote_out(v))


@router.get("/{vote_id}")
def get_vote(vote_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.get_by_id(vote_id)
    if not v:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    return _ok(_vote_out(v))


@router.post("/{vote_id}/submit")
def cast_vote(vote_id: int, data: VoteCastRequest, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.get_by_id(vote_id)
    if not v:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    try:
        svc.cast(v.meeting_id, vote_id, data.attendee_id, data.option)
    except VoteClosedError:
        raise HTTPException(400, detail="VOTE_CLOSED")
    except InvalidVoteOptionError:
        raise HTTPException(400, detail="INVALID_OPTION")
    return _ok(_vote_out(v))


@router.get("/{vote_id}/statistics")
def get_vote_statistics(vote_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    try:
        stats = svc.get_statistics(vote_id)
    except VoteNotFoundError:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    return _ok(stats)


@router.post("/{vote_id}/close")
def close_vote(vote_id: int, db: Session = Depends(get_db)):
    svc = _get_service(db)
    v = svc.get_by_id(vote_id)
    if not v:
        raise HTTPException(404, detail="VOTE_NOT_FOUND")
    try:
        v = svc.close(v.meeting_id, vote_id)
    except VoteClosedError:
        raise HTTPException(400, detail="VOTE_ALREADY_CLOSED")
    return _ok(_vote_out(v))
