from __future__ import annotations
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Vote, VoteRecord, Attendee
from schemas import VoteCreate, VoteCast, VoteResult, VoteOut

router = APIRouter(prefix="/api/votes", tags=["votes"])


def _build_vote_out(vote: Vote, db: Session) -> VoteOut:
    results: dict[str, int] = {opt: 0 for opt in vote.options}
    for record in vote.records:
        if record.option in results:
            results[record.option] += 1
    return VoteOut(
        id=vote.id,
        meeting_id=vote.meeting_id,
        title=vote.title,
        options=vote.options,
        status=vote.status,
        results=[VoteResult(option=k, count=v) for k, v in results.items()],
    )


@router.post("", response_model=VoteOut)
def create_vote(data: VoteCreate, meeting_id: int, db: Session = Depends(get_db)):
    vote = Vote(meeting_id=meeting_id, title=data.title, options=data.options, status="open")
    db.add(vote)
    db.commit()
    db.refresh(vote)
    result = _build_vote_out(vote, db)
    from ws_manager import manager
    manager.broadcast_sync(str(meeting_id), "vote_update", {"vote_id": vote.id})
    return result


@router.get("/{vote_id}", response_model=VoteOut)
def get_vote(vote_id: int, db: Session = Depends(get_db)):
    vote = db.query(Vote).get(vote_id)
    if not vote:
        raise HTTPException(404, "投票不存在")
    return _build_vote_out(vote, db)


@router.get("/meeting/{meeting_id}", response_model=List[VoteOut])
def list_votes(meeting_id: int, db: Session = Depends(get_db)):
    votes = db.query(Vote).filter(Vote.meeting_id == meeting_id).all()
    return [_build_vote_out(v, db) for v in votes]


@router.post("/{vote_id}/cast", response_model=VoteOut)
def cast_vote(vote_id: int, data: VoteCast, db: Session = Depends(get_db)):
    vote = db.query(Vote).get(vote_id)
    if not vote:
        raise HTTPException(404, "投票不存在")
    if vote.status != "open":
        raise HTTPException(400, "投票已关闭")

    attendee = db.query(Attendee).get(data.attendee_id)
    if not attendee:
        raise HTTPException(404, "参会者不存在")

    # one vote per attendee — replace if exists
    existing = db.query(VoteRecord).filter(
        VoteRecord.vote_id == vote_id,
        VoteRecord.attendee_id == data.attendee_id,
    ).first()
    if existing:
        existing.option = data.option
    else:
        db.add(VoteRecord(vote_id=vote_id, attendee_id=data.attendee_id, option=data.option))

    db.commit()
    db.refresh(vote)
    result = _build_vote_out(vote, db)
    # broadcast updated results
    from ws_manager import manager
    manager.broadcast_sync(str(vote.meeting_id), "vote_update", {"vote_id": vote.id})
    return result


@router.post("/{vote_id}/close", response_model=VoteOut)
def close_vote(vote_id: int, db: Session = Depends(get_db)):
    vote = db.query(Vote).get(vote_id)
    if not vote:
        raise HTTPException(404, "投票不存在")
    vote.status = "closed"
    db.commit()
    db.refresh(vote)
    result = _build_vote_out(vote, db)
    from ws_manager import manager
    manager.broadcast_sync(str(vote.meeting_id), "vote_update", {"vote_id": vote.id})
    return result
