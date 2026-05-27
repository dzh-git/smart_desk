from __future__ import annotations
import asyncio
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Vote, VoteRecord, Attendee
from backend.schemas import VoteCreate, VoteCast, VoteOut, VoteResult
from backend.services.ws_service import ws_svc
from backend.services.desk_coordinator import desk

router = APIRouter(prefix="/api/votes", tags=["votes"])


def _vote_out(v: Vote, db: Session) -> VoteOut:
    records = db.query(VoteRecord).filter(VoteRecord.vote_id == v.id).all()
    # Count per option
    counts: dict[str, int] = {opt: 0 for opt in v.options}
    for r in records:
        if r.option in counts:
            counts[r.option] += 1
    results = [VoteResult(option=k, count=c) for k, c in counts.items()]
    return VoteOut(
        id=v.id, meeting_id=v.meeting_id, title=v.title,
        options=v.options, status=v.status, results=results,
    )


@router.get("/{meeting_id}", response_model=List[VoteOut])
def list_votes(meeting_id: int, db: Session = Depends(get_db)):
    votes = db.query(Vote).filter(Vote.meeting_id == meeting_id).all()
    return [_vote_out(v, db) for v in votes]


@router.post("/{meeting_id}", response_model=VoteOut, status_code=201)
def create_vote(meeting_id: int, data: VoteCreate, db: Session = Depends(get_db)):
    import json
    v = Vote(meeting_id=meeting_id, title=data.title)
    v.options = data.options
    db.add(v)
    db.commit()
    db.refresh(v)
    asyncio.run(ws_svc.get_or_create(meeting_id).broadcast(
        {"type": "vote_update", "payload": {"vote_id": v.id}}
    ))
    return _vote_out(v, db)


@router.get("/{meeting_id}/{vote_id}", response_model=VoteOut)
def get_vote(meeting_id: int, vote_id: int, db: Session = Depends(get_db)):
    v = db.query(Vote).filter(Vote.id == vote_id, Vote.meeting_id == meeting_id).first()
    if not v:
        raise HTTPException(404, "Vote not found")
    return _vote_out(v, db)


@router.post("/{meeting_id}/{vote_id}/cast", response_model=VoteOut)
def cast_vote(meeting_id: int, vote_id: int, data: VoteCast, db: Session = Depends(get_db)):
    v = db.query(Vote).filter(Vote.id == vote_id, Vote.meeting_id == meeting_id).first()
    if not v:
        raise HTTPException(404, "Vote not found")
    if v.status != "open":
        raise HTTPException(400, "Vote is closed")
    if data.option not in v.options:
        raise HTTPException(400, f"Invalid option: {data.option}")

    existing = db.query(VoteRecord).filter(
        VoteRecord.vote_id == vote_id, VoteRecord.attendee_id == data.attendee_id
    ).first()
    if existing:
        existing.option = data.option
    else:
        db.add(VoteRecord(vote_id=vote_id, attendee_id=data.attendee_id, option=data.option))

    db.commit()
    asyncio.run(ws_svc.get_or_create(meeting_id).broadcast(
        {"type": "vote_update", "payload": {"vote_id": vote_id}}
    ))
    return _vote_out(v, db)


@router.post("/{meeting_id}/{vote_id}/close", response_model=VoteOut)
def close_vote(meeting_id: int, vote_id: int, db: Session = Depends(get_db)):
    v = db.query(Vote).filter(Vote.id == vote_id, Vote.meeting_id == meeting_id).first()
    if not v:
        raise HTTPException(404, "Vote not found")
    v.status = "closed"
    db.commit()
    asyncio.run(ws_svc.get_or_create(meeting_id).broadcast(
        {"type": "vote_update", "payload": {"vote_id": vote_id}}
    ))
    return _vote_out(v, db)
