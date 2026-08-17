"""
Tests for MeetingService — meeting lifecycle, agendas, attendees.

Coverage:
    - Create meeting
    - Start meeting (happy path + edge cases)
    - Block multiple active meetings
    - End meeting
    - Agenda CRUD
    - Attendee CRUD
    - Meeting end resets seats, unbinds attendees, closes open vote,
      preserves speaker seat (Phase 03)
"""
from __future__ import annotations

import pytest

from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.services.meeting_service import MeetingService
from backend.services.seat_service import SeatService
from backend.repositories.seat_repository import SeatRepository
from backend.models.seat_state import SeatState
from backend.models.vote import Vote
from backend.models.speaker_seat import SpeakerSeat


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def svc(db, event_bus):
    """MeetingService with test DB and EventBus."""
    return MeetingService(db, event_bus)


def _create_pending(svc, title="Test Meeting") -> int:
    """Helper: create a pending meeting, return meeting_id."""
    m = svc.create_meeting(title=title, description="desc")
    return m.id


# ── Create Meeting ───────────────────────────────────────────────────────────


class TestCreateMeeting:
    """POST /api/meetings — create meeting."""

    def test_create_meeting_basic(self, svc):
        """Create a meeting with title and description."""
        meeting = svc.create_meeting("Board Meeting", "Quarterly review")
        assert meeting.id is not None
        assert meeting.title == "Board Meeting"
        assert meeting.description == "Quarterly review"
        assert meeting.status == "pending"
        assert meeting.created_at is not None

    def test_create_meeting_minimal(self, svc):
        """Create a meeting with only title."""
        meeting = svc.create_meeting("Quick Sync")
        assert meeting.description == ""
        assert meeting.status == "pending"

    def test_list_meetings(self, svc):
        """List all meetings."""
        svc.create_meeting("M1")
        svc.create_meeting("M2")
        meetings = svc.list_meetings()
        assert len(meetings) == 2

    def test_get_meeting(self, svc):
        """Get meeting by ID."""
        mid = _create_pending(svc, "Target")
        meeting = svc.get_meeting(mid)
        assert meeting.title == "Target"

    def test_get_meeting_not_found(self, svc):
        """Get non-existent meeting raises NotFoundError."""
        with pytest.raises(NotFoundError, match="999.*not found"):
            svc.get_meeting(999)

    def test_get_active_meeting_none(self, svc):
        """No active meeting returns None."""
        assert svc.get_active_meeting() is None

    def test_get_active_meeting_found(self, svc):
        """Active meeting is found after start."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        active = svc.get_active_meeting()
        assert active is not None
        assert active.id == mid


# ── Start Meeting ────────────────────────────────────────────────────────────


class TestStartMeeting:
    """POST /api/meetings/{id}/start — start meeting."""

    def test_start_meeting_success(self, svc):
        """Start a pending meeting → active."""
        mid = _create_pending(svc)
        meeting = svc.start_meeting(mid)
        assert meeting.status == "active"
        assert meeting.started_at is not None

    def test_start_meeting_idempotent(self, svc):
        """Starting an already-active meeting is idempotent."""
        mid = _create_pending(svc)
        first = svc.start_meeting(mid)
        second = svc.start_meeting(mid)
        assert second.status == "active"
        assert second.started_at == first.started_at

    def test_start_finished_meeting_fails(self, svc):
        """Cannot start a finished meeting."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        svc.end_meeting(mid)
        with pytest.raises(ValidationError, match="finished"):
            svc.start_meeting(mid)

    def test_publishes_meeting_started_event(self, svc, event_bus):
        """start_meeting publishes meeting_started."""
        events = []
        event_bus.subscribe("meeting_started", lambda e: events.append(e))
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        assert len(events) == 1
        assert events[0].event_name == "meeting_started"
        assert events[0].payload["meeting_id"] == mid


# ── Block Multiple Active Meetings ───────────────────────────────────────────


class TestSingleActiveMeeting:
    """Only one meeting may be active at a time."""

    def test_second_active_meeting_blocked(self, svc):
        """Starting a second meeting while one is active raises ConflictError."""
        m1 = _create_pending(svc, "Meeting 1")
        m2 = _create_pending(svc, "Meeting 2")
        svc.start_meeting(m1)

        with pytest.raises(ConflictError, match="already active"):
            svc.start_meeting(m2)

    def test_restart_same_meeting_allowed(self, svc):
        """Starting the same meeting again does not conflict."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        # Should not raise — same meeting
        svc.start_meeting(mid)

    def test_new_meeting_after_end(self, svc):
        """After first meeting ends, second can start."""
        m1 = _create_pending(svc, "M1")
        m2 = _create_pending(svc, "M2")
        svc.start_meeting(m1)
        svc.end_meeting(m1)
        result = svc.start_meeting(m2)
        assert result.status == "active"


# ── End Meeting ──────────────────────────────────────────────────────────────


class TestEndMeeting:
    """POST /api/meetings/{id}/end — end meeting."""

    def test_end_meeting_success(self, svc):
        """End an active meeting → finished."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        meeting = svc.end_meeting(mid)
        assert meeting.status == "finished"
        assert meeting.ended_at is not None

    def test_end_pending_meeting_fails(self, svc):
        """Cannot end a pending meeting."""
        mid = _create_pending(svc)
        with pytest.raises(ValidationError, match="active"):
            svc.end_meeting(mid)

    def test_end_finished_meeting_fails(self, svc):
        """Cannot end an already-finished meeting."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        svc.end_meeting(mid)
        with pytest.raises(ValidationError, match="already finished"):
            svc.end_meeting(mid)

    def test_end_nonexistent_meeting_fails(self, svc):
        """Ending non-existent meeting raises NotFoundError."""
        with pytest.raises(NotFoundError, match="999.*not found"):
            svc.end_meeting(999)

    def test_publishes_meeting_ended_event(self, svc, event_bus):
        """end_meeting publishes meeting_ended."""
        events = []
        event_bus.subscribe("meeting_ended", lambda e: events.append(e))
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        svc.end_meeting(mid)
        assert len(events) == 1
        assert events[0].event_name == "meeting_ended"
        assert events[0].payload["meeting_id"] == mid

    def test_finished_is_irreversible(self, svc):
        """Finished meeting cannot transition to any other status."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        svc.end_meeting(mid)

        # Cannot re-end
        with pytest.raises(ValidationError):
            svc.end_meeting(mid)

        # Cannot re-start
        with pytest.raises(ValidationError):
            svc.start_meeting(mid)


# ── Agenda CRUD ──────────────────────────────────────────────────────────────


class TestAgendaCRUD:
    """Agenda create, list, delete."""

    def test_create_agenda(self, svc):
        """Create an agenda item for a meeting."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        agenda = svc.create_agenda(mid, "Financial Report", sort_order=1)
        assert agenda.id is not None
        assert agenda.title == "Financial Report"
        assert agenda.sort_order == 1
        assert agenda.meeting_id == mid
        assert agenda.status == "pending"

    def test_create_agenda_default_sort(self, svc):
        """Agenda sort_order defaults to 0."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        agenda = svc.create_agenda(mid, "Intro")
        assert agenda.sort_order == 0

    def test_create_agenda_nonexistent_meeting(self, svc):
        """Creating agenda for non-existent meeting raises NotFoundError."""
        with pytest.raises(NotFoundError, match="999.*not found"):
            svc.create_agenda(999, "Ghost Agenda")

    def test_list_agendas(self, svc):
        """List agendas sorted by sort_order."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        svc.create_agenda(mid, "Third", sort_order=3)
        svc.create_agenda(mid, "First", sort_order=1)
        svc.create_agenda(mid, "Second", sort_order=2)

        agendas = svc.list_agendas(mid)
        assert len(agendas) == 3
        assert [a.sort_order for a in agendas] == [1, 2, 3]

    def test_list_agendas_empty(self, svc):
        """List agendas for meeting with none."""
        mid = _create_pending(svc)
        assert svc.list_agendas(mid) == []

    def test_list_agendas_nonexistent_meeting(self, svc):
        """List agendas for non-existent meeting raises NotFoundError."""
        with pytest.raises(NotFoundError, match="999.*not found"):
            svc.list_agendas(999)

    def test_delete_agenda(self, svc):
        """Delete an agenda item."""
        mid = _create_pending(svc)
        svc.start_meeting(mid)
        agenda = svc.create_agenda(mid, "To Delete")
        svc.delete_agenda(mid, agenda.id)
        assert len(svc.list_agendas(mid)) == 0

    def test_delete_agenda_wrong_meeting(self, svc):
        """Cannot delete agenda belonging to different meeting."""
        m1 = _create_pending(svc, "M1")
        m2 = _create_pending(svc, "M2")
        svc.start_meeting(m1)
        agenda = svc.create_agenda(m1, "Budget")
        with pytest.raises(NotFoundError, match="Agenda.*not found"):
            svc.delete_agenda(m2, agenda.id)

    def test_delete_agenda_nonexistent(self, svc):
        """Delete non-existent agenda raises NotFoundError."""
        mid = _create_pending(svc)
        with pytest.raises(NotFoundError, match="Agenda.*not found"):
            svc.delete_agenda(mid, 999)


# ── Attendee CRUD ────────────────────────────────────────────────────────────


class TestAttendeeCRUD:
    """Attendee create, list, delete."""

    def test_create_attendee(self, svc):
        """Create an attendee for a meeting."""
        mid = _create_pending(svc)
        attendee = svc.create_attendee(mid, "Alice", "CEO")
        assert attendee.id is not None
        assert attendee.name == "Alice"
        assert attendee.title == "CEO"
        assert attendee.meeting_id == mid
        assert attendee.checked_in is False
        assert attendee.seat_id is None

    def test_create_attendee_default_title(self, svc):
        """Attendee title defaults to empty string."""
        mid = _create_pending(svc)
        attendee = svc.create_attendee(mid, "Bob")
        assert attendee.title == ""

    def test_create_attendee_nonexistent_meeting(self, svc):
        """Creating attendee for non-existent meeting raises NotFoundError."""
        with pytest.raises(NotFoundError, match="999.*not found"):
            svc.create_attendee(999, "Ghost", "Nobody")

    def test_list_attendees(self, svc):
        """List all attendees for a meeting."""
        mid = _create_pending(svc)
        svc.create_attendee(mid, "Alice")
        svc.create_attendee(mid, "Bob")
        attendees = svc.list_attendees(mid)
        assert len(attendees) == 2

    def test_list_attendees_empty(self, svc):
        """List attendees for meeting with none."""
        mid = _create_pending(svc)
        assert svc.list_attendees(mid) == []

    def test_list_attendees_nonexistent_meeting(self, svc):
        """List attendees for non-existent meeting raises NotFoundError."""
        with pytest.raises(NotFoundError, match="999.*not found"):
            svc.list_attendees(999)

    def test_delete_attendee(self, svc):
        """Delete an attendee."""
        mid = _create_pending(svc)
        attendee = svc.create_attendee(mid, "Charlie")
        svc.delete_attendee(mid, attendee.id)
        assert len(svc.list_attendees(mid)) == 0

    def test_delete_attendee_wrong_meeting(self, svc):
        """Cannot delete attendee belonging to different meeting."""
        m1 = _create_pending(svc, "M1")
        m2 = _create_pending(svc, "M2")
        attendee = svc.create_attendee(m1, "Dave")
        with pytest.raises(NotFoundError, match="Attendee.*not found"):
            svc.delete_attendee(m2, attendee.id)

    def test_delete_attendee_nonexistent(self, svc):
        """Delete non-existent attendee raises NotFoundError."""
        mid = _create_pending(svc)
        with pytest.raises(NotFoundError, match="Attendee.*not found"):
            svc.delete_attendee(mid, 999)

    def test_attendee_name_not_unique(self, svc):
        """Multiple attendees can have the same name."""
        mid = _create_pending(svc)
        a1 = svc.create_attendee(mid, "Duplicate")
        a2 = svc.create_attendee(mid, "Duplicate")
        assert a1.id != a2.id
        assert len(svc.list_attendees(mid)) == 2

    def test_attendee_id_is_persistent_business_key(self, svc):
        """Attendee id is the business key for downstream modules."""
        mid = _create_pending(svc)
        attendee = svc.create_attendee(mid, "Eve", "CFO")
        # attendee.id should be stable and usable as a business key
        fetched = svc.attendee_repo.get_by_id(attendee.id)
        assert fetched is not None
        assert fetched.id == attendee.id

    def test_seat_assignment_changes_publish_refresh_events(self, svc, event_bus):
        mid = _create_pending(svc)
        attendee = svc.create_attendee(mid, "Assigned Person")
        received = []

        def capture(event):
            received.append(event)

        event_bus.subscribe("seat_assignment_updated", capture)

        svc.assign_attendee_to_seat(mid, 1, attendee.id)
        svc.clear_seat_assignment(mid, 1)

        assert [event.meeting_id for event in received] == [mid, mid]
        assert [event.payload for event in received] == [
            {
                "seat_id": 1,
                "attendee_id": attendee.id,
                "action": "assigned",
            },
            {
                "seat_id": 1,
                "attendee_id": attendee.id,
                "action": "cleared",
            },
        ]


# ── Extended Meeting End Behavior (Phase 03) ───────────────────────────────


class TestEndMeetingExtended:
    """Meeting end: seat reset, attendee unbind, vote close, speaker preserved."""

    def _meeting_svc(self, db, event_bus) -> MeetingService:
        return MeetingService(db, event_bus)

    def _seat_svc(self, db, event_bus) -> SeatService:
        return SeatService(db, event_bus)

    def test_ends_meeting_resets_seats_to_vacant(self, seeded_db, event_bus):
        """After end_meeting, all seats are vacant with attendee_id cleared."""
        SeatRepository.init_seats(seeded_db)  # idempotent
        ms = self._meeting_svc(seeded_db, event_bus)
        ss = self._seat_svc(seeded_db, event_bus)

        mid = _create_pending(ms)
        ms.start_meeting(mid)

        # Occupy and check in some seats
        ss.seat_occupied(1)
        ss.seat_occupied(2)

        assert seeded_db.get(SeatState, 1).status == "occupied_unchecked"
        assert seeded_db.get(SeatState, 2).status == "occupied_unchecked"

        ms.end_meeting(mid)

        assert seeded_db.get(SeatState, 1).status == "vacant"
        assert seeded_db.get(SeatState, 1).attendee_id is None
        assert seeded_db.get(SeatState, 2).status == "vacant"
        assert seeded_db.get(SeatState, 2).attendee_id is None

    def test_ends_meeting_unbinds_attendees(self, seeded_db, event_bus):
        """Attendees have seat_id cleared and checked_in=false after end."""
        SeatRepository.init_seats(seeded_db)
        ms = self._meeting_svc(seeded_db, event_bus)
        ss = self._seat_svc(seeded_db, event_bus)

        mid = _create_pending(ms)
        ms.start_meeting(mid)
        attendee = ms.create_attendee(mid, "Alice")
        ss.seat_occupied(1)
        ss.check_in(1, attendee_id=attendee.id)

        assert attendee.seat_id == 1
        assert attendee.checked_in is True

        ms.end_meeting(mid)

        assert attendee.seat_id is None
        assert attendee.checked_in is False

    def test_ends_meeting_closes_open_vote(self, seeded_db, event_bus):
        """Open vote is closed when meeting ends, vote_closed event published."""
        from backend.events.vote_events import VoteClosedEvent

        SeatRepository.init_seats(seeded_db)
        ms = self._meeting_svc(seeded_db, event_bus)

        mid = _create_pending(ms)
        ms.start_meeting(mid)

        # Create a vote directly
        from backend.repositories.vote_repository import VoteRepository
        import json
        vote_repo = VoteRepository(seeded_db)
        vote = vote_repo.create(
            meeting_id=mid,
            title="Test Vote",
            options_json=json.dumps(["Yes", "No"]),
            status="open",
        )

        events = []
        event_bus.subscribe("vote_closed", lambda e: events.append(e))

        ms.end_meeting(mid)

        # Vote should be closed
        closed_vote = seeded_db.get(Vote, vote.id)
        assert closed_vote.status == "closed"
        assert closed_vote.closed_at is not None
        assert len(events) == 1
        assert events[0].event_name == "vote_closed"
        assert events[0].payload["vote_id"] == vote.id

    def test_ends_meeting_preserves_speaker_seat(self, seeded_db, event_bus):
        """Speaker seat is NOT cleared when meeting ends."""
        SeatRepository.init_seats(seeded_db)
        ms = self._meeting_svc(seeded_db, event_bus)
        ss = self._seat_svc(seeded_db, event_bus)

        mid = _create_pending(ms)
        ms.start_meeting(mid)

        # Set speaker seat
        ss.set_speaker_seat(3)
        assert seeded_db.get(SpeakerSeat, 1).seat_id == 3

        ms.end_meeting(mid)

        # Speaker seat must still be 3 (preserved)
        assert seeded_db.get(SpeakerSeat, 1).seat_id == 3

    def test_ends_meeting_publishes_meeting_ended(self, seeded_db, event_bus):
        """meeting_ended event is published."""
        SeatRepository.init_seats(seeded_db)
        ms = self._meeting_svc(seeded_db, event_bus)

        events = []
        event_bus.subscribe("meeting_ended", lambda e: events.append(e))

        mid = _create_pending(ms)
        ms.start_meeting(mid)
        ms.end_meeting(mid)

        assert len(events) == 1
        assert events[0].event_name == "meeting_ended"
        assert events[0].meeting_id == mid

    def test_ends_meeting_no_open_vote_skips_vote_closed(self, seeded_db, event_bus):
        """No vote_closed event when there is no open vote."""
        SeatRepository.init_seats(seeded_db)
        ms = self._meeting_svc(seeded_db, event_bus)

        events = []
        event_bus.subscribe("vote_closed", lambda e: events.append(e))

        mid = _create_pending(ms)
        ms.start_meeting(mid)
        ms.end_meeting(mid)

        assert len(events) == 0

    def test_ends_meeting_preserves_service_calls(self, seeded_db, event_bus):
        """Service calls (historical data) are NOT deleted."""
        SeatRepository.init_seats(seeded_db)
        ms = self._meeting_svc(seeded_db, event_bus)

        mid = _create_pending(ms)
        ms.start_meeting(mid)

        from backend.services.service_call_service import ServiceCallService
        sc_svc = ServiceCallService(seeded_db, event_bus)
        sc = sc_svc.create_call(mid, seat_id=5, service_type="coffee")
        sc_id = sc.id

        ms.end_meeting(mid)

        # Service call should still exist
        remaining = sc_svc.list_calls(mid)
        assert any(c.id == sc_id for c in remaining)
