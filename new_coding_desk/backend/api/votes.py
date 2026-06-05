"""
Vote API — create vote, cast ballot, get results, close.

Per API_SPEC §8:
    GET   /api/votes/active                → VoteService
    POST  /api/votes                       → VoteService  + vote_started event
    GET   /api/votes/{vote_id}             → VoteService
    POST  /api/votes/{vote_id}/submit      → VoteService  + vote_updated event
    GET   /api/votes/{vote_id}/statistics  → VoteService
    POST  /api/votes/{vote_id}/close       → VoteService  + vote_closed event
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.services.vote_service import VoteService
from backend.utils import _ok

router = APIRouter(prefix="/api/votes", tags=["votes"])


# ── Request models ────────────────────────────────────────────────────────────


class VoteCreateRequest(BaseModel):
    meeting_id: int
    title: str = Field(..., max_length=500)
    options: list[str] = Field(..., min_length=2)
    is_anonymous: bool = False


class VoteCastRequest(BaseModel):
    attendee_id: int
    option: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _vote_out(v) -> dict:
    """Serialize Vote ORM object to API response dict."""
    options: list[str] = json.loads(v.options_json)
    return {
        "id": v.id,
        "meeting_id": v.meeting_id,
        "title": v.title,
        "options": options,
        "status": v.status,
        "is_anonymous": v.is_anonymous,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/active")
def get_active_vote(db: Session = Depends(get_db)):
    """GET /api/votes/active — get the currently open vote."""
    svc = VoteService(db, event_bus)
    v = svc.get_active_vote()
    if not v:
        return _ok(None)
    return _ok(_vote_out(v))


@router.post("", status_code=201)
def create_vote(data: VoteCreateRequest, db: Session = Depends(get_db)):
    """POST /api/votes — create a new vote.

    Publishes: vote_started event.
    """
    if not data.title or not data.title.strip():
        raise HTTPException(400, detail="EMPTY_TITLE")
    svc = VoteService(db, event_bus)
    try:
        v = svc.create_vote(
            meeting_id=data.meeting_id,
            title=data.title,
            options=data.options,
            is_anonymous=data.is_anonymous,
        )
    except ConflictError as e:
        raise HTTPException(409, detail=e.error_code)
    return _ok(_vote_out(v))


@router.get("/{vote_id}")
def get_vote(vote_id: int, db: Session = Depends(get_db)):
    """GET /api/votes/{vote_id} — get a vote by ID."""
    svc = VoteService(db, event_bus)
    try:
        v = svc.get_vote(vote_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=e.error_code)
    return _ok(_vote_out(v))


@router.post("/{vote_id}/submit")
def cast_vote(vote_id: int, data: VoteCastRequest, db: Session = Depends(get_db)):
    """POST /api/votes/{vote_id}/submit — cast or update a ballot.

    Publishes: vote_updated event.
    """
    svc = VoteService(db, event_bus)
    try:
        v = svc.submit_vote(
            vote_id=vote_id,
            attendee_id=data.attendee_id,
            option=data.option,
        )
    except NotFoundError as e:
        raise HTTPException(404, detail=e.error_code)
    except ValidationError as e:
        raise HTTPException(400, detail=e.error_code)
    return _ok(_vote_out(v))


@router.get("/{vote_id}/statistics")
def get_vote_statistics(vote_id: int, db: Session = Depends(get_db)):
    """GET /api/votes/{vote_id}/statistics — get vote results."""
    svc = VoteService(db, event_bus)
    try:
        stats = svc.get_statistics(vote_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=e.error_code)
    return _ok(stats.model_dump())


@router.post("/{vote_id}/close")
def close_vote(vote_id: int, db: Session = Depends(get_db)):
    """POST /api/votes/{vote_id}/close — close a vote.

    Publishes: vote_closed event.
    """
    svc = VoteService(db, event_bus)
    try:
        v = svc.close_vote(vote_id)
    except NotFoundError as e:
        raise HTTPException(404, detail=e.error_code)
    return _ok(_vote_out(v))
