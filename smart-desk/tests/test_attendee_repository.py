import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
import backend.models  # noqa: F401
from backend.models import Vote, VoteRecord, ServiceCall
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.meeting_repository import MeetingRepository


@pytest.fixture
def db_session_with_meeting():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    meeting = mr.create("Test Meeting")
    yield session, meeting.id
    session.close()


def test_create_attendee(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "John", "CEO", seat_id=1)
    assert a.id is not None
    assert a.name == "John"
    assert a.checked_in is False


def test_list_by_meeting(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    repo.create(meeting_id, "Alice")
    repo.create(meeting_id, "Bob")
    attendees = repo.list_by_meeting(meeting_id)
    assert len(attendees) == 2


def test_check_in(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "John")
    checked = repo.check_in(a.id)
    assert checked.checked_in is True


def test_has_history(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "John")
    assert repo.has_history(meeting_id, a.id) is False
    repo.check_in(a.id)
    assert repo.has_history(meeting_id, a.id) is True


def test_get_by_id_returns_attendee(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "Alice")
    found = repo.get_by_id(a.id)
    assert found is not None
    assert found.name == "Alice"


def test_get_by_id_returns_none_for_missing(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    assert repo.get_by_id(9999) is None


def test_get_by_seat_returns_attendee(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    repo.create(meeting_id, "Alice", seat_id=5)
    a = repo.get_by_seat(meeting_id, 5)
    assert a is not None
    assert a.name == "Alice"


def test_get_by_seat_returns_none_when_empty(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    assert repo.get_by_seat(meeting_id, 99) is None


def test_count_by_meeting(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    assert repo.count_by_meeting(meeting_id) == 0
    repo.create(meeting_id, "Alice")
    repo.create(meeting_id, "Bob")
    assert repo.count_by_meeting(meeting_id) == 2


def test_count_checked_in(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a1 = repo.create(meeting_id, "Alice")
    a2 = repo.create(meeting_id, "Bob")
    assert repo.count_checked_in(meeting_id) == 0
    repo.check_in(a1.id)
    assert repo.count_checked_in(meeting_id) == 1
    repo.check_in(a2.id)
    assert repo.count_checked_in(meeting_id) == 2


def test_delete_attendee(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "Removable")
    result = repo.delete(a.id)
    assert result is True
    assert repo.get_by_id(a.id) is None


def test_delete_attendee_missing(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    assert repo.delete(9999) is False


def test_has_history_for_missing_attendee(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    assert repo.has_history(meeting_id, 9999) is False


def test_has_history_returns_true_when_has_vote(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "Voter", seat_id=3)
    # Attendee has not checked in and has no vote yet
    assert repo.has_history(meeting_id, a.id) is False
    # Create a vote and vote record directly
    v = Vote(meeting_id=meeting_id, title="Test Vote", options_json='["Yes","No"]')
    db_session.add(v)
    db_session.commit()
    vr = VoteRecord(vote_id=v.id, attendee_id=a.id, option="Yes")
    db_session.add(vr)
    db_session.commit()
    # Now has_history should return True via VoteRecord path
    assert repo.has_history(meeting_id, a.id) is True


def test_has_history_returns_true_when_has_service_call(db_session_with_meeting):
    db_session, meeting_id = db_session_with_meeting
    repo = AttendeeRepository(db_session)
    a = repo.create(meeting_id, "Caller", seat_id=4)
    # Attendee has not checked in and has no calls yet
    assert repo.has_history(meeting_id, a.id) is False
    # Create a service call linked to this specific attendee
    sc = ServiceCall(
        meeting_id=meeting_id,
        seat_id=a.seat_id,
        attendee_id=a.id,
        service_type="coffee",
    )
    db_session.add(sc)
    db_session.commit()
    # Now has_history should return True via ServiceCall path
    assert repo.has_history(meeting_id, a.id) is True


def test_has_history_vote_record_is_meeting_scoped():
    """CR-005: VoteRecord check must be scoped by meeting_id.
    An attendee who voted in Meeting A should NOT have history in Meeting B."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    m1 = mr.create("Meeting A")
    m2 = mr.create("Meeting B")
    repo = AttendeeRepository(session)
    a = repo.create(m1.id, "Cross Voter", seat_id=10)
    # Create a vote in Meeting A and record the attendee's vote
    v = Vote(meeting_id=m1.id, title="M1 Vote", options_json='["Y","N"]')
    session.add(v)
    session.commit()
    vr = VoteRecord(vote_id=v.id, attendee_id=a.id, option="Y")
    session.add(vr)
    session.commit()
    # Attendee voted in Meeting A → should NOT have history in Meeting B
    assert repo.has_history(m2.id, a.id) is False
    # But SHOULD have history in Meeting A
    assert repo.has_history(m1.id, a.id) is True
    session.close()


def test_has_history_checked_in_is_meeting_scoped():
    """CR-006: checked_in early return must be scoped by meeting_id.
    An attendee who checked in for Meeting A should NOT have history in Meeting B."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    m1 = mr.create("Meeting A")
    m2 = mr.create("Meeting B")
    repo = AttendeeRepository(session)
    a = repo.create(m1.id, "Cross Checkin", seat_id=7)
    repo.check_in(a.id)
    # Attendee checked in for Meeting A → should NOT have history in Meeting B
    assert repo.has_history(m2.id, a.id) is False
    # But SHOULD have history in Meeting A
    assert repo.has_history(m1.id, a.id) is True
    session.close()


def test_list_by_meeting_returns_id_order():
    """CR-010: list_by_meeting must return deterministic results via ORDER BY.

    Without explicit ORDER BY, SQLite may return rows in arbitrary order
    that varies between queries, causing UI flakiness and test non-determinism.
    """
    from backend.models import Attendee

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    m = mr.create("Order Test Meeting")
    repo = AttendeeRepository(session)

    # Create three attendees; auto-increment assigns ids 1,2,3 in creation order.
    # Verify list_by_meeting returns them sorted by id ascending.
    a1 = repo.create(m.id, "Charlie")  # will get id=1
    a2 = repo.create(m.id, "Alice")    # will get id=2
    a3 = repo.create(m.id, "Bob")      # will get id=3

    attendees = repo.list_by_meeting(m.id)
    assert len(attendees) == 3
    # Must be ordered by id ascending for deterministic results
    assert [a.id for a in attendees] == [a1.id, a2.id, a3.id]
    assert attendees[0].name == "Charlie"
    assert attendees[1].name == "Alice"
    assert attendees[2].name == "Bob"
    session.close()


def test_has_history_service_call_is_attendee_scoped():
    """CR-008: ServiceCall check must be scoped by attendee_id, not seat_id proxy.
    When two attendees share the same seat_id, a service call by one
    should NOT give the other a false-positive history result."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    mr = MeetingRepository(session)
    m = mr.create("Meeting")
    repo = AttendeeRepository(session)
    # Two attendees sharing the same seat_id (both default seat_id=0)
    alice = repo.create(m.id, "Alice")
    bob = repo.create(m.id, "Bob")
    assert alice.seat_id == 0
    assert bob.seat_id == 0
    assert alice.seat_id == bob.seat_id  # both share seat_id 0
    # Bob makes a service call linked to his attendee record
    sc = ServiceCall(meeting_id=m.id, seat_id=bob.seat_id, attendee_id=bob.id, service_type="coffee")
    session.add(sc)
    session.commit()
    # Alice has no history (no check-in, no vote, no service call of her own)
    # But because she shares seat_id=0 with Bob, the old seat_id proxy query
    # would falsely return True. The fix must scope by attendee, not seat.
    assert repo.has_history(m.id, alice.id) is False, (
        "CR-008: has_history must NOT use seat_id proxy for ServiceCall. "
        "Alice shares seat_id=0 with Bob but did not make the call."
    )
    # Bob has history through his service call
    assert repo.has_history(m.id, bob.id) is True
    session.close()
