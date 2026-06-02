import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.event_bus import EventBus
from backend.services.service_call_service import (
    ServiceCallService, DuplicatePendingCallError, ServiceCallNotFoundError,
)
from tests.conftest import force_expire_service_call


@pytest.fixture
def sc_services():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    bus = EventBus()
    scr = ServiceCallRepository(db)
    svc = ServiceCallService(bus, scr)
    yield svc, bus, m.id, scr
    db.close()


def test_create_service_call(sc_services):
    svc, bus, meeting_id, _ = sc_services
    events = []
    bus.subscribe("service_call_created", lambda e: events.append(e))
    sc = svc.create(meeting_id, seat_id=4, service_type="coffee")
    assert sc.status == "pending"
    assert len(events) == 1


def test_resolve_then_cancel(sc_services):
    svc, bus, meeting_id, _ = sc_services
    sc = svc.create(meeting_id, 5, "water")
    svc.resolve(sc.id)
    # After resolve, only one call exists
    sc_list = svc.list_by_meeting(meeting_id)
    assert sc_list[0].status == "resolved"
    sc2 = svc.create(meeting_id, 5, "tea")
    svc.cancel(sc2.id)
    # Verify both statuses regardless of list ordering
    statuses = {c.service_type: c.status for c in svc.list_by_meeting(meeting_id)}
    assert statuses == {"water": "resolved", "tea": "cancelled"}


def test_cancel_expired(sc_services):
    svc, bus, meeting_id, scr = sc_services
    sc = svc.create(meeting_id, seat_id=4, service_type="coffee")
    force_expire_service_call(scr.db, sc.id, seconds_ago=600)
    # Subscribe to cancellation events
    events = []
    bus.subscribe("service_call_cancelled", lambda e: events.append(e))
    expired = svc.cancel_expired()
    assert len(expired) == 1
    assert expired[0].id == sc.id
    assert expired[0].status == "cancelled"
    assert expired[0].cancel_reason == "TIMEOUT"
    assert len(events) == 1
    assert events[0].payload["call_id"] == sc.id
    assert events[0].payload["reason"] == "TIMEOUT"


def test_create_invalid_service_type(sc_services):
    svc, bus, meeting_id, _ = sc_services
    with pytest.raises(ValueError, match="service_type must be one of"):
        svc.create(meeting_id, 4, "invalid")


def test_create_with_custom_text(sc_services):
    svc, bus, meeting_id, _ = sc_services
    sc = svc.create(meeting_id, seat_id=3, service_type="other", custom_text="Please bring a pen")
    assert sc.custom_text == "Please bring a pen"
    assert sc.service_type == "other"
    assert sc.status == "pending"


def test_duplicate_pending_rejected(sc_services):
    svc, bus, meeting_id, _ = sc_services
    svc.create(meeting_id, 4, "coffee")
    with pytest.raises(DuplicatePendingCallError):
        svc.create(meeting_id, 4, "tea")


def test_resolve_nonexistent(sc_services):
    svc, bus, meeting_id, _ = sc_services
    with pytest.raises(ServiceCallNotFoundError):
        svc.resolve(99999)


def test_cancel_nonexistent(sc_services):
    svc, bus, meeting_id, _ = sc_services
    with pytest.raises(ServiceCallNotFoundError):
        svc.cancel(99999)
