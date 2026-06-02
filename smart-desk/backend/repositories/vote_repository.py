from __future__ import annotations
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from backend.models import Vote, VoteRecord


class VoteRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, meeting_id: int, title: str, options: list[str], is_anonymous: bool = False) -> Vote:
        v = Vote(meeting_id=meeting_id, title=title, is_anonymous=is_anonymous)
        v.options = options
        self.db.add(v)
        self.db.commit()
        self.db.refresh(v)
        return v

    def get_by_id(self, vote_id: int, meeting_id: int | None = None) -> Vote | None:
        q = self.db.query(Vote).filter(Vote.id == vote_id)
        if meeting_id is not None:
            q = q.filter(Vote.meeting_id == meeting_id)
        return q.first()

    def list_by_meeting(self, meeting_id: int) -> list[Vote]:
        return self.db.query(Vote).filter(Vote.meeting_id == meeting_id).all()

    def get_active(self, meeting_id: int) -> Vote | None:
        return self.db.query(Vote).filter(
            Vote.meeting_id == meeting_id, Vote.status == "open"
        ).first()

    def close(self, vote_id: int) -> Vote | None:
        v = self.get_by_id(vote_id)
        if v:
            v.status = "closed"
            v.closed_at = datetime.now(timezone.utc)
            self.db.commit()
            self.db.refresh(v)
        return v

    def close_all_open(self, meeting_id: int) -> int:
        count = self.db.query(Vote).filter(
            Vote.meeting_id == meeting_id, Vote.status == "open"
        ).update({"status": "closed"})
        self.db.commit()
        return count

    def get_all_open(self, meeting_id: int) -> list[Vote]:
        """Return all open votes for a meeting (used by end() for per-vote close events)."""
        return self.db.query(Vote).filter(
            Vote.meeting_id == meeting_id, Vote.status == "open"
        ).all()

    # -- Vote Records --
    def cast(self, vote_id: int, attendee_id: int, option: str) -> bool:
        existing = self.db.query(VoteRecord).filter(
            VoteRecord.vote_id == vote_id, VoteRecord.attendee_id == attendee_id
        ).first()
        if existing:
            existing.option = option
        else:
            self.db.add(VoteRecord(vote_id=vote_id, attendee_id=attendee_id, option=option))
        self.db.commit()
        return True

    def get_results(self, vote_id: int) -> dict[str, int]:
        v = self.get_by_id(vote_id)
        if not v:
            return {}
        counts: dict[str, int] = {opt: 0 for opt in v.options}
        records = self.db.query(VoteRecord).filter(VoteRecord.vote_id == vote_id).all()
        for r in records:
            counts[r.option] = counts.get(r.option, 0) + 1
        return counts

    def get_voter_ids(self, vote_id: int) -> list[tuple[int, str]]:
        records = self.db.query(VoteRecord).filter(VoteRecord.vote_id == vote_id).all()
        return [(r.attendee_id, r.option) for r in records]
