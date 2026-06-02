from __future__ import annotations
from sqlalchemy.orm import Session
from backend.models import Attendee, Vote, VoteRecord, ServiceCall


class AttendeeRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, meeting_id: int, name: str, title: str = "", seat_id: int | None = None) -> Attendee:
        a = Attendee(meeting_id=meeting_id, name=name, title=title, seat_id=seat_id)
        self.db.add(a)
        self.db.commit()
        self.db.refresh(a)
        return a

    def get_by_id(self, attendee_id: int) -> Attendee | None:
        return self.db.query(Attendee).filter(Attendee.id == attendee_id).first()

    def list_by_meeting(self, meeting_id: int) -> list[Attendee]:
        return self.db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id
        ).order_by(Attendee.id).all()

    def get_by_seat(self, meeting_id: int, seat_id: int) -> Attendee | None:
        return self.db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id, Attendee.seat_id == seat_id
        ).first()

    def check_in(self, attendee_id: int) -> Attendee | None:
        a = self.get_by_id(attendee_id)
        if a:
            a.checked_in = True
            self.db.commit()
            self.db.refresh(a)
        return a

    def count_by_meeting(self, meeting_id: int) -> int:
        return self.db.query(Attendee).filter(Attendee.meeting_id == meeting_id).count()

    def count_checked_in(self, meeting_id: int) -> int:
        return self.db.query(Attendee).filter(
            Attendee.meeting_id == meeting_id, Attendee.checked_in == True
        ).count()

    def delete(self, attendee_id: int) -> bool:
        a = self.get_by_id(attendee_id)
        if a:
            self.db.delete(a)
            self.db.commit()
            return True
        return False

    def uncheck(self, attendee_id: int) -> Attendee | None:
        """Reset checked_in flag for re-seat auto-binding flow."""
        a = self.get_by_id(attendee_id)
        if a:
            a.checked_in = False
            self.db.commit()
            self.db.refresh(a)
        return a

    def has_history(self, meeting_id: int, attendee_id: int) -> bool:
        """Check if attendee has participated (checked in, voted, or made service calls)."""
        a = self.get_by_id(attendee_id)
        if not a:
            return False
        if a.meeting_id != meeting_id:
            return False
        if a.checked_in:
            return True
        has_vote = self.db.query(VoteRecord).join(
            Vote, VoteRecord.vote_id == Vote.id
        ).filter(
            VoteRecord.attendee_id == attendee_id,
            Vote.meeting_id == meeting_id,
        ).first() is not None
        has_call = self.db.query(ServiceCall).filter(
            ServiceCall.attendee_id == attendee_id,
            ServiceCall.meeting_id == meeting_id,
        ).first() is not None
        return has_vote or has_call
