"""
SeatService — seat state machine, check-in, speaker seat management.

Per system_architecture §4.2, EVENT_BUS_SPEC §6:
    - seat_occupied:  vacant → occupied_unchecked  + seat_occupied + checkin_prompt
    - seat_vacant:    any   → vacant               + seat_vacant
    - check_in:       occupied_unchecked → checked_in  + check_in
    - set_speaker:    overwrite old speaker        + speaker_seat_set
    - clear_speaker:  NULL speaker                 + speaker_seat_clear
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.events.event_bus import EventBus
from backend.events.seat_events import (
    SeatOccupiedEvent,
    SeatVacantEvent,
    CheckinPromptEvent,
    CheckInEvent,
    SpeakerSeatSetEvent,
    SpeakerSeatClearEvent,
)
from backend.events.translation_events import TranslationInterimCancelledEvent
from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.models.seat_state import SeatState
from backend.models.speaker_seat import SpeakerSeat
from backend.models.attendee import Attendee
from backend.models.meeting import Meeting
from backend.repositories.seat_repository import SeatRepository, SEAT_COUNT
from backend.repositories.attendee_repository import AttendeeRepository
from backend.services.base import BaseService
from backend.services.speech_stream_service import stream_service
from backend.websocket.speech_registry import speech_registry

logger = logging.getLogger(__name__)


class SeatService(BaseService):
    """Seat state machine and speaker seat management.

    Business rules:
        - seat_occupied: only from vacant state.
        - check_in: only from occupied_unchecked state; attendee must exist
          and belong to the active meeting; no duplicate seat/attendee bindings.
        - seat_vacant: any state → vacant.
        - One speaker seat at a time; setting new overwrites old.
        - Publishes 6 event types.
    """

    def __init__(self, db: Session, event_bus: EventBus) -> None:
        super().__init__(db, event_bus)
        self.seat_repo = SeatRepository(db)
        self.attendee_repo = AttendeeRepository(db)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _get_seat(self, seat_id: int) -> SeatState:
        """Get a seat by ID. Raises NotFoundError if missing."""
        seat = self.seat_repo.get_seat(seat_id)
        if seat is None:
            raise NotFoundError(
                f"Seat {seat_id} not found",
                "SEAT_NOT_FOUND",
            )
        return seat

    def _publish(self, event, meeting_id: int | None = None) -> None:
        """Publish an event, optionally setting meeting_id."""
        if meeting_id is not None:
            event.meeting_id = meeting_id
        self.event_bus.publish(event)

    def _active_meeting(self) -> Meeting | None:
        """Return the currently active meeting, or None."""
        return self.db.query(Meeting).filter(Meeting.status == "active").first()

    # ── Speaker Seat Switch (Phase 5) ─────────────────────────────────────────

    def _handle_speaker_seat_switch(
        self, meeting_id: int, old_seat_id: int,
    ) -> None:
        """Clean up when an old speaker seat is replaced.

        Per WEBSOCKET_PROTOCOL §7 (Speaker Seat Switch):
            1. Cancel any pending utterance (clear buffer, reset state).
            2. Publish TranslationInterimCancelledEvent.
            3. Close the old speech WS connection (triggers handler cleanup).

        The old WS handler's finally block handles stream_service session
        removal and speech_registry unregister.
        """
        old_key = f"speech_{meeting_id}_{old_seat_id}"

        # 1. Cancel pending utterance (clears buffer, resets revision)
        cancelled_uid = stream_service.cancel_utterance(old_key)

        # 2. Publish TranslationInterimCancelledEvent
        cancelled_uid_str = cancelled_uid if cancelled_uid else ""
        self._publish(
            TranslationInterimCancelledEvent(
                payload={
                    "utterance_id": cancelled_uid_str,
                    "seat_id": old_seat_id,
                    "reason": "speaker_seat_changed",
                },
            ),
            meeting_id=meeting_id,
        )

        # 3. Mark old WS as invalidated so no further messages are processed
        old_ws = speech_registry.get(meeting_id, old_seat_id)
        if old_ws is not None:
            speech_registry.mark_invalidated(old_ws)

        # 4. Close old speech WS (async via call_soon_threadsafe)
        speech_registry.close_seat(meeting_id, old_seat_id)

        logger.info(
            "Speaker seat switch: cleaned up seat %d (utterance=%s)",
            old_seat_id, cancelled_uid_str or "(none)",
        )

    # ── Seat State ───────────────────────────────────────────────────────────

    def list_seats(self) -> list[SeatState]:
        """Return all seat states, ordered by seat_id."""
        return self.seat_repo.list_seats()

    # ── seat_occupied ────────────────────────────────────────────────────────

    def seat_occupied(self, seat_id: int, meeting_id: int | None = None) -> SeatState:
        """Transition: vacant → occupied_unchecked.

        Rules:
            - Seat must be in vacant state.
            - Clears attendee_id.
            - Publishes seat_occupied + checkin_prompt.

        Called by HardwareService when TOF sensor detects occupancy.
        """
        seat = self._get_seat(seat_id)

        if seat.status != "vacant":
            raise ValidationError(
                f"Seat {seat_id} is already occupied (status={seat.status})",
                "SEAT_OCCUPIED",
            )

        seat.status = "occupied_unchecked"
        seat.attendee_id = None
        self.seat_repo.save_seat(seat)

        self._publish(
            SeatOccupiedEvent(payload={"seat_id": seat_id}),
            meeting_id=meeting_id,
        )
        self._publish(
            CheckinPromptEvent(payload={"seat_id": seat_id}),
            meeting_id=meeting_id,
        )

        logger.info("Seat %d: occupied_unchecked", seat_id)
        return seat

    # ── seat_vacant ──────────────────────────────────────────────────────────

    def seat_vacant(self, seat_id: int, meeting_id: int | None = None) -> SeatState:
        """Transition: any state → vacant.

        Rules:
            - Idempotent (calling on already-vacant seat is a no-op).
            - If a checked-in attendee is bound to this seat, unbind them:
              attendee.seat_id = None, attendee.checked_in = False.
            - Clears seat.attendee_id.
            - Publishes seat_vacant.
        """
        seat = self._get_seat(seat_id)

        if seat.status == "vacant":
            return seat  # already vacant, no event

        # Unbind any attendee that was checked into this seat
        if seat.attendee_id is not None:
            attendee = self.attendee_repo.get_by_id(seat.attendee_id)
            if attendee is not None:
                attendee.seat_id = None
                attendee.checked_in = False
                self.attendee_repo.save(attendee)
                logger.info(
                    "Seat %d: unbound attendee %d (seat_id=None, checked_in=False)",
                    seat_id, seat.attendee_id,
                )

        seat.status = "vacant"
        seat.attendee_id = None
        self.seat_repo.save_seat(seat)

        self._publish(
            SeatVacantEvent(payload={"seat_id": seat_id}),
            meeting_id=meeting_id,
        )

        logger.info("Seat %d: vacant", seat_id)
        return seat

    # ── check_in ─────────────────────────────────────────────────────────────

    def check_in(
        self, seat_id: int, attendee_id: int, meeting_id: int | None = None
    ) -> SeatState:
        """Transition: occupied_unchecked → checked_in.

        Rules:
            - Seat must be in occupied_unchecked state.
            - attendee must exist and belong to the active meeting.
            - attendee must not already be bound to another seat.
            - seat must not be bound to another attendee.
            - On success: seat.status=checked_in, seat.attendee_id set,
              attendee.seat_id set, attendee.checked_in=true.
            - Publishes check_in.
        """
        seat = self._get_seat(seat_id)

        if seat.status == "vacant":
            raise ValidationError(
                f"Seat {seat_id} is vacant — cannot check in",
                "SEAT_NOT_OCCUPIED",
            )
        if seat.status == "checked_in":
            raise ValidationError(
                f"Seat {seat_id} is already checked in",
                "SEAT_ALREADY_CHECKED_IN",
            )

        # Validate attendee exists
        attendee = self.attendee_repo.get_by_id(attendee_id)
        if attendee is None:
            raise ValidationError(
                f"Attendee {attendee_id} not found",
                "ATTENDEE_NOT_FOUND",
            )

        # Validate attendee belongs to active meeting
        active = self._active_meeting()
        if active is None or attendee.meeting_id != active.id:
            raise ValidationError(
                f"Attendee {attendee_id} is not in the active meeting",
                "ATTENDEE_NOT_IN_ACTIVE_MEETING",
            )

        # Validate attendee not already bound to another seat
        if attendee.seat_id is not None and attendee.seat_id != seat_id:
            raise ValidationError(
                f"Attendee {attendee_id} is already checked into seat {attendee.seat_id}",
                "ATTENDEE_ALREADY_CHECKED_IN",
            )

        # Validate seat not bound to a different attendee
        if seat.attendee_id is not None and seat.attendee_id != attendee_id:
            raise ValidationError(
                f"Seat {seat_id} is already bound to attendee {seat.attendee_id}",
                "SEAT_ALREADY_BOUND",
            )

        # Use active meeting ID if not explicitly provided
        if meeting_id is None and active is not None:
            meeting_id = active.id

        # Update both seat and attendee
        seat.status = "checked_in"
        seat.attendee_id = attendee_id
        attendee.seat_id = seat_id
        attendee.checked_in = True
        self.seat_repo.save_seat(seat)
        self.attendee_repo.save(attendee)

        self._publish(
            CheckInEvent(
                payload={"seat_id": seat_id, "attendee_id": attendee_id},
            ),
            meeting_id=meeting_id,
        )

        logger.info(
            "Seat %d: checked_in by attendee %d", seat_id, attendee_id
        )
        return seat

    # ── Speaker Seat ─────────────────────────────────────────────────────────

    def get_speaker_seat(self) -> SpeakerSeat:
        """Return the singleton speaker_seat row (id=1)."""
        return self.seat_repo.get_speaker_seat()

    def set_speaker_seat(
        self, seat_id: int, meeting_id: int | None = None
    ) -> SpeakerSeat:
        """Set the speaker seat. Overwrites any previous speaker.

        Rules:
            - seat_id must reference a valid seat (1..10).
            - If the old and new seat differ, performs a hard switch:
              old speech WS closed, pending interim cancelled, buffer cleared.
            - Publishes speaker_seat_set.
        """
        self._get_seat(seat_id)  # validate seat exists

        speaker = self.seat_repo.get_speaker_seat()
        old_seat_id = speaker.seat_id

        # Hard switch: clean up old speaker seat if it changed
        if old_seat_id is not None and old_seat_id != seat_id and meeting_id is not None:
            self._handle_speaker_seat_switch(meeting_id, old_seat_id)

        speaker.seat_id = seat_id
        self.seat_repo.save_speaker_seat(speaker)

        self._publish(
            SpeakerSeatSetEvent(payload={"seat_id": seat_id}),
            meeting_id=meeting_id,
        )

        logger.info(
            "Speaker seat set to %d (was %s)", seat_id, old_seat_id,
        )
        return speaker

    def clear_speaker_seat(
        self, meeting_id: int | None = None
    ) -> SpeakerSeat:
        """Clear the speaker seat (set to NULL).

        Rules:
            - If there was an active speaker, performs hard switch cleanup:
              old speech WS closed, pending interim cancelled, buffer cleared.
            - Publishes speaker_seat_clear.
        """
        speaker = self.seat_repo.get_speaker_seat()
        old_seat_id = speaker.seat_id

        # Hard switch: clean up old speaker seat if one was set
        if old_seat_id is not None and meeting_id is not None:
            self._handle_speaker_seat_switch(meeting_id, old_seat_id)

        speaker.seat_id = None
        self.seat_repo.save_speaker_seat(speaker)

        self._publish(
            SpeakerSeatClearEvent(payload={}),
            meeting_id=meeting_id,
        )

        logger.info(
            "Speaker seat cleared (was %s)", old_seat_id,
        )
        return speaker
