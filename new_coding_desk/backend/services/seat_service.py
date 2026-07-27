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
import os
import time

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
from backend.models.identity_checkin_event import IdentityCheckInEvent
from backend.repositories.seat_repository import SeatRepository, SEAT_COUNT
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.person_repository import PersonRepository
from backend.repositories.identity_checkin_event_repository import (
    IdentityCheckInEventRepository,
)
from backend.services.base import BaseService
from backend.services.tablet_device_service import TabletDeviceService
from backend.services.speech_stream_service import stream_service
from backend.websocket.speech_registry import speech_registry

logger = logging.getLogger(__name__)


def _bounded_identity_time_setting(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


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
        self.person_repo = PersonRepository(db)
        self.identity_event_repo = IdentityCheckInEventRepository(db)
        self.tablet_device_service = TabletDeviceService(db)

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
        self,
        seat_id: int,
        attendee_id: int,
        meeting_id: int | None = None,
        *,
        commit: bool = True,
        publish: bool = True,
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
        self.seat_repo.save_seat(seat, commit=commit)
        self.attendee_repo.save(attendee, commit=commit)

        if publish:
            self._publish_checkin_success(
                seat_id=seat_id,
                attendee_id=attendee_id,
                meeting_id=meeting_id,
            )
        return seat

    def identity_check_in(
        self,
        *,
        seat_id: int,
        device_seat_id: int,
        device_id: str,
        device_token: str | None,
        event_id: str,
        event_timestamp: int,
        person_id: str,
        identity_status: str,
        threshold_status: str,
        verification_level: str,
        similarity: float,
        model_version: str | None,
        allow_prototype: bool = False,
    ) -> SeatState:
        """Resolve a stable person in the active meeting, then reuse check_in.

        The Android result is evidence only. This method enforces the rollout
        gate before mapping Person -> Attendee and delegates the actual seat
        transition to check_in(), so there is still one check-in state machine.
        """
        if device_seat_id != seat_id:
            raise ValidationError(
                (
                    f"Device is bound to seat {device_seat_id}, "
                    f"not requested seat {seat_id}"
                ),
                "DEVICE_SEAT_MISMATCH",
            )
        self.tablet_device_service.authenticate(
            device_id=device_id,
            seat_id=seat_id,
            token=device_token,
        )

        existing_event = self.identity_event_repo.get(event_id)
        if existing_event is not None:
            if (
                existing_event.device_id != device_id
                or existing_event.seat_id != seat_id
                or existing_event.person_id != person_id
            ):
                raise ConflictError(
                    "Identity event_id was already used for different evidence",
                    "IDENTITY_EVENT_CONFLICT",
                )
            seat = self._get_seat(existing_event.seat_id)
            if (
                seat.status != "checked_in"
                or seat.attendee_id != existing_event.attendee_id
            ):
                raise ConflictError(
                    "Identity event exists but its seat state no longer matches",
                    "IDENTITY_EVENT_STATE_CONFLICT",
                )
            return seat

        now_ms = int(time.time() * 1000)
        max_age_ms = (
            _bounded_identity_time_setting(
                "SMARTDESK_IDENTITY_MAX_EVENT_AGE_SECONDS",
                120,
                minimum=10,
                maximum=600,
            )
            * 1000
        )
        future_skew_ms = (
            _bounded_identity_time_setting(
                "SMARTDESK_IDENTITY_MAX_FUTURE_SKEW_SECONDS",
                30,
                minimum=1,
                maximum=120,
            )
            * 1000
        )
        if event_timestamp < now_ms - max_age_ms:
            raise ValidationError(
                "Identity event is too old",
                "IDENTITY_EVENT_STALE",
            )
        if event_timestamp > now_ms + future_skew_ms:
            raise ValidationError(
                "Identity event timestamp is in the future",
                "IDENTITY_EVENT_FUTURE",
            )

        identity_status = identity_status.upper()
        threshold_status = threshold_status.upper()
        verification_level = verification_level.upper()
        if identity_status != "VERIFIED":
            raise ValidationError(
                "Identity result is not VERIFIED",
                "IDENTITY_NOT_VERIFIED",
            )
        if threshold_status == "CALIBRATION_PENDING":
            raise ValidationError(
                "Face verification calibration is still pending",
                "FACE_CALIBRATION_PENDING",
            )
        if verification_level == "PROTOTYPE":
            if threshold_status != "PROVISIONAL":
                raise ValidationError(
                    "Prototype verification requires a PROVISIONAL threshold",
                    "IDENTITY_THRESHOLD_INVALID",
                )
            if not allow_prototype:
                raise ValidationError(
                    "Prototype identity check-in is disabled",
                    "PROTOTYPE_IDENTITY_CHECKIN_DISABLED",
                )
        elif verification_level == "VALIDATED":
            if threshold_status != "VALIDATED":
                raise ValidationError(
                    "Validated verification requires a VALIDATED threshold",
                    "IDENTITY_THRESHOLD_INVALID",
                )
        else:
            raise ValidationError(
                f"Unsupported verification level: {verification_level}",
                "IDENTITY_VERIFICATION_LEVEL_INVALID",
            )

        active = self._active_meeting()
        if active is None:
            raise ValidationError(
                "There is no active meeting",
                "NO_ACTIVE_MEETING",
            )

        person = self.person_repo.get_by_id(person_id)
        if person is None:
            raise ValidationError(
                f"Person {person_id} not found",
                "PERSON_NOT_FOUND",
            )
        if not person.active:
            raise ValidationError(
                f"Person {person_id} is inactive",
                "PERSON_INACTIVE",
            )

        attendee = self.attendee_repo.get_by_person_and_meeting(
            person_id,
            active.id,
        )
        if attendee is None:
            raise ValidationError(
                f"Person {person_id} is not in the active meeting",
                "PERSON_NOT_IN_ACTIVE_MEETING",
            )

        current_seat = self._get_seat(seat_id)
        performed_checkin = not (
            current_seat.status == "checked_in"
            and current_seat.attendee_id == attendee.id
        )
        try:
            if performed_checkin:
                checked_in_seat = self.check_in(
                    seat_id=seat_id,
                    attendee_id=attendee.id,
                    meeting_id=active.id,
                    commit=False,
                    publish=False,
                )
            else:
                checked_in_seat = current_seat

            identity_event = IdentityCheckInEvent(
                event_id=event_id,
                device_id=device_id,
                seat_id=seat_id,
                person_id=person_id,
                attendee_id=attendee.id,
                similarity=similarity,
                verification_level=verification_level,
                model_version=model_version,
            )
            self.identity_event_repo.save(
                identity_event,
                commit=False,
            )
            self.db.commit()
            self.db.refresh(checked_in_seat)
            self.db.refresh(identity_event)
        except Exception:
            self.db.rollback()
            raise

        if performed_checkin:
            self._publish_checkin_success(
                seat_id=seat_id,
                attendee_id=attendee.id,
                meeting_id=active.id,
            )
        return checked_in_seat

    def _publish_checkin_success(
        self,
        *,
        seat_id: int,
        attendee_id: int,
        meeting_id: int | None,
    ) -> None:
        self._publish(
            CheckInEvent(
                payload={"seat_id": seat_id, "attendee_id": attendee_id},
            ),
            meeting_id=meeting_id,
        )
        logger.info(
            "Seat %d: checked_in by attendee %d",
            seat_id,
            attendee_id,
        )

    # ── Speaker Seat ─────────────────────────────────────────────────────────

    def get_speaker_seat(self) -> SpeakerSeat:
        """Return the singleton speaker_seat row (id=1)."""
        return self.seat_repo.get_speaker_seat()

    def set_speaker_seat(
        self, seat_id: int, meeting_id: int | None = None
    ) -> SpeakerSeat:
        """Set the speaker seat. Overwrites any previous speaker.

        Rules:
            - seat_id must reference a valid seat (1..9).
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
