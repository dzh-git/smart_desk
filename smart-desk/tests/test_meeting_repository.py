import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_meeting(db_session):
    repo = MeetingRepository(db_session)
    meeting = repo.create("Test Meeting", "A description")
    assert meeting.id is not None
    assert meeting.title == "Test Meeting"
    assert meeting.status == "pending"


def test_get_active_returns_none_when_no_active(db_session):
    repo = MeetingRepository(db_session)
    assert repo.get_active() is None


def test_get_active_returns_active_meeting(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Active Meeting")
    repo.update_status(m.id, "active")
    active = repo.get_active()
    assert active is not None
    assert active.id == m.id


def test_list_all_returns_desc_order(db_session):
    from datetime import datetime, timezone
    from backend.models import Meeting

    # Use explicit timestamps to guarantee deterministic ordering,
    # avoiding fragility from rapid-fire creates producing equal created_at values.
    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    m1 = Meeting(title="First", created_at=t1)
    m2 = Meeting(title="Second", created_at=t2)
    db_session.add_all([m1, m2])
    db_session.commit()

    repo = MeetingRepository(db_session)
    meetings = repo.list_all()
    assert len(meetings) == 2
    assert meetings[0].title == "Second"  # t2 newer → first in desc order
    assert meetings[1].title == "First"   # t1 older → second in desc order


def test_update_status(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Test")
    updated = repo.update_status(m.id, "finished")
    assert updated.status == "finished"
    assert updated.ended_at is not None


def test_update_status_rejects_invalid(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Test")
    with pytest.raises(ValueError, match="Invalid status"):
        repo.update_status(m.id, "bogus")


def test_get_by_id_returns_meeting(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Find Me")
    found = repo.get_by_id(m.id)
    assert found is not None
    assert found.title == "Find Me"


def test_get_by_id_returns_none_for_missing(db_session):
    repo = MeetingRepository(db_session)
    assert repo.get_by_id(9999) is None


def test_delete_removes_meeting(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Delete Me")
    result = repo.delete(m.id)
    assert result is True
    assert repo.get_by_id(m.id) is None


def test_delete_returns_false_for_missing(db_session):
    repo = MeetingRepository(db_session)
    assert repo.delete(9999) is False


def test_add_agenda(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Meeting with agenda")
    a = repo.add_agenda(m.id, "Discuss Q1 Results", sort_order=1)
    assert a.id is not None
    assert a.title == "Discuss Q1 Results"
    assert a.meeting_id == m.id
    assert a.sort_order == 1


def test_list_agendas_returns_ordered(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Meeting")
    repo.add_agenda(m.id, "Second", sort_order=2)
    repo.add_agenda(m.id, "First", sort_order=1)
    agendas = repo.list_agendas(m.id)
    assert len(agendas) == 2
    assert agendas[0].title == "First"
    assert agendas[1].title == "Second"


def test_list_agendas_empty(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Empty meeting")
    assert repo.list_agendas(m.id) == []


def test_remove_agenda(db_session):
    repo = MeetingRepository(db_session)
    m = repo.create("Meeting")
    a = repo.add_agenda(m.id, "Removable")
    result = repo.remove_agenda(m.id, a.id)
    assert result is True
    assert repo.list_agendas(m.id) == []


def test_remove_agenda_wrong_meeting_fails(db_session):
    repo = MeetingRepository(db_session)
    m1 = repo.create("Meeting 1")
    m2 = repo.create("Meeting 2")
    a = repo.add_agenda(m1.id, "Agenda for M1")
    # Try to remove from wrong meeting
    result = repo.remove_agenda(m2.id, a.id)
    assert result is False
    # Agenda still exists under correct meeting
    assert len(repo.list_agendas(m1.id)) == 1


def test_get_active_deterministic_when_multiple_active(db_session):
    """CR-009: get_active must use ORDER BY for deterministic results.
    When multiple active meetings exist (data inconsistency corner case),
    the query should return the most recently created one deterministically."""
    from datetime import datetime, timezone
    from backend.models import Meeting

    t1 = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    m1 = Meeting(title="Older Active", status="active", created_at=t1)
    m2 = Meeting(title="Newer Active", status="active", created_at=t2)
    db_session.add_all([m1, m2])
    db_session.commit()

    repo = MeetingRepository(db_session)
    active = repo.get_active()
    assert active is not None
    # Must return the most recently created active meeting deterministically
    assert active.title == "Newer Active"


def test_update_status_preserves_started_at_on_re_activation(db_session):
    """CR-011: started_at must not be overwritten when re-activating an
    already-active meeting. The timestamp records the first activation."""
    repo = MeetingRepository(db_session)
    m = repo.create("Test")
    # First activation
    updated = repo.update_status(m.id, "active")
    first_started_at = updated.started_at
    assert first_started_at is not None
    # Re-activation (same status) — started_at must be preserved
    re_updated = repo.update_status(m.id, "active")
    assert re_updated.started_at == first_started_at


def test_update_status_preserves_ended_at_on_re_completion(db_session):
    """CR-011: ended_at must not be overwritten when re-completing an
    already-finished meeting. The timestamp records the first completion."""
    repo = MeetingRepository(db_session)
    m = repo.create("Test")
    # First transition to active then finished
    repo.update_status(m.id, "active")
    updated = repo.update_status(m.id, "finished")
    first_ended_at = updated.ended_at
    assert first_ended_at is not None
    # Re-completion — ended_at must be preserved
    re_updated = repo.update_status(m.id, "finished")
    assert re_updated.ended_at == first_ended_at
