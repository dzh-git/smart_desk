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
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.events import event_bus
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.vote import (
    VoteCreate,
    VoteSubmit,
    VoteResponse,
    VoteStatistics,
)
from backend.services.vote_service import VoteService

router = APIRouter(prefix="/api/votes", tags=["votes"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _service(db: Session) -> VoteService:
    return VoteService(db, event_bus)


def _to_json(api_response: ApiResponse, status_code: int = 200) -> JSONResponse:
    """Serialize ApiResponse to JSONResponse with the given HTTP status."""
    return JSONResponse(
        content=api_response.model_dump(),
        status_code=status_code,
    )


def _build_vote_response(vote, total_votes: int) -> VoteResponse:
    """Construct VoteResponse from ORM Vote, parsing options_json."""
    options: list[str] = json.loads(vote.options_json)
    return VoteResponse(
        id=vote.id,
        meeting_id=vote.meeting_id,
        title=vote.title,
        options=options,
        is_anonymous=vote.is_anonymous,
        status=vote.status,
        total_votes=total_votes,
        created_at=vote.created_at,
        closed_at=vote.closed_at,
    )


# ── Vote endpoints ───────────────────────────────────────────────────────────


@router.get("/active", response_model=ApiResponse[VoteResponse])
def get_active_vote(db: Session = Depends(get_db)):
    """GET /api/votes/active — get the currently open vote."""
    svc = _service(db)
    vote = svc.get_active_vote()
    if vote is None:
        return ApiResponse.ok(data=None)
    total = svc.get_record_count(vote.id)
    return ApiResponse.ok(data=_build_vote_response(vote, total))


@router.post("", response_model=ApiResponse[VoteResponse], status_code=201)
def create_vote(body: VoteCreate, db: Session = Depends(get_db)):
    """POST /api/votes — create a new vote.

    Publishes: vote_started event.
    """
    svc = _service(db)
    try:
        vote = svc.create_vote(
            meeting_id=body.meeting_id,
            title=body.title,
            options=body.options,
            is_anonymous=body.is_anonymous,
        )
    except ConflictError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 409)
    total = svc.get_record_count(vote.id)
    return ApiResponse.ok(data=_build_vote_response(vote, total))


@router.get("/{vote_id}", response_model=ApiResponse[VoteResponse])
def get_vote(vote_id: int, db: Session = Depends(get_db)):
    """GET /api/votes/{vote_id} — get a vote by ID."""
    svc = _service(db)
    try:
        vote = svc.get_vote(vote_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    total = svc.get_record_count(vote.id)
    return ApiResponse.ok(data=_build_vote_response(vote, total))


@router.post("/{vote_id}/submit", response_model=ApiResponse[VoteResponse])
def submit_vote(vote_id: int, body: VoteSubmit, db: Session = Depends(get_db)):
    """POST /api/votes/{vote_id}/submit — cast or update a ballot.

    Publishes: vote_updated event.
    """
    svc = _service(db)
    try:
        vote = svc.submit_vote(
            vote_id=vote_id,
            attendee_id=body.attendee_id,
            option=body.option,
        )
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    except ValidationError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 400)
    total = svc.get_record_count(vote.id)
    return ApiResponse.ok(data=_build_vote_response(vote, total))


@router.get(
    "/{vote_id}/statistics", response_model=ApiResponse[VoteStatistics]
)
def get_vote_statistics(vote_id: int, db: Session = Depends(get_db)):
    """GET /api/votes/{vote_id}/statistics — get vote results."""
    svc = _service(db)
    try:
        stats = svc.get_statistics(vote_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    return ApiResponse.ok(data=stats)


@router.post("/{vote_id}/close", response_model=ApiResponse[VoteResponse])
def close_vote(vote_id: int, db: Session = Depends(get_db)):
    """POST /api/votes/{vote_id}/close — close a vote.

    Publishes: vote_closed event.
    """
    svc = _service(db)
    try:
        vote = svc.close_vote(vote_id)
    except NotFoundError as e:
        return _to_json(ApiResponse.fail(e.message, e.error_code), 404)
    total = svc.get_record_count(vote.id)
    return ApiResponse.ok(data=_build_vote_response(vote, total))
