"""Tests for DashboardService including CR-005 and CR-006 coverage."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.database import Base
from backend.models import SeatState, SpeakerSeat
from backend.repositories.meeting_repository import MeetingRepository
from backend.repositories.attendee_repository import AttendeeRepository
from backend.repositories.seat_repository import SeatRepository
from backend.repositories.vote_repository import VoteRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.dashboard_service import DashboardService


@pytest.fixture
def dash_services():
    """Base fixture: meeting with 10 vacant seats, no speaker, no votes, no calls."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    mr = MeetingRepository(db)
    m = mr.create("Test")
    for sid in range(1, 11):
        db.add(SeatState(seat_id=sid, status="vacant"))
    db.add(SpeakerSeat(id=1, seat_id=None))
    db.commit()
    ar = AttendeeRepository(db)
    sr = SeatRepository(db)
    vr = VoteRepository(db)
    scr = ServiceCallRepository(db)
    svc = DashboardService(db, mr, ar, sr, vr, scr)
    yield svc, m.id, db, mr, ar, sr, vr, scr
    db.close()


# ── Happy path (existing spec test) ─────────────────────────────────────

def test_dashboard_returns_all_blocks(dash_services):
    """Dashboard returns meeting, speaker_seat, active_vote, pending_service_calls, seats."""
    svc, meeting_id, _db, _mr, _ar, _sr, _vr, _scr = dash_services
    result = svc.get_dashboard(meeting_id)
    assert "meeting" in result
    assert "speaker_seat" in result
    assert "active_vote" in result
    assert "pending_service_calls" in result
    assert "seats" in result
    assert len(result["seats"]) == 10


# ── Non-existent meeting ────────────────────────────────────────────────

def test_dashboard_nonexistent_meeting(dash_services):
    """Dashboard for non-existent meeting returns null meeting block."""
    svc, _mid, _db, _mr, _ar, _sr, _vr, _scr = dash_services
    result = svc.get_dashboard(9999)
    assert result["meeting"] is None
    assert result["speaker_seat"] is None
    assert result["active_vote"] is None
    assert result["pending_service_calls"] == []


# ── Active vote ─────────────────────────────────────────────────────────

def test_dashboard_with_active_vote(dash_services):
    """Dashboard returns active vote when one exists."""
    svc, meeting_id, _db, _mr, _ar, _sr, vr, _scr = dash_services
    vote = vr.create(meeting_id, "Test Vote", ["Yes", "No", "Abstain"])
    result = svc.get_dashboard(meeting_id)
    assert result["active_vote"] is not None
    assert result["active_vote"]["id"] == vote.id
    assert result["active_vote"]["title"] == "Test Vote"
    assert result["active_vote"]["options"] == ["Yes", "No", "Abstain"]
    assert result["active_vote"]["status"] == "open"


def test_dashboard_no_active_vote_when_all_closed(dash_services):
    """Dashboard returns null active_vote when all votes are closed."""
    svc, meeting_id, _db, _mr, _ar, _sr, vr, _scr = dash_services
    vote = vr.create(meeting_id, "Closed Vote", ["A", "B"])
    vr.close(vote.id)
    result = svc.get_dashboard(meeting_id)
    assert result["active_vote"] is None


# ── Pending service calls ──────────────────────────────────────────────

def test_dashboard_with_pending_calls(dash_services):
    """Dashboard returns pending service calls list."""
    svc, meeting_id, _db, _mr, _ar, _sr, _vr, scr = dash_services
    sc1 = scr.create(meeting_id, 3, "coffee")
    sc2 = scr.create(meeting_id, 5, "tea")
    result = svc.get_dashboard(meeting_id)
    assert len(result["pending_service_calls"]) == 2
    call_ids = {c["id"] for c in result["pending_service_calls"]}
    assert sc1.id in call_ids
    assert sc2.id in call_ids


def test_dashboard_pending_calls_excludes_resolved(dash_services):
    """Dashboard pending calls excludes resolved/cancelled calls."""
    svc, meeting_id, _db, _mr, _ar, _sr, _vr, scr = dash_services
    sc1 = scr.create(meeting_id, 3, "coffee")
    scr.resolve(sc1.id)
    result = svc.get_dashboard(meeting_id)
    assert len(result["pending_service_calls"]) == 0


# ── Speaker seat ────────────────────────────────────────────────────────

def test_dashboard_with_speaker_seat(dash_services):
    """Dashboard returns speaker_seat when one is assigned."""
    svc, meeting_id, _db, _mr, _ar, sr, _vr, _scr = dash_services
    sr.set_speaker_seat(7)
    result = svc.get_dashboard(meeting_id)
    assert result["speaker_seat"] == 7


def test_dashboard_no_speaker_seat(dash_services):
    """Dashboard returns null speaker_seat when none assigned."""
    svc, meeting_id, _db, _mr, _ar, _sr, _vr, _scr = dash_services
    result = svc.get_dashboard(meeting_id)
    assert result["speaker_seat"] is None


# ── Seats ───────────────────────────────────────────────────────────────

def test_dashboard_empty_seats(dash_services):
    """Dashboard returns empty seats list when no seat states exist."""
    svc, meeting_id, db, _mr, _ar, _sr, _vr, _scr = dash_services
    # Clear all seat states
    db.query(SeatState).delete()
    db.commit()
    result = svc.get_dashboard(meeting_id)
    assert result["seats"] == []


# ── CR-005: attendee_repo used to resolve names ───────────────────────

def test_dashboard_seats_include_attendee_name(dash_services):
    """CR-005: Each seat with an attendee includes the attendee's name."""
    svc, meeting_id, _db, mr, ar, sr, _vr, _scr = dash_services
    attendee = ar.create(meeting_id, "Alice", title="Engineer")
    # Assign attendee to seat 3
    sr.update_seat(3, "checked_in", attendee_id=attendee.id)
    result = svc.get_dashboard(meeting_id)
    seat3 = next((s for s in result["seats"] if s["seat_id"] == 3), None)
    assert seat3 is not None
    assert seat3["attendee_id"] == attendee.id
    assert seat3.get("attendee_name") == "Alice"


def test_dashboard_seat_without_attendee_has_none_name(dash_services):
    """CR-005: Seats without an attendee have attendee_name None."""
    svc, meeting_id, _db, _mr, _ar, _sr, _vr, _scr = dash_services
    result = svc.get_dashboard(meeting_id)
    for seat in result["seats"]:
        assert seat.get("attendee_name") is None


def test_dashboard_seat_attendee_not_found(dash_services):
    """CR-005: Seats with orphaned attendee_id have attendee_name None."""
    svc, meeting_id, _db, _mr, _ar, sr, _vr, _scr = dash_services
    sr.update_seat(5, "checked_in", attendee_id=99999)
    result = svc.get_dashboard(meeting_id)
    seat5 = next((s for s in result["seats"] if s["seat_id"] == 5), None)
    assert seat5 is not None
    assert seat5.get("attendee_name") is None


# -- CR-007: Batch attendee fetch (eliminates N+1 queries) -------------------

def test_dashboard_multiple_attendees_in_seats(dash_services):
    """CR-007: Multiple attendees across seats all resolve correctly via batch fetch."""
    svc, meeting_id, _db, mr, ar, sr, _vr, _scr = dash_services
    alice = ar.create(meeting_id, "Alice", title="Engineer")
    bob = ar.create(meeting_id, "Bob", title="Designer")
    carol = ar.create(meeting_id, "Carol", title="Manager")
    sr.update_seat(1, "checked_in", attendee_id=alice.id)
    sr.update_seat(2, "checked_in", attendee_id=bob.id)
    sr.update_seat(3, "checked_in", attendee_id=carol.id)
    result = svc.get_dashboard(meeting_id)
    seat_names = {s["seat_id"]: s.get("attendee_name") for s in result["seats"]}
    assert seat_names.get(1) == "Alice"
    assert seat_names.get(2) == "Bob"
    assert seat_names.get(3) == "Carol"
    # Vacant seats still have no attendee_name
    assert seat_names.get(4) is None
