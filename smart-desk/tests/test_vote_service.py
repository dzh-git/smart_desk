import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.vote_repository import VoteRepository
from backend.services.event_bus import EventBus
from backend.services.vote_service import (
    VoteService, VoteNotFoundError, VoteClosedError, InvalidVoteOptionError,
)


@pytest.fixture
def vote_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    ar = AttendeeRepository(db)
    a = ar.create(m.id, "John", seat_id=1)
    bus = EventBus()
    vr = VoteRepository(db)
    svc = VoteService(bus, vr)
    yield svc, bus, m.id, a.id
    db.close()


def test_create_vote(vote_services):
    svc, bus, meeting_id, _ = vote_services
    events = []
    bus.subscribe("vote_started", lambda e: events.append(e))
    v = svc.create(meeting_id, "Budget", ["Yes", "No"], is_anonymous=False)
    assert v.title == "Budget"
    assert len(events) == 1


def test_cast_and_close(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"])
    # Reset events
    events = []
    bus.subscribe("vote_updated", lambda e: events.append(e))
    bus.subscribe("vote_closed", lambda e: events.append(e))
    svc.cast(meeting_id, v.id, attendee_id, "A")
    assert len(events) == 1  # vote_updated fired
    svc.close(meeting_id, v.id)
    # Check close event fired
    close_events = [e for e in events if e.name == "vote_closed"]
    assert len(close_events) == 1


def test_statistics_anonymous(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"], is_anonymous=True)
    svc.cast(meeting_id, v.id, attendee_id, "A")
    stats = svc.get_statistics(v.id)
    assert stats["is_anonymous"] is True
    assert isinstance(stats["results"], dict)
    assert stats["results"]["A"] == 1
    assert stats["results"]["B"] == 0


def test_statistics_named(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Poll", ["Opt1", "Opt2"], is_anonymous=False)
    svc.cast(meeting_id, v.id, attendee_id, "Opt1")
    stats = svc.get_statistics(v.id)
    assert stats["is_anonymous"] is False
    assert "Opt1" in stats["results"]
    assert "Opt2" in stats["results"]
    assert attendee_id in stats["results"]["Opt1"]
    assert stats["results"]["Opt2"] == []


def test_create_empty_title(vote_services):
    svc, bus, meeting_id, _ = vote_services
    with pytest.raises(ValueError, match="title must not be empty"):
        svc.create(meeting_id, "", ["A"])


def test_create_whitespace_title(vote_services):
    svc, bus, meeting_id, _ = vote_services
    with pytest.raises(ValueError, match="title must not be empty"):
        svc.create(meeting_id, "   ", ["A"])


def test_create_empty_options(vote_services):
    svc, bus, meeting_id, _ = vote_services
    with pytest.raises(ValueError, match="options must not be empty"):
        svc.create(meeting_id, "Valid Title", [])


def test_cast_nonexistent_vote(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    with pytest.raises(VoteNotFoundError):
        svc.cast(meeting_id, 999, attendee_id, "A")


def test_cast_closed_vote(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"])
    svc.close(meeting_id, v.id)
    with pytest.raises(VoteClosedError):
        svc.cast(meeting_id, v.id, attendee_id, "A")


def test_cast_invalid_option(vote_services):
    svc, bus, meeting_id, attendee_id = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"])
    with pytest.raises(InvalidVoteOptionError):
        svc.cast(meeting_id, v.id, attendee_id, "C")


def test_close_nonexistent_vote(vote_services):
    svc, bus, meeting_id, _ = vote_services
    with pytest.raises(VoteNotFoundError):
        svc.close(meeting_id, 999)


def test_close_already_closed(vote_services):
    svc, bus, meeting_id, _ = vote_services
    v = svc.create(meeting_id, "Test", ["A", "B"])
    svc.close(meeting_id, v.id)
    with pytest.raises(VoteClosedError):
        svc.close(meeting_id, v.id)


def test_get_statistics_nonexistent(vote_services):
    svc, bus, meeting_id, _ = vote_services
    with pytest.raises(VoteNotFoundError):
        svc.get_statistics(999)
