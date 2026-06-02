import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import SeatState, SpeakerSeat
from backend.repositories.seat_repository import SeatRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    # Seed required data
    for sid in range(1, 11):
        session.add(SeatState(seat_id=sid, status="vacant"))
    session.add(SpeakerSeat(id=1, seat_id=None))
    session.commit()
    yield session
    session.close()


def test_get_seat_state(db_session):
    repo = SeatRepository(db_session)
    state = repo.get_seat_state(1)
    assert state is not None
    assert state.seat_id == 1
    assert state.status == "vacant"


def test_update_seat_status(db_session):
    repo = SeatRepository(db_session)
    s = repo.update_seat(3, "occupied_unchecked", attendee_id=5)
    assert s.status == "occupied_unchecked"
    assert s.attendee_id == 5


def test_reset_all_seats(db_session):
    repo = SeatRepository(db_session)
    repo.update_seat(1, "checked_in", attendee_id=1)
    repo.update_seat(2, "occupied_unchecked", attendee_id=2)
    repo.reset_all_seats()
    for sid in range(1, 11):
        s = repo.get_seat_state(sid)
        assert s.status == "vacant"
        assert s.attendee_id is None


def test_get_all_seats(db_session):
    repo = SeatRepository(db_session)
    all_seats = repo.get_all_seats()
    assert len(all_seats) == 10


def test_speaker_seat_lifecycle(db_session):
    repo = SeatRepository(db_session)
    sp = repo.get_speaker_seat()
    assert sp.seat_id is None
    repo.set_speaker_seat(5)
    sp = repo.get_speaker_seat()
    assert sp.seat_id == 5
    repo.clear_speaker_seat()
    sp = repo.get_speaker_seat()
    assert sp.seat_id is None


def test_get_seat_state_nonexistent(db_session):
    repo = SeatRepository(db_session)
    state = repo.get_seat_state(999)
    assert state is None


def test_update_seat_nonexistent(db_session):
    repo = SeatRepository(db_session)
    result = repo.update_seat(999, "checked_in", attendee_id=1)
    assert result is None


@pytest.fixture
def db_session_empty():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_get_speaker_seat_when_no_row(db_session_empty):
    repo = SeatRepository(db_session_empty)
    sp = repo.get_speaker_seat()
    assert sp is None


def test_update_seat_invalid_status_raises(db_session):
    repo = SeatRepository(db_session)
    with pytest.raises(ValueError, match="Invalid status"):
        repo.update_seat(1, "invalid_status")


def test_update_seat_valid_statuses_all_accepted(db_session):
    repo = SeatRepository(db_session)
    for status in ["vacant", "occupied_unchecked", "checked_in"]:
        result = repo.update_seat(1, status)
        assert result.status == status


def test_set_speaker_seat_when_no_row(db_session_empty):
    repo = SeatRepository(db_session_empty)
    result = repo.set_speaker_seat(5)
    assert result is None


def test_clear_speaker_seat_when_no_row(db_session_empty):
    repo = SeatRepository(db_session_empty)
    result = repo.clear_speaker_seat()
    assert result is None


def test_import_from_repositories_package():
    from backend.repositories import SeatRepository
    assert SeatRepository is not None
