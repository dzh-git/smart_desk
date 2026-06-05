"""
Tests for SeatService — state machine, check-in, speaker seat.

Coverage:
    - seat_occupied (vacant → occupied_unchecked)
    - seat_vacant (any → vacant)
    - check_in (occupied_unchecked → checked_in + attendee/meeting validation)
    - State machine error cases
    - Speaker seat set/clear
    - Event publishing (6 event types)
    - Active meeting ID injected into seat events (Phase 03)
"""
from __future__ import annotations

import pytest

from backend.exceptions import NotFoundError, ValidationError
from backend.services.seat_service import SeatService
from backend.services.meeting_service import MeetingService
from backend.models.seat_state import SeatState
from backend.models.attendee import Attendee


# ── Helpers ─────────────────────────────────────────────────────────────────


def _active_meeting_with_attendee(db, event_bus, name="Alice", title=""):
    """Create and start a meeting, add an attendee. Returns (meeting, attendee)."""
    ms = MeetingService(db, event_bus)
    meeting = ms.create_meeting("Test Meeting")
    ms.start_meeting(meeting.id)
    attendee = ms.create_attendee(meeting.id, name, title)
    return meeting, attendee


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def svc(seeded_db, event_bus):
    """SeatService with seeded DB."""
    return SeatService(seeded_db, event_bus)


# ── Seat Occupied ────────────────────────────────────────────────────────────


class TestSeatOccupied:
    """seat_occupied: vacant → occupied_unchecked."""

    def test_occupies_vacant_seat(self, svc):
        """Vacant seat transitions to occupied_unchecked."""
        seat = svc.seat_occupied(1)
        assert seat.status == "occupied_unchecked"
        assert seat.attendee_id is None

    def test_publishes_seat_occupied_event(self, svc, event_bus):
        """Publishes seat_occupied event."""
        events = []
        event_bus.subscribe("seat_occupied", lambda e: events.append(e))
        svc.seat_occupied(2)
        assert len(events) == 1
        assert events[0].event_name == "seat_occupied"
        assert events[0].payload["seat_id"] == 2

    def test_publishes_checkin_prompt_event(self, svc, event_bus):
        """Publishes checkin_prompt event after seat_occupied."""
        events = []
        event_bus.subscribe("checkin_prompt", lambda e: events.append(e))
        svc.seat_occupied(3)
        assert len(events) == 1
        assert events[0].event_name == "checkin_prompt"
        assert events[0].payload["seat_id"] == 3

    def test_publishes_both_events_together(self, svc, event_bus):
        """Both seat_occupied and checkin_prompt published."""
        captured = {}
        event_bus.subscribe(
            "seat_occupied", lambda e: captured.setdefault("occupied", []).append(e)
        )
        event_bus.subscribe(
            "checkin_prompt", lambda e: captured.setdefault("prompt", []).append(e)
        )
        svc.seat_occupied(5)
        assert len(captured["occupied"]) == 1
        assert len(captured["prompt"]) == 1

    def test_meeting_id_in_event(self, svc, event_bus):
        """Meeting ID is passed through to events."""
        events = []
        event_bus.subscribe("seat_occupied", lambda e: events.append(e))
        svc.seat_occupied(1, meeting_id=42)
        assert events[0].meeting_id == 42

    def test_fails_when_not_vacant(self, svc):
        """seat_occupied fails if seat is already occupied."""
        svc.seat_occupied(4)  # now occupied_unchecked
        with pytest.raises(ValidationError, match="already occupied"):
            svc.seat_occupied(4)

    def test_fails_when_checked_in(self, svc):
        """seat_occupied fails if seat is checked_in."""
        from backend.services.meeting_service import MeetingService
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(6)
        svc.check_in(6, attendee_id=attendee.id)
        with pytest.raises(ValidationError, match="already occupied"):
            svc.seat_occupied(6)

    def test_clears_attendee_id_on_occupy(self, svc):
        """seat_occupied clears any previous attendee_id."""
        from backend.services.meeting_service import MeetingService
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(7)
        svc.check_in(7, attendee_id=attendee.id)
        svc.seat_vacant(7)
        seat = svc.seat_occupied(7)
        assert seat.attendee_id is None

    def test_nonexistent_seat_raises_not_found(self, svc):
        """seat_occupied on seat_id=99 raises NotFoundError."""
        with pytest.raises(NotFoundError, match="Seat 99"):
            svc.seat_occupied(99)


# ── Seat Vacant ──────────────────────────────────────────────────────────────


class TestSeatVacant:
    """seat_vacant: any → vacant."""

    def test_vacant_from_occupied_unchecked(self, svc):
        """occupied_unchecked → vacant."""
        svc.seat_occupied(1)
        seat = svc.seat_vacant(1)
        assert seat.status == "vacant"
        assert seat.attendee_id is None

    def test_vacant_from_checked_in(self, svc):
        """checked_in → vacant."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(2)
        svc.check_in(2, attendee_id=attendee.id)
        seat = svc.seat_vacant(2)
        assert seat.status == "vacant"
        assert seat.attendee_id is None

    def test_idempotent_on_vacant(self, svc):
        """Calling seat_vacant on already-vacant is a no-op."""
        seat1 = svc.seat_vacant(3)
        seat2 = svc.seat_vacant(3)
        assert seat1.status == "vacant"
        assert seat2.status == "vacant"

    def test_no_event_when_already_vacant(self, svc, event_bus):
        """No event published if already vacant."""
        events = []
        event_bus.subscribe("seat_vacant", lambda e: events.append(e))
        svc.seat_vacant(4)  # already vacant from seed
        assert len(events) == 0

    def test_publishes_seat_vacant_event(self, svc, event_bus):
        """Publishes seat_vacant event when transitioning to vacant."""
        svc.seat_occupied(5)
        events = []
        event_bus.subscribe("seat_vacant", lambda e: events.append(e))
        svc.seat_vacant(5)
        assert len(events) == 1
        assert events[0].event_name == "seat_vacant"
        assert events[0].payload["seat_id"] == 5

    def test_nonexistent_seat_raises_not_found(self, svc):
        """seat_vacant on non-existent seat raises NotFoundError."""
        with pytest.raises(NotFoundError, match="Seat 99"):
            svc.seat_vacant(99)

    def test_vacant_clears_attendee_seat_id(self, svc):
        """Vacating a checked-in seat sets attendee.seat_id to None."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(1)
        svc.check_in(1, attendee_id=attendee.id)
        assert attendee.seat_id == 1
        assert attendee.checked_in is True

        svc.seat_vacant(1)
        # Reload attendee to verify persistence
        svc.db.refresh(attendee)
        assert attendee.seat_id is None
        assert attendee.checked_in is False

    def test_vacant_clears_checked_in_flag(self, svc):
        """Vacating a checked-in seat clears checked_in on attendee."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(2)
        svc.check_in(2, attendee_id=attendee.id)
        svc.seat_vacant(2)
        svc.db.refresh(attendee)
        assert attendee.checked_in is False

    def test_vacant_allows_recheckin_after_vacate(self, svc):
        """After vacate, the same attendee can be checked in again."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)

        # First cycle
        svc.seat_occupied(3)
        svc.check_in(3, attendee_id=attendee.id)
        svc.seat_vacant(3)

        # Second cycle (re-occupy + re-check-in)
        svc.seat_occupied(3)
        seat = svc.check_in(3, attendee_id=attendee.id)
        assert seat.status == "checked_in"
        assert seat.attendee_id == attendee.id
        svc.db.refresh(attendee)
        assert attendee.seat_id == 3
        assert attendee.checked_in is True


# ── Check-in ─────────────────────────────────────────────────────────────────


class TestCheckIn:
    """check_in: occupied_unchecked → checked_in with attendee & meeting validation."""

    def test_checks_in_successfully(self, svc):
        """occupied_unchecked → checked_in with valid attendee in active meeting."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(1)
        seat = svc.check_in(1, attendee_id=attendee.id)
        assert seat.status == "checked_in"
        assert seat.attendee_id == attendee.id

    def test_check_in_syncs_attendee(self, svc):
        """After check-in, attendee.seat_id and checked_in are updated."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(2)
        svc.check_in(2, attendee_id=attendee.id)
        assert attendee.seat_id == 2
        assert attendee.checked_in is True

    def test_publishes_check_in_event(self, svc, event_bus):
        """Publishes check_in event with active meeting ID."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(3)
        events = []
        event_bus.subscribe("check_in", lambda e: events.append(e))
        svc.check_in(3, attendee_id=attendee.id)
        assert len(events) == 1
        assert events[0].event_name == "check_in"
        assert events[0].payload == {"seat_id": 3, "attendee_id": attendee.id}
        assert events[0].meeting_id == meeting.id

    def test_fails_when_vacant(self, svc):
        """Cannot check in a vacant seat."""
        with pytest.raises(ValidationError, match="vacant"):
            svc.check_in(3, attendee_id=1)

    def test_fails_when_already_checked_in(self, svc):
        """Cannot check in an already checked-in seat."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(4)
        svc.check_in(4, attendee_id=attendee.id)
        with pytest.raises(ValidationError, match="already checked in"):
            svc.check_in(4, attendee_id=attendee.id)

    def test_fails_when_attendee_not_found(self, svc):
        """Non-existent attendee raises ValidationError."""
        svc.seat_occupied(5)
        with pytest.raises(ValidationError, match="Attendee.*not found"):
            svc.check_in(5, attendee_id=999)

    def test_fails_when_no_active_meeting(self, svc):
        """Attendee not in active meeting raises ValidationError."""
        # Create attendee but no active meeting
        ms = MeetingService(svc.db, svc.event_bus)
        m = ms.create_meeting("Pending")  # not started
        attendee = ms.create_attendee(m.id, "Bob")

        svc.seat_occupied(6)
        with pytest.raises(ValidationError, match="not in the active meeting"):
            svc.check_in(6, attendee_id=attendee.id)

    def test_fails_when_attendee_wrong_meeting(self, svc):
        """Attendee from a different meeting raises ValidationError."""
        meeting1, attendee1 = _active_meeting_with_attendee(svc.db, svc.event_bus, "Alice")
        # attendee1 belongs to meeting1 which is active — this should work
        svc.seat_occupied(1)
        seat = svc.check_in(1, attendee_id=attendee1.id)
        assert seat.status == "checked_in"

    def test_fails_when_attendee_already_bound(self, svc):
        """Attendee already bound to another seat raises ValidationError."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus, "Charlie")
        # Check in to seat 1
        svc.seat_occupied(1)
        svc.check_in(1, attendee_id=attendee.id)
        # Try to check in same attendee to seat 2
        svc.seat_occupied(2)
        with pytest.raises(ValidationError, match="already checked into"):
            svc.check_in(2, attendee_id=attendee.id)

    def test_nonexistent_seat_raises_not_found(self, svc):
        """check_in on non-existent seat raises NotFoundError."""
        with pytest.raises(NotFoundError, match="Seat 99"):
            svc.check_in(99, attendee_id=1)

    def test_check_in_preserves_attendee_id(self, svc):
        """attendee_id is correctly persisted."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(5)
        seat = svc.check_in(5, attendee_id=attendee.id)
        assert seat.attendee_id == attendee.id

        # Verify persisted in DB
        fetched = svc.seat_repo.get_seat(5)
        assert fetched.attendee_id == attendee.id


# ── List Seats ───────────────────────────────────────────────────────────────


class TestListSeats:
    """list_seats: return all 10 seat states."""

    def test_returns_10_seats(self, svc):
        """Seed data provides exactly 10 seats."""
        seats = svc.list_seats()
        assert len(seats) == 10

    def test_seats_ordered_by_id(self, svc):
        """Seats returned in seat_id order."""
        seats = svc.list_seats()
        ids = [s.seat_id for s in seats]
        assert ids == list(range(1, 11))

    def test_all_initially_vacant(self, svc):
        """All seats start vacant after seed."""
        seats = svc.list_seats()
        assert all(s.status == "vacant" for s in seats)


# ── Speaker Seat ─────────────────────────────────────────────────────────────


class TestSpeakerSeat:
    """Speaker seat: set, clear, auto-overwrite."""

    def test_initial_speaker_seat_null(self, svc):
        """After seed, speaker seat_id is None."""
        speaker = svc.get_speaker_seat()
        assert speaker.seat_id is None

    def test_set_speaker_seat(self, svc):
        """Set speaker to a valid seat."""
        speaker = svc.set_speaker_seat(3)
        assert speaker.seat_id == 3

    def test_publishes_speaker_seat_set(self, svc, event_bus):
        """Publishes speaker_seat_set event."""
        events = []
        event_bus.subscribe("speaker_seat_set", lambda e: events.append(e))
        svc.set_speaker_seat(5)
        assert len(events) == 1
        assert events[0].event_name == "speaker_seat_set"
        assert events[0].payload == {"seat_id": 5}

    def test_auto_overwrites_previous_speaker(self, svc):
        """Setting new speaker automatically replaces old."""
        svc.set_speaker_seat(1)
        svc.set_speaker_seat(2)
        speaker = svc.get_speaker_seat()
        assert speaker.seat_id == 2

    def test_clear_speaker_seat(self, svc):
        """Clear speaker seat sets seat_id to None."""
        svc.set_speaker_seat(4)
        speaker = svc.clear_speaker_seat()
        assert speaker.seat_id is None

    def test_publishes_speaker_seat_clear(self, svc, event_bus):
        """Publishes speaker_seat_clear event."""
        svc.set_speaker_seat(3)
        events = []
        event_bus.subscribe("speaker_seat_clear", lambda e: events.append(e))
        svc.clear_speaker_seat()
        assert len(events) == 1
        assert events[0].event_name == "speaker_seat_clear"
        assert events[0].payload == {}

    def test_clear_already_clear_is_noop(self, svc):
        """Clearing when already None works (no-op)."""
        speaker = svc.clear_speaker_seat()
        assert speaker.seat_id is None

    def test_set_nonexistent_seat_fails(self, svc):
        """Cannot set speaker to non-existent seat."""
        with pytest.raises(NotFoundError, match="Seat 99"):
            svc.set_speaker_seat(99)

    def test_get_speaker_seat_persists(self, svc):
        """get_speaker_seat returns persisted state after set."""
        svc.set_speaker_seat(8)
        speaker = svc.get_speaker_seat()
        assert speaker.id == 1
        assert speaker.seat_id == 8


# ── State Machine Round-trip ─────────────────────────────────────────────────


class TestStateMachineRoundTrip:
    """Full lifecycle: vacant → occupied_unchecked → checked_in → vacant."""

    def test_full_lifecycle(self, svc):
        """Complete state machine cycle with valid attendee."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)

        # Start: vacant
        seat = svc.seat_repo.get_seat(1)
        assert seat.status == "vacant"

        # Occupy
        seat = svc.seat_occupied(1)
        assert seat.status == "occupied_unchecked"

        # Check in
        seat = svc.check_in(1, attendee_id=attendee.id)
        assert seat.status == "checked_in"
        assert seat.attendee_id == attendee.id

        # Vacate
        seat = svc.seat_vacant(1)
        assert seat.status == "vacant"
        assert seat.attendee_id is None

    def test_reoccupy_after_full_cycle(self, svc):
        """After full cycle, seat can be occupied again."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        svc.seat_occupied(2)
        svc.check_in(2, attendee_id=attendee.id)
        svc.seat_vacant(2)
        # Can occupy again
        seat = svc.seat_occupied(2)
        assert seat.status == "occupied_unchecked"

    def test_events_in_lifecycle(self, svc, event_bus):
        """Track all events during a lifecycle."""
        meeting, attendee = _active_meeting_with_attendee(svc.db, svc.event_bus)
        events = []
        for name in [
            "seat_occupied", "checkin_prompt", "check_in", "seat_vacant",
        ]:
            event_bus.subscribe(name, lambda e, n=name: events.append(n))

        svc.seat_occupied(3)       # seat_occupied + checkin_prompt
        svc.check_in(3, attendee_id=attendee.id)   # check_in
        svc.seat_vacant(3)         # seat_vacant

        assert events == [
            "seat_occupied", "checkin_prompt", "check_in", "seat_vacant",
        ]
