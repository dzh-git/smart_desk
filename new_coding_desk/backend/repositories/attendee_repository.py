"""
AttendeeRepository — CRUD for attendees.

Per DATABASE_SCHEMA.md §5, §15:
    Owns: attendees
    No business logic.
"""
from __future__ import annotations

from sqlalchemy import exists, or_, select

from backend.models.attendee import Attendee
from backend.models.identity_checkin_event import IdentityCheckInEvent
from backend.models.vote_record import VoteRecord
from backend.repositories.base import BaseRepository


class AttendeeRepository(BaseRepository[Attendee]):
    """Data access for attendees.

    Extends BaseRepository[Attendee] with:
        - List by meeting
    """

    model = Attendee

    def list_by_meeting(self, meeting_id: int) -> list[Attendee]:
        """List all attendees for a meeting."""
        return (
            self.db.query(Attendee)
            .filter(Attendee.meeting_id == meeting_id)
            .all()
        )

    def has_history(self, attendee_id: int) -> bool:
        """Return whether stored identity evidence or ballots reference the attendee."""
        identity_history = exists().where(IdentityCheckInEvent.attendee_id == attendee_id)
        voting_history = exists().where(VoteRecord.attendee_id == attendee_id)
        return bool(self.db.scalar(select(or_(identity_history, voting_history))))

    def get_by_person_and_meeting(
        self,
        person_id: str,
        meeting_id: int,
    ) -> Attendee | None:
        return (
            self.db.query(Attendee)
            .filter(
                Attendee.person_id == person_id,
                Attendee.meeting_id == meeting_id,
            )
            .first()
        )

    def get_by_assigned_seat(
        self,
        meeting_id: int,
        seat_id: int,
    ) -> Attendee | None:
        return (
            self.db.query(Attendee)
            .filter(
                Attendee.meeting_id == meeting_id,
                Attendee.assigned_seat_id == seat_id,
            )
            .first()
        )
