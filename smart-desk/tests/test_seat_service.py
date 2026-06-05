# tests/test_seat_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import SeatState, SpeakerSeat, Attendee
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.meeting_repository import MeetingRepository
from backend.services.event_bus import EventBus
from backend.services.seat_service import SeatService


@pytest.fixture
def seat_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    for sid in range(1, 11):
        db.add(SeatState(seat_id=sid, status="vacant"))
    db.add(SpeakerSeat(id=1, seat_id=None))
    mr = MeetingRepository(db)
    meeting = mr.create("Test")
    ar = AttendeeRepository(db)
    att = ar.create(meeting.id, "John", "CEO", seat_id=3)
    db.commit()
    event_bus = EventBus()
    seat_repo = SeatRepository(db)
    svc = SeatService(db, event_bus, seat_repo, ar)
    yield svc, event_bus, meeting.id, att.id
    db.close()


def test_checkin_valid(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    # First mark seat as occupied
    svc.on_seat_occupied(meeting_id, 3)
    events = []
    bus.subscribe("check_in", lambda e: events.append(e))
    result = svc.checkin(meeting_id, 3, attendee_id)
    assert result.status == "checked_in"
    assert len(events) == 1


def test_recheckin_after_reseat(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    # First check in
    svc.on_seat_occupied(meeting_id, 3)
    svc.checkin(meeting_id, 3, attendee_id)
    # Vacate
    svc.on_seat_vacant(meeting_id, 3)
    # Re-occupy
    svc.on_seat_occupied(meeting_id, 3)
    # Re-checkin should succeed (CR-002: checked_in must be reset on vacate)
    events = []
    bus.subscribe("check_in", lambda e: events.append(e))
    result = svc.checkin(meeting_id, 3, attendee_id)
    assert result is not None
    assert result.status == "checked_in"
    assert len(events) == 1


def test_seat_occupied_auto_bind(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    # First check in to bind attendee to seat 3
    svc.on_seat_occupied(meeting_id, 3)
    svc.checkin(meeting_id, 3, attendee_id)
    # Now vacate and re-occupy
    svc.on_seat_vacant(meeting_id, 3)
    svc.on_seat_occupied(meeting_id, 3)
    seat = svc.get_seat_state(3)
    # attendee_id preserved for re-binding
    assert seat.attendee_id == attendee_id


def test_checkin_prompt_via_desk_coordinator(seat_services):
    """CR-009: checkin_prompt is now published by DeskCoordinator, not SeatService."""
    from backend.services.event_bus import event_bus as global_bus, BaseEvent
    events = []
    global_bus.subscribe("checkin_prompt", lambda e: events.append(e))
    global_bus.publish(BaseEvent(name="checkin_prompt",
                                  payload={"meeting_id": 1, "seat_id": 3}))
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == 1
    assert events[0].payload["seat_id"] == 3


def test_checkin_invalid_seat_status(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    # Manual/tablet check-in is allowed before hardware occupancy arrives.
    result = svc.checkin(meeting_id, 3, attendee_id)
    assert result is not None
    assert result.status == "checked_in"

def test_checkin_nonexistent_attendee(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    svc.on_seat_occupied(meeting_id, 3)
    result = svc.checkin(meeting_id, 3, 9999)
    assert result is None


def test_checkin_already_checked_in(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    svc.on_seat_occupied(meeting_id, 3)
    svc.checkin(meeting_id, 3, attendee_id)
    # Second checkin of same attendee should fail
    svc.on_seat_occupied(meeting_id, 4)
    result = svc.checkin(meeting_id, 4, attendee_id)
    assert result is None


def test_checkin_cross_seat_conflict(seat_services):
    svc, bus, meeting_id, attendee_id = seat_services
    # Check in at seat 3
    svc.on_seat_occupied(meeting_id, 3)
    svc.checkin(meeting_id, 3, attendee_id)
    # Try to check in same attendee at seat 4 (should fail)
    svc.on_seat_occupied(meeting_id, 4)
    result = svc.checkin(meeting_id, 4, attendee_id)
    assert result is None


def test_on_seat_occupied_nonexistent_seat(seat_services):
    svc, bus, meeting_id, _ = seat_services
    result = svc.on_seat_occupied(meeting_id, 99)
    assert result is None


def test_on_seat_vacant_nonexistent_seat(seat_services):
    svc, bus, meeting_id, _ = seat_services
    result = svc.on_seat_vacant(meeting_id, 99)
    assert result is None


def test_get_seat_state_nonexistent(seat_services):
    svc, bus, meeting_id, _ = seat_services
    result = svc.get_seat_state(99)
    assert result is None


def test_seat_occupied_no_event_from_service(seat_services):
    """CR-009: SeatService.on_seat_occupied only persists to DB, no EventBus publish."""
    svc, bus, meeting_id, _ = seat_services
    events = []
    bus.subscribe("seat_occupied", lambda e: events.append(e))
    result = svc.on_seat_occupied(meeting_id, 3)
    assert result is not None
    assert result.status == "occupied_unchecked"
    assert len(events) == 0  # CR-009: EventBus publishing moved to DeskCoordinator


def test_seat_vacant_no_event_from_service(seat_services):
    """CR-009: SeatService.on_seat_vacant only persists to DB, no EventBus publish."""
    svc, bus, meeting_id, _ = seat_services
    svc.on_seat_occupied(meeting_id, 5)
    events = []
    bus.subscribe("seat_vacant", lambda e: events.append(e))
    result = svc.on_seat_vacant(meeting_id, 5)
    assert result is not None
    assert result.status == "vacant"
    assert len(events) == 0  # CR-009: EventBus publishing moved to DeskCoordinator


def test_speaker_seat_set_event_has_meeting_id(seat_services):
    svc, bus, meeting_id, _ = seat_services
    events = []
    bus.subscribe("speaker_seat_set", lambda e: events.append(e))
    svc.set_speaker_seat(meeting_id, 5)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == meeting_id
    assert events[0].payload["seat_id"] == 5


def test_speaker_seat_clear_event_has_meeting_id(seat_services):
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)
    events = []
    bus.subscribe("speaker_seat_clear", lambda e: events.append(e))
    svc.clear_speaker_seat(meeting_id)
    assert len(events) == 1
    assert events[0].payload == {"meeting_id": meeting_id}


def test_speaker_seat_persistence(seat_services):
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)
    sp = svc.get_speaker_seat()
    assert sp.seat_id == 5
    svc.clear_speaker_seat(meeting_id)
    sp = svc.get_speaker_seat()
    assert sp.seat_id is None


def test_check_in_event_has_meeting_id(seat_services):
    """CR-007: check_in event payload must include meeting_id for consistency."""
    svc, bus, meeting_id, attendee_id = seat_services
    svc.on_seat_occupied(meeting_id, 3)
    events = []
    bus.subscribe("check_in", lambda e: events.append(e))
    svc.checkin(meeting_id, 3, attendee_id)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == meeting_id
    assert events[0].payload["seat_id"] == 3
    assert events[0].payload["attendee_id"] == attendee_id


def test_on_seat_occupied_on_checked_in_seat_noop(seat_services):
    """CR-009: on_seat_occupied on already checked_in seat should not downgrade status."""
    svc, bus, meeting_id, attendee_id = seat_services
    svc.on_seat_occupied(meeting_id, 3)
    svc.checkin(meeting_id, 3, attendee_id)
    # Seat is now "checked_in" 鈥?calling on_seat_occupied again should be a no-op
    events = []
    bus.subscribe("seat_occupied", lambda e: events.append(e))
    result = svc.on_seat_occupied(meeting_id, 3)
    # Should still succeed (return the seat) but NOT change status
    assert result is not None
    assert result.status == "checked_in"
    assert len(events) == 0  # No duplicate event


def test_on_seat_occupied_on_occupied_unchecked_noop(seat_services):
    """CR-009: on_seat_occupied on already occupied_unchecked seat should be a no-op."""
    svc, bus, meeting_id, _ = seat_services
    svc.on_seat_occupied(meeting_id, 3)
    # Seat is now "occupied_unchecked" 鈥?calling again should be a no-op
    events = []
    bus.subscribe("seat_occupied", lambda e: events.append(e))
    result = svc.on_seat_occupied(meeting_id, 3)
    assert result is not None
    assert result.status == "occupied_unchecked"
    assert len(events) == 0  # No duplicate event


def test_on_seat_vacant_on_already_vacant_noop(seat_services):
    """CR-015: on_seat_vacant on already vacant seat should be a no-op (symmetric to CR-009)."""
    svc, bus, meeting_id, _ = seat_services
    # Seat 3 is already "vacant" 鈥?calling on_seat_vacant should be a no-op
    events = []
    bus.subscribe("seat_vacant", lambda e: events.append(e))
    result = svc.on_seat_vacant(meeting_id, 3)
    assert result is not None
    assert result.status == "vacant"
    assert len(events) == 0  # No spurious event


# 鈹€鈹€ C8: recording_stop on speaker seat switch 鈹€鈹€

def test_set_speaker_seat_publishes_recording_stop_for_previous_speaker(seat_services):
    """C8: When speaker seat switches from A to B, recording_stop fires for A."""
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)
    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    svc.set_speaker_seat(meeting_id, 3)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == meeting_id
    assert events[0].payload["seat_id"] == 5
    assert events[0].payload["reason"] == "speaker_changed"


def test_set_speaker_seat_no_recording_stop_when_no_previous_speaker(seat_services):
    """C8: First set_speaker_seat call (no previous speaker) should NOT fire recording_stop."""
    svc, bus, meeting_id, _ = seat_services
    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    svc.set_speaker_seat(meeting_id, 5)
    assert len(events) == 0


def test_set_speaker_seat_no_recording_stop_for_same_seat(seat_services):
    """C8: Setting the same speaker seat again should NOT fire recording_stop."""
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)
    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    svc.set_speaker_seat(meeting_id, 5)  # same seat
    assert len(events) == 0


def test_clear_speaker_seat_publishes_recording_stop(seat_services):
    """C8: clear_speaker_seat should fire recording_stop for the current speaker."""
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)
    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    svc.clear_speaker_seat(meeting_id)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == meeting_id
    assert events[0].payload["seat_id"] == 5
    assert events[0].payload["reason"] == "speaker_cleared"


def test_clear_speaker_seat_no_recording_stop_when_no_speaker(seat_services):
    """C8: clear_speaker_seat with no current speaker should NOT fire recording_stop."""
    svc, bus, meeting_id, _ = seat_services
    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    svc.clear_speaker_seat(meeting_id)
    assert len(events) == 0


def test_set_speaker_seat_no_recording_stop_on_repo_failure(seat_services):
    """CR-005: recording_stop NOT published when repo mutation raises."""
    from unittest.mock import MagicMock
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)  # set initial speaker

    # Mock repo to raise on next set_speaker_seat
    original = svc.seat_repo.set_speaker_seat
    svc.seat_repo.set_speaker_seat = MagicMock(side_effect=RuntimeError("DB error"))

    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    try:
        svc.set_speaker_seat(meeting_id, 3)
    except RuntimeError:
        pass

    svc.seat_repo.set_speaker_seat = original
    # recording_stop must NOT be published because the mutation failed
    assert len(events) == 0


def test_clear_speaker_seat_no_recording_stop_on_repo_failure(seat_services):
    """CR-005: recording_stop NOT published when clear_speaker_seat repo raises."""
    from unittest.mock import MagicMock
    svc, bus, meeting_id, _ = seat_services
    svc.set_speaker_seat(meeting_id, 5)  # set speaker first

    # Mock repo to raise on clear_speaker_seat
    original = svc.seat_repo.clear_speaker_seat
    svc.seat_repo.clear_speaker_seat = MagicMock(side_effect=RuntimeError("DB error"))

    events = []
    bus.subscribe("recording_stop", lambda e: events.append(e))
    try:
        svc.clear_speaker_seat(meeting_id)
    except RuntimeError:
        pass

    svc.seat_repo.clear_speaker_seat = original
    # recording_stop must NOT be published because the mutation failed
    assert len(events) == 0

