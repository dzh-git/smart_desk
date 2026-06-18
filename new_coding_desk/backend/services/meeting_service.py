"""
MeetingService — meeting lifecycle, agendas, attendees.

Per system_architecture §4.2, EVENT_BUS_SPEC §7:
    - All business rules enforced here.
    - Publishes meeting_started, meeting_ended events.
    - Uses MeetingRepository + AttendeeRepository for data access.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.meeting_events import MeetingStartedEvent, MeetingEndedEvent
from backend.events.vote_events import VoteClosedEvent
from backend.events.agenda_events import AgendaUpdatedEvent
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.models.meeting import Meeting
from backend.models.agenda import Agenda
from backend.models.attendee import Attendee
from backend.models.seat_state import SeatState
from backend.models.vote import Vote
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.base import BaseService

logger = logging.getLogger(__name__)


class MeetingService(BaseService):
    """Meeting lifecycle, agenda, and attendee management.

    Business rules:
        - Only one active meeting at a time.
        - Status flow: pending → active → finished (no rollback).
        - start_meeting() publishes meeting_started.
        - end_meeting() resets seats, unbinds attendees, closes open vote,
          preserves speaker seat, publishes meeting_ended + vote_closed.
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

        # Task 119: trigger background model preload (non-blocking)
        _trigger_speech_preload()

        return meeting

    def end_meeting(self, meeting_id: int) -> Meeting:
        """End an active meeting.

        Rules:
            - Meeting must be active.
            - All seat_states reset to vacant (attendee_id cleared).
            - All attendees for this meeting have seat_id cleared and
              checked_in set to false.
            - Any open vote is automatically closed (vote_closed event).
            - Speaker seat is preserved (NOT cleared).
            - Historical votes, service calls and translation records
              are preserved.
            - Publishes meeting_ended and (if vote was closed) vote_closed.
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
                "MEETING_NOT_ACTIVE",
            )

        meeting.status = "finished"
        meeting.ended_at = datetime.now(timezone.utc)

        # Reset all seat_states to vacant, clear attendee_id
        seats = self.db.query(SeatState).all()
        for seat in seats:
            seat.status = "vacant"
            seat.attendee_id = None

        # Clear attendee bindings for this meeting
        attendees = self.attendee_repo.list_by_meeting(meeting_id)
        for attendee in attendees:
            attendee.seat_id = None
            attendee.checked_in = False

        # Auto-close open vote (if any)
        open_vote = self.db.query(Vote).filter(Vote.status == "open").first()
        if open_vote is not None:
            open_vote.status = "closed"
            open_vote.closed_at = datetime.now(timezone.utc)
            self.event_bus.publish(
                VoteClosedEvent(
                    meeting_id=meeting_id,
                    payload={"vote_id": open_vote.id},
                )
            )

        # Speaker seat deliberately preserved — NOT cleared.

        self.meeting_repo.save(meeting)

        self.event_bus.publish(
            MeetingEndedEvent(
                meeting_id=meeting.id,
                payload={"meeting_id": meeting.id},
            )
        )

        return meeting

    # ── Agenda CRUD & State Machine ─────────────────────────────────────────

    def create_agenda(
        self, meeting_id: int, title: str, sort_order: int = 0
    ) -> Agenda:
        """Add an agenda item to an active meeting. Status defaults to pending.

        Raises ValidationError if meeting is not active.
        Publishes agenda_updated (action=create).
        """
        self._check_meeting_active(meeting_id)
        agenda = self.meeting_repo.create_agenda(
            meeting_id=meeting_id,
            title=title,
            sort_order=sort_order,
            status="pending",
        )

        current_active = self.meeting_repo.get_active_agenda(meeting_id)
        self.event_bus.publish(
            AgendaUpdatedEvent(
                meeting_id=meeting_id,
                payload={
                    "meeting_id": meeting_id,
                    "agenda_id": agenda.id,
                    "action": "create",
                    "current_agenda_id": current_active.id if current_active else None,
                },
            )
        )
        return agenda

    def list_agendas(self, meeting_id: int) -> list[Agenda]:
        """List agendas for a meeting, sorted by sort_order.

        Available for ended meetings as well (read-only).
        """
        self.get_meeting(meeting_id)  # ensure meeting exists
        return self.meeting_repo.list_agendas_by_meeting(meeting_id)

    def delete_agenda(self, meeting_id: int, agenda_id: int) -> None:
        """Delete a non-active agenda item. Must belong to the given meeting.

        Raises ValidationError if:
            - Meeting is not active.
            - Agenda is currently active.
        Publishes agenda_updated (action=delete).
        """
        agenda = self.meeting_repo.get_agenda_by_id(agenda_id)
        if not agenda or agenda.meeting_id != meeting_id:
            raise NotFoundError(
                f"Agenda {agenda_id} not found in meeting {meeting_id}",
                "AGENDA_NOT_FOUND",
            )

        self._check_meeting_active(meeting_id)

        if agenda.status == "active":
            raise ValidationError(
                "Cannot delete an active agenda",
                "AGENDA_ACTIVE",
            )

        self.meeting_repo.delete_agenda(agenda)

        current_active = self.meeting_repo.get_active_agenda(meeting_id)
        self.event_bus.publish(
            AgendaUpdatedEvent(
                meeting_id=meeting_id,
                payload={
                    "meeting_id": meeting_id,
                    "agenda_id": agenda_id,
                    "action": "delete",
                    "current_agenda_id": current_active.id if current_active else None,
                },
            )
        )

    # ── Agenda state machine (Phase 1) ───────────────────────────────────────

    def _check_meeting_active(self, meeting_id: int) -> Meeting:
        """Check meeting exists and is active. Raises if not."""
        meeting = self.get_meeting(meeting_id)
        if meeting.status != "active":
            raise ValidationError(
                f"Meeting {meeting_id} is not active",
                "MEETING_NOT_ACTIVE",
            )
        return meeting

    def _get_current_active_agenda(self, meeting_id: int) -> Agenda | None:
        """Return the single active agenda for a meeting, or None."""
        return self.meeting_repo.get_active_agenda(meeting_id)

    def set_current_agenda(self, meeting_id: int, agenda_id: int) -> Agenda:
        """Set a pending/skipped agenda as the current active topic.

        Rules per API_SPEC (agenda state machine):
            - Meeting must be active.
            - Accepted source statuses: pending, skipped.
            - Completed → 400.
            - Already-active → idempotent (no started_at update).
            - If another agenda is active: old → completed, new → active.
        Publishes agenda_updated (action=set_current).
        """
        self._check_meeting_active(meeting_id)

        agenda = self.meeting_repo.get_agenda_by_id(agenda_id)
        if not agenda or agenda.meeting_id != meeting_id:
            raise NotFoundError(
                f"Agenda {agenda_id} not found in meeting {meeting_id}",
                "AGENDA_NOT_FOUND",
            )

        # Idempotent: already active
        if agenda.status == "active":
            return agenda

        # Forbidden: completed cannot be set as current
        if agenda.status == "completed":
            raise ValidationError(
                "Cannot set a completed agenda as current",
                "AGENDA_ALREADY_COMPLETED",
            )

        # Only pending or skipped are valid source statuses
        if agenda.status not in ("pending", "skipped"):
            raise ValidationError(
                f"Cannot set agenda with status '{agenda.status}' as current",
                "AGENDA_INVALID_STATUS",
            )

        now = datetime.now(timezone.utc)

        # Complete any currently active agenda
        current_active = self._get_current_active_agenda(meeting_id)
        if current_active:
            current_active.status = "completed"
            current_active.completed_at = now
            current_active.skipped_at = None

        # Activate the target agenda
        agenda.status = "active"
        agenda.started_at = now
        agenda.completed_at = None
        agenda.skipped_at = None

        # Single transaction: both changes committed atomically
        self.db.commit()
        self.db.refresh(agenda)
        if current_active:
            self.db.refresh(current_active)

        self.event_bus.publish(
            AgendaUpdatedEvent(
                meeting_id=meeting_id,
                payload={
                    "meeting_id": meeting_id,
                    "agenda_id": agenda_id,
                    "action": "set_current",
                    "current_agenda_id": agenda_id,
                },
            )
        )

        return agenda

    def advance_agenda(self, meeting_id: int) -> Agenda | None:
        """Complete current active agenda and activate the next pending.

        Rules:
            - Meeting must be active.
            - Must have a current active agenda (otherwise 400).
            - Current active → completed.
            - Next pending (by sort_order) → active.
            - If no next pending: current completed, no current agenda.
        Publishes agenda_updated (action=advance).
        """
        self._check_meeting_active(meeting_id)

        current_active = self._get_current_active_agenda(meeting_id)
        if not current_active:
            raise ValidationError(
                "No active agenda to advance",
                "NO_ACTIVE_AGENDA",
            )

        now = datetime.now(timezone.utc)

        # Complete current
        current_active.status = "completed"
        current_active.completed_at = now
        current_active.skipped_at = None

        # Find and activate next pending
        next_agenda = self.meeting_repo.get_next_pending_agenda(
            meeting_id, after_sort_order=current_active.sort_order,
        )

        if next_agenda:
            next_agenda.status = "active"
            next_agenda.started_at = now
            next_agenda.completed_at = None
            next_agenda.skipped_at = None

        # Single transaction: both changes committed atomically
        self.db.commit()
        self.db.refresh(current_active)
        if next_agenda:
            self.db.refresh(next_agenda)

        self.event_bus.publish(
            AgendaUpdatedEvent(
                meeting_id=meeting_id,
                payload={
                    "meeting_id": meeting_id,
                    "agenda_id": current_active.id,
                    "action": "advance",
                    "current_agenda_id": next_agenda.id if next_agenda else None,
                },
            )
        )

        return next_agenda if next_agenda else current_active

    def complete_agenda(self, meeting_id: int, agenda_id: int) -> Agenda:
        """Complete the current active agenda.

        Rules:
            - Meeting must be active.
            - agenda_id must be the current active agenda (otherwise 400).
        Publishes agenda_updated (action=complete).
        """
        self._check_meeting_active(meeting_id)

        agenda = self.meeting_repo.get_agenda_by_id(agenda_id)
        if not agenda or agenda.meeting_id != meeting_id:
            raise NotFoundError(
                f"Agenda {agenda_id} not found in meeting {meeting_id}",
                "AGENDA_NOT_FOUND",
            )

        if agenda.status != "active":
            raise ValidationError(
                "Only the active agenda can be completed",
                "AGENDA_NOT_ACTIVE",
            )

        now = datetime.now(timezone.utc)
        agenda.status = "completed"
        agenda.completed_at = now
        agenda.skipped_at = None

        self.meeting_repo.save_agenda(agenda)

        self.event_bus.publish(
            AgendaUpdatedEvent(
                meeting_id=meeting_id,
                payload={
                    "meeting_id": meeting_id,
                    "agenda_id": agenda_id,
                    "action": "complete",
                    "current_agenda_id": None,
                },
            )
        )

        return agenda

    def skip_agenda(self, meeting_id: int, agenda_id: int) -> Agenda:
        """Skip the current active agenda.

        Rules:
            - Meeting must be active.
            - agenda_id must be the current active agenda (otherwise 400).
        Publishes agenda_updated (action=skip).
        """
        self._check_meeting_active(meeting_id)

        agenda = self.meeting_repo.get_agenda_by_id(agenda_id)
        if not agenda or agenda.meeting_id != meeting_id:
            raise NotFoundError(
                f"Agenda {agenda_id} not found in meeting {meeting_id}",
                "AGENDA_NOT_FOUND",
            )

        if agenda.status != "active":
            raise ValidationError(
                "Only the active agenda can be skipped",
                "AGENDA_NOT_ACTIVE",
            )

        now = datetime.now(timezone.utc)
        agenda.status = "skipped"
        agenda.skipped_at = now
        agenda.completed_at = None

        self.meeting_repo.save_agenda(agenda)

        self.event_bus.publish(
            AgendaUpdatedEvent(
                meeting_id=meeting_id,
                payload={
                    "meeting_id": meeting_id,
                    "agenda_id": agenda_id,
                    "action": "skip",
                    "current_agenda_id": None,
                },
            )
        )

        return agenda

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


# ── Background speech preload (Task 119) ────────────────────────────────────────


def _trigger_speech_preload() -> None:
    """Trigger SpeechModule preload in background after meeting starts.

    Non-blocking — the meeting start API returns immediately.
    Preload runs in a daemon thread and is idempotent.
    """
    try:
        from backend.services.speech_stream_service import (
            _preload_speech_models_background,
        )
        _preload_speech_models_background()
    except Exception as exc:
        logger.warning("Failed to trigger speech preload: %s", exc)
