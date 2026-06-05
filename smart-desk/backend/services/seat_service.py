from __future__ import annotations
from sqlalchemy.orm import Session
from backend.services.event_bus import EventBus, BaseEvent
from backend.services.background_tasks import get_logger

logger = get_logger()


class SeatService:
    def __init__(self, db: Session, event_bus: EventBus, seat_repo, attendee_repo):
        # db accepted but not stored — all DB operations go through injected repositories
        self.bus = event_bus
        self.seat_repo = seat_repo
        self.attendee_repo = attendee_repo

    def get_all_seats(self):
        return self.seat_repo.get_all_seats()

    def get_seat_state(self, seat_id: int):
        return self.seat_repo.get_seat_state(seat_id)

    def on_seat_occupied(self, meeting_id: int, seat_id: int):
        """Persist TOF detection to DB: vacant -> occupied_unchecked; re-seat auto-binding.

        CR-009: This method only updates DB state. EventBus publishing and
        checkin_prompt timer are handled by DeskCoordinator._on_serial().
        """
        current = self.seat_repo.get_seat_state(seat_id)
        if not current:
            return None
        # Guard: only transition from "vacant" state (CR-009: prevent downgrade)
        if current.status != "vacant":
            return current  # No-op: already occupied or checked in
        # Re-seat: auto-bind previous attendee
        previous_attendee_id = current.attendee_id
        s = self.seat_repo.update_seat(seat_id, "occupied_unchecked",
                                       attendee_id=previous_attendee_id)
        logger.info(f"Seat {seat_id} occupied: attendee_id={previous_attendee_id}")
        return s

    def on_seat_vacant(self, meeting_id: int, seat_id: int):
        """Persist TOF vacancy to DB. Does NOT clear speaker seat. Preserves attendee_id for re-seat auto-binding.

        CR-009: This method only updates DB state. EventBus publishing is
        handled by DeskCoordinator._on_serial().
        """
        current = self.seat_repo.get_seat_state(seat_id)
        if not current:
            return None
        # Guard: no-op if seat is already vacant (CR-009: symmetric to guard in on_seat_occupied)
        if current.status == "vacant":
            return current
        # Reset checked_in flag if seat was in checked_in state (CR-002: enable re-checkin)
        if current.status == "checked_in" and current.attendee_id:
            self.attendee_repo.uncheck(current.attendee_id)
        s = self.seat_repo.update_seat(seat_id, "vacant", attendee_id=current.attendee_id)
        return s

    def checkin(self, meeting_id: int, seat_id: int, attendee_id: int):
        """Check in an attendee at a seat."""
        seat = self.seat_repo.get_seat_state(seat_id)
        if not seat:
            return None
        # Verify attendee exists and is pre-assigned
        att = self.attendee_repo.get_by_id(attendee_id)
        if not att or att.meeting_id != meeting_id:
            return None
        if att.seat_id != seat_id:
            return None
        # Manual/tablet check-in is allowed for pre-assigned attendees even
        # when hardware has not reported TOF occupancy yet.
        if seat.status not in ("vacant", "occupied_unchecked"):
            return None  # INVALID_SEAT_STATE
        if att.checked_in:
            return None  # SEAT_ALREADY_CHECKED_IN
        # Check attendee not already in another seat
        all_seats = self.seat_repo.get_all_seats()
        for s in all_seats:
            if s.attendee_id == attendee_id and s.seat_id != seat_id and s.status == "checked_in":
                return None  # Already checked in elsewhere
        s = self.seat_repo.update_seat(seat_id, "checked_in", attendee_id=attendee_id)
        self.attendee_repo.check_in(attendee_id)
        self.bus.publish(BaseEvent(
            name="check_in",
            payload={"meeting_id": meeting_id, "seat_id": seat_id, "attendee_id": attendee_id},
        ))
        logger.info(f"Seat {seat_id} checkin: attendee_id={attendee_id}")
        return s

    def get_speaker_seat(self):
        return self.seat_repo.get_speaker_seat()

    def set_speaker_seat(self, meeting_id: int, seat_id: int):
        """Set speaker seat. Includes recording_stop signal for previous speaker."""
        current = self.seat_repo.get_speaker_seat()
        previous_seat_id = current.seat_id if current else None

        sp = self.seat_repo.set_speaker_seat(seat_id)

        # Publish recording_stop for previous speaker AFTER successful mutation
        if previous_seat_id and previous_seat_id != seat_id:
            self.bus.publish(BaseEvent(
                name="recording_stop",
                payload={"meeting_id": meeting_id, "seat_id": previous_seat_id, "reason": "speaker_changed"},
            ))

        self.bus.publish(BaseEvent(
            name="speaker_seat_set",
            payload={"meeting_id": meeting_id, "seat_id": seat_id},
        ))
        return sp

    def clear_speaker_seat(self, meeting_id: int):
        current = self.seat_repo.get_speaker_seat()
        previous_seat_id = current.seat_id if current else None

        sp = self.seat_repo.clear_speaker_seat()

        # Publish recording_stop AFTER successful mutation
        if previous_seat_id:
            self.bus.publish(BaseEvent(
                name="recording_stop",
                payload={"meeting_id": meeting_id, "seat_id": previous_seat_id, "reason": "speaker_cleared"},
            ))

        self.bus.publish(BaseEvent(
            name="speaker_seat_clear",
            payload={"meeting_id": meeting_id},
        ))
        return sp
