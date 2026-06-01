"""
MeetingRepository — CRUD for meetings + agendas.

Per DATABASE_SCHEMA.md §3-4, §15:
    Owns: meetings, agendas
    No business logic.
"""
from __future__ import annotations

from backend.models.meeting import Meeting
from backend.models.agenda import Agenda
from backend.repositories.base import BaseRepository


class MeetingRepository(BaseRepository[Meeting]):
    """Data access for meetings and agendas.

    Extends BaseRepository[Meeting] with:
        - Active meeting lookup
        - Agenda CRUD
    """

    model = Meeting

    # ── Meeting queries ──────────────────────────────────────────────────────

    def get_active_meeting(self) -> Meeting | None:
        """Return the meeting with status='active', or None."""
        return self.db.query(Meeting).filter(Meeting.status == "active").first()

    def list_by_status(self, status: str) -> list[Meeting]:
        """List meetings filtered by status."""
        return self.db.query(Meeting).filter(Meeting.status == status).all()

    # ── Agenda CRUD ──────────────────────────────────────────────────────────

    def create_agenda(self, **kwargs) -> Agenda:
        """Create an agenda item. Auto-commits."""
        agenda = Agenda(**kwargs)
        self.db.add(agenda)
        self.db.commit()
        self.db.refresh(agenda)
        return agenda

    def get_agenda_by_id(self, agenda_id: int) -> Agenda | None:
        """Get agenda by primary key."""
        return self.db.get(Agenda, agenda_id)

    def list_agendas_by_meeting(self, meeting_id: int) -> list[Agenda]:
        """List agendas for a meeting, ordered by sort_order."""
        return (
            self.db.query(Agenda)
            .filter(Agenda.meeting_id == meeting_id)
            .order_by(Agenda.sort_order)
            .all()
        )

    def delete_agenda(self, agenda: Agenda) -> None:
        """Delete an agenda item. Commits."""
        self.db.delete(agenda)
        self.db.commit()
