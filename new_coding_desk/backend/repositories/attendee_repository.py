"""
AttendeeRepository — CRUD for attendees.

Per DATABASE_SCHEMA.md §5, §15:
    Owns: attendees
    No business logic.
"""
from __future__ import annotations

from backend.models.attendee import Attendee
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
