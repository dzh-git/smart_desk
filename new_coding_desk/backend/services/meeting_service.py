"""
MeetingService — meeting lifecycle, agendas, attendees.

Per system_architecture §4.2, EVENT_BUS_SPEC §7:
    - All business rules enforced here.
    - Publishes meeting_started, meeting_ended events.
    - Uses MeetingRepository + AttendeeRepository for data access.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.meeting_events import MeetingStartedEvent, MeetingEndedEvent
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.models.meeting import Meeting
from backend.models.agenda import Agenda
from backend.models.attendee import Attendee
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.base import BaseService


class MeetingService(BaseService):
    """Meeting lifecycle, agenda, and attendee management.

    Business rules:
        - Only one active meeting at a time.
        - Status flow: pending → active → finished (no rollback).
        - start_meeting() publishes meeting_started.
        - end_meeting() publishes meeting_ended.
    """

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.meeting_repo = MeetingRepository(db)
        self.attendee_repo = AttendeeRepository(db)

    # ── Meeting CRUD ─────────────────────────────────────────────────────────

    def create_meeting(self, title: str, description: str | None = None) -> Meeting:
        """Create a new meeting with status='pending'."""
        return self.meeting_repo.create(
            title=title,
            description=description or "",
            status="pending",
        )

    def get_meeting(self, meeting_id: int) -> Meeting:
        """Get meeting by ID. Raises NotFoundError if missing."""
        meeting = self.meeting_repo.get_by_id(meeting_id)
        if not meeting:
            raise NotFoundError(
                f"Meeting {meeting_id} not found",
                "MEETING_NOT_FOUND",
            )
        return meeting

    def list_meetings(self) -> list[Meeting]:
        """List all meetings."""
        return self.meeting_repo.list_all()

    def get_active_meeting(self) -> Meeting | None:
        """Return the currently active meeting, or None."""
        return self.meeting_repo.get_active_meeting()

    # ── Meeting lifecycle ────────────────────────────────────────────────────

    def start_meeting(self, meeting_id: int) -> Meeting:
        """Start a meeting.

        Rules:
            - Meeting must exist and be pending.
            - No other active meeting may exist.
            - Publishes meeting_started event.
        """
        meeting = self.get_meeting(meeting_id)

        if meeting.status == "finished":
            raise ValidationError(
                "Cannot start a finished meeting",
                "MEETING_ALREADY_FINISHED",
            )

        if meeting.status == "active":
            return meeting  # idempotent

        # Check no other active meeting
        active = self.meeting_repo.get_active_meeting()
        if active and active.id != meeting_id:
            raise ConflictError(
                f"Meeting {active.id} is already active",
                "ACTIVE_MEETING_EXISTS",
            )

        meeting.status = "active"
        meeting.started_at = datetime.now(timezone.utc)
        self.meeting_repo.save(meeting)

        self.event_bus.publish(
            MeetingStartedEvent(
                meeting_id=meeting.id,
                payload={"meeting_id": meeting.id},
            )
        )

        return meeting

    def end_meeting(self, meeting_id: int) -> Meeting:
        """End an active meeting.

        Rules:
            - Meeting must be active.
            - finished status is irreversible.
            - Publishes meeting_ended event.
        """
        meeting = self.get_meeting(meeting_id)

        if meeting.status == "finished":
            raise ValidationError(
                "Meeting is already finished",
                "MEETING_ALREADY_FINISHED",
            )

        if meeting.status != "active":
            raise ValidationError(
                "Only an active meeting can be ended",
                "MEETING_NOT_FOUND",
            )

        meeting.status = "finished"
        meeting.ended_at = datetime.now(timezone.utc)
        self.meeting_repo.save(meeting)

        self.event_bus.publish(
            MeetingEndedEvent(
                meeting_id=meeting.id,
                payload={"meeting_id": meeting.id},
            )
        )

        return meeting

    # ── Agenda ───────────────────────────────────────────────────────────────

    def create_agenda(
        self, meeting_id: int, title: str, sort_order: int = 0
    ) -> Agenda:
        """Add an agenda item to a meeting."""
        self.get_meeting(meeting_id)  # ensure meeting exists
        return self.meeting_repo.create_agenda(
            meeting_id=meeting_id,
            title=title,
            sort_order=sort_order,
        )

    def list_agendas(self, meeting_id: int) -> list[Agenda]:
        """List agendas for a meeting, sorted by sort_order."""
        self.get_meeting(meeting_id)  # ensure meeting exists
        return self.meeting_repo.list_agendas_by_meeting(meeting_id)

    def delete_agenda(self, meeting_id: int, agenda_id: int) -> None:
        """Delete an agenda item. Must belong to the given meeting."""
        agenda = self.meeting_repo.get_agenda_by_id(agenda_id)
        if not agenda or agenda.meeting_id != meeting_id:
            raise NotFoundError(
                f"Agenda {agenda_id} not found in meeting {meeting_id}",
                "AGENDA_NOT_FOUND",
            )
        self.meeting_repo.delete_agenda(agenda)

    # ── Attendee ─────────────────────────────────────────────────────────────

    def create_attendee(
        self, meeting_id: int, name: str, title: str = ""
    ) -> Attendee:
        """Add an attendee to a meeting."""
        self.get_meeting(meeting_id)  # ensure meeting exists
        return self.attendee_repo.create(
            meeting_id=meeting_id,
            name=name,
            title=title,
        )

    def list_attendees(self, meeting_id: int) -> list[Attendee]:
        """List all attendees for a meeting."""
        self.get_meeting(meeting_id)  # ensure meeting exists
        return self.attendee_repo.list_by_meeting(meeting_id)

    def delete_attendee(self, meeting_id: int, attendee_id: int) -> None:
        """Remove an attendee. Must belong to the given meeting."""
        attendee = self.attendee_repo.get_by_id(attendee_id)
        if not attendee or attendee.meeting_id != meeting_id:
            raise NotFoundError(
                f"Attendee {attendee_id} not found in meeting {meeting_id}",
                "ATTENDEE_NOT_FOUND",
            )
        self.attendee_repo.delete(attendee)
