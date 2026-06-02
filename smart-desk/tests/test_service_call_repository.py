import pytest
from backend.repositories.service_call_repository import ServiceCallRepository
from tests.conftest import force_expire_service_call


def test_create_service_call(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, seat_id=4, service_type="coffee")
    assert sc.id is not None
    assert sc.status == "pending"
    assert sc.service_type == "coffee"


def test_get_pending_by_seat(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    repo.create(meeting_id, 4, "coffee")
    pending = repo.get_pending_by_seat(meeting_id, 4)
    assert pending is not None
    assert repo.get_pending_by_seat(meeting_id, 5) is None


def test_resolve_and_cancel(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, 4, "tea")
    repo.resolve(sc.id)
    sc = repo.get_by_id(sc.id)
    assert sc.status == "resolved"
    assert sc.resolved_at is not None
    sc2 = repo.create(meeting_id, 5, "water")
    repo.cancel(sc2.id, reason="TIMEOUT")
    sc2 = repo.get_by_id(sc2.id)
    assert sc2.status == "cancelled"
    assert sc2.cancel_reason == "TIMEOUT"


def test_cancel_expired(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, 4, "coffee")
    force_expire_service_call(db, sc.id, seconds_ago=600)
    result = repo.cancel_expired(timeout_seconds=300)
    assert len(result) == 1
    assert result[0].status == "cancelled"
    assert result[0].cancel_reason == "TIMEOUT"


def test_create_with_custom_text(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, seat_id=3, service_type="other", custom_text="Please bring a pen")
    assert sc.id is not None
    assert sc.service_type == "other"
    assert sc.custom_text == "Please bring a pen"
    assert sc.status == "pending"


def test_list_by_meeting(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc1 = repo.create(meeting_id, seat_id=2, service_type="coffee")
    sc2 = repo.create(meeting_id, seat_id=3, service_type="tea")
    sc3 = repo.create(meeting_id, seat_id=4, service_type="water")
    calls = repo.list_by_meeting(meeting_id)
    assert len(calls) == 3
    call_ids = {c.id for c in calls}
    assert call_ids == {sc1.id, sc2.id, sc3.id}


def test_get_pending_all(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc1 = repo.create(meeting_id, seat_id=2, service_type="coffee")
    sc2 = repo.create(meeting_id, seat_id=3, service_type="tea")
    repo.resolve(sc1.id)
    pending = repo.get_pending_all(meeting_id)
    assert len(pending) == 1
    assert pending[0].id == sc2.id


def test_resolve_nonexistent(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    result = repo.resolve(99999)
    assert result is None


def test_cancel_nonexistent(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    result = repo.cancel(99999)
    assert result is None


def test_create_with_attendee_id(db_session):
    db, meeting_id = db_session
    repo = ServiceCallRepository(db)
    sc = repo.create(meeting_id, seat_id=4, service_type="coffee", attendee_id=7)
    assert sc.id is not None
    assert sc.attendee_id == 7
