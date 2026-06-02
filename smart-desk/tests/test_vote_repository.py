import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.vote_repository import VoteRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    meeting = mr.create("Test")
    ar = AttendeeRepository(session)
    att = ar.create(meeting.id, "John", seat_id=1)
    yield session, meeting.id, att.id
    session.close()


def test_create_vote(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Approve Budget", ["Agree", "Reject", "Abstain"])
    assert v.id is not None
    assert v.title == "Approve Budget"
    assert v.status == "open"
    assert v.options == ["Agree", "Reject", "Abstain"]


def test_cast_vote(db_session):
    db, meeting_id, attendee_id = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Test", ["Yes", "No"])
    ok = repo.cast(v.id, attendee_id, "Yes")
    assert ok is True
    results = repo.get_results(v.id)
    assert results["Yes"] == 1


def test_duplicate_cast_updates(db_session):
    db, meeting_id, attendee_id = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Test", ["Yes", "No"])
    repo.cast(v.id, attendee_id, "Yes")
    repo.cast(v.id, attendee_id, "No")
    results = repo.get_results(v.id)
    assert results["Yes"] == 0
    assert results["No"] == 1


def test_close_vote(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    v = repo.create(meeting_id, "Test", ["Yes"])
    closed = repo.close(v.id)
    assert closed.status == "closed"
    assert closed.closed_at is not None


def test_close_all_open(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    repo.create(meeting_id, "V1", ["A"])
    repo.create(meeting_id, "V2", ["B"])
    count = repo.close_all_open(meeting_id)
    assert count == 2


def test_get_active(db_session):
    db, meeting_id, _ = db_session
    repo = VoteRepository(db)
    assert repo.get_active(meeting_id) is None
    v = repo.create(meeting_id, "V", ["A"])
    assert repo.get_active(meeting_id).id == v.id
