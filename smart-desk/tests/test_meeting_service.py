# tests/test_meeting_service.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import EventBus
from backend.services.meeting_service import MeetingService
from backend.models import SeatState, SpeakerSeat


@pytest.fixture
def services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    for sid in range(1, 11):
        db.add(SeatState(seat_id=sid, status="vacant"))
    db.add(SpeakerSeat(id=1, seat_id=None))
    db.commit()

    event_bus = EventBus()
    meeting_repo = MeetingRepository(db)
    attendee_repo = AttendeeRepository(db)
    seat_repo = SeatRepository(db)
    vote_repo = VoteRepository(db)
    svc = MeetingService(db, event_bus, meeting_repo, attendee_repo, seat_repo, vote_repo)
    yield svc, event_bus
    db.close()


def test_create_meeting(services):
    svc, bus = services
    events = []
    bus.subscribe("meeting_started", lambda e: events.append(e))
    m = svc.create("Board Meeting", "Quarterly Review")
    assert m.title == "Board Meeting"
    assert m.status == "pending"
    assert len(events) == 0  # Creating doesn't start


def test_start_meeting_fires_event(services):
    svc, bus = services
    events = []
    bus.subscribe("meeting_started", lambda e: events.append(e))
    m = svc.create("Test")
    svc.start(m.id)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == m.id


def test_end_meeting_fires_event(services):
    svc, bus = services
    events = []
    bus.subscribe("meeting_ended", lambda e: events.append(e))
    m = svc.create("Test")
    svc.start(m.id)
    svc.end(m.id)
    assert len(events) == 1
    assert events[0].payload["meeting_id"] == m.id


def test_end_pending_meeting_fails(services):
    svc, bus = services
    m = svc.create("Test")
    # Meeting is "pending", not "active" — ending should fail
    assert m.status == "pending"
    events = []
    bus.subscribe("meeting_ended", lambda e: events.append(e))
    result = svc.end(m.id)
    assert result is None
    assert len(events) == 0  # No event should fire
    # Verify meeting status should NOT have changed
    meeting = svc.get_by_id(m.id)
    assert meeting.status == "pending"


def test_end_nonexistent_meeting_fails(services):
    svc, bus = services
    result = svc.end(9999)
    assert result is None


def test_remove_attendee_with_history_fails(services):
    svc, bus = services
    m = svc.create("Test")
    a = svc.add_attendee(m.id, "John", seat_id=1)
    # Check in to establish history
    svc.attendee_repo.check_in(a.id)
    assert svc.remove_attendee(m.id, a.id) is False  # ATTENDEE_HAS_HISTORY

def test_remove_attendee_no_history_succeeds(services):
    svc, bus = services
    m = svc.create("Test")
    a = svc.add_attendee(m.id, "Jane", seat_id=2)
    # No history — removal should succeed
    assert svc.remove_attendee(m.id, a.id) is True


def test_start_with_active_meeting_fails(services):
    svc, bus = services
    m1 = svc.create("Meeting 1")
    m2 = svc.create("Meeting 2")  # Create both before starting
    svc.start(m1.id)
    # Now m1 is active — starting m2 should fail
    result = svc.start(m2.id)
    assert result is None


def test_start_nonexistent_meeting_fails(services):
    svc, bus = services
    result = svc.start(9999)
    assert result is None


def test_end_resets_seats(services):
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    # Occupy a seat
    svc.seat_repo.update_seat(1, "checked_in", attendee_id=1)
    svc.end(m.id)
    seat = svc.seat_repo.get_seat_state(1)
    assert seat.status == "vacant"
    assert seat.attendee_id is None


def test_end_clears_speaker_seat(services):
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    svc.seat_repo.set_speaker_seat(5)
    svc.end(m.id)
    sp = svc.seat_repo.get_speaker_seat()
    assert sp.seat_id is None


def test_end_closes_open_votes(services):
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    v = svc.vote_repo.create(m.id, "Vote 1", ["Yes", "No"])
    assert v.status == "open"
    vote_events = []
    bus.subscribe("vote_closed", lambda e: vote_events.append(e))
    svc.end(m.id)
    # Vote should be closed
    v2 = svc.vote_repo.get_by_id(v.id)
    assert v2.status == "closed"
    assert len(vote_events) == 1
    assert vote_events[0].payload["vote_id"] == v.id


def test_end_with_multiple_open_votes(services):
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    v1 = svc.vote_repo.create(m.id, "Vote 1", ["A", "B"])
    v2 = svc.vote_repo.create(m.id, "Vote 2", ["C", "D"])
    vote_events = []
    bus.subscribe("vote_closed", lambda e: vote_events.append(e))
    svc.end(m.id)
    assert len(vote_events) == 2
    ids = {e.payload["vote_id"] for e in vote_events}
    assert ids == {v1.id, v2.id}


def test_start_finished_meeting_fails(services):
    """CR-008: start() should validate target meeting status, reject finished meetings."""
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    svc.end(m.id)
    # Meeting is now "finished" — starting should fail
    result = svc.start(m.id)
    assert result is None
    # Meeting should still be "finished"
    meeting = svc.get_by_id(m.id)
    assert meeting.status == "finished"


def test_delete_active_meeting_fails(services):
    """CR-011: delete() should reject deletion of active meetings."""
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    # Meeting is "active" — deleting should fail
    result = svc.delete(m.id)
    assert result is False
    # Meeting should still exist and be active
    meeting = svc.get_by_id(m.id)
    assert meeting is not None
    assert meeting.status == "active"


def test_delete_pending_meeting_succeeds(services):
    """delete() should allow deletion of pending (non-active) meetings."""
    svc, bus = services
    m = svc.create("Test")
    result = svc.delete(m.id)
    assert result is True
    assert svc.get_by_id(m.id) is None


def test_delete_finished_meeting_succeeds(services):
    """delete() should allow deletion of finished meetings."""
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    svc.end(m.id)
    # Meeting is "finished" — deleting should succeed
    result = svc.delete(m.id)
    assert result is True
    assert svc.get_by_id(m.id) is None


def test_delete_nonexistent_meeting_fails(services):
    """delete() should return False for non-existent meeting."""
    svc, bus = services
    result = svc.delete(9999)
    assert result is False


def test_create_with_active_meeting_fails(services):
    """CR-013: create() should reject when an active meeting already exists."""
    svc, bus = services
    m1 = svc.create("Meeting 1")
    svc.start(m1.id)
    # An active meeting exists — create should return None
    result = svc.create("Meeting 2")
    assert result is None


def test_remove_attendee_wrong_meeting_fails(services):
    """CR-014: remove_attendee() should not delete an attendee belonging to a different meeting."""
    svc, bus = services
    m1 = svc.create("Meeting 1")
    m2 = svc.create("Meeting 2")
    a = svc.add_attendee(m2.id, "Alice", seat_id=5)
    # Try to remove attendee from meeting 1 — should fail because attendee belongs to meeting 2
    result = svc.remove_attendee(m1.id, a.id)
    assert result is False
    # Attendee should still exist in meeting 2
    att = svc.attendee_repo.get_by_id(a.id)
    assert att is not None
    assert att.meeting_id == m2.id


def test_remove_attendee_nonexistent_attendee_fails(services):
    """remove_attendee() should return False for a non-existent attendee."""
    svc, bus = services
    m = svc.create("Test")
    result = svc.remove_attendee(m.id, 9999)
    assert result is False


def test_vote_closed_event_has_meeting_id(services):
    """CR-012: vote_closed event payload must include meeting_id for consistency."""
    svc, bus = services
    m = svc.create("Test")
    svc.start(m.id)
    v = svc.vote_repo.create(m.id, "Vote 1", ["Yes", "No"])
    vote_events = []
    bus.subscribe("vote_closed", lambda e: vote_events.append(e))
    svc.end(m.id)
    assert len(vote_events) == 1
    assert vote_events[0].payload["vote_id"] == v.id
    assert vote_events[0].payload["meeting_id"] == m.id
