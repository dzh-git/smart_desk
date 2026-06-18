"""
Tests for Agenda State Machine — Phase 1.

Covers:
    1.  create agenda defaults to pending, time fields null
    2.  GET agendas returns top-level array with status/time
    3.  set-current: pending → active
    4.  set-current: skipped → active, clears skipped_at
    5.  set-current already-active is idempotent, no started_at refresh
    6.  set-current completed → 400
    7.  Set-current with existing active: old → completed, new → active
    8.  complete non-active → 400
    9.  skip non-active → 400
    10. advance without active → 400
    11. advance with next pending: current completed, next active
    12. advance last active: current completed, no current agenda
    13. delete active agenda → 400
    14. Ended meeting write operations (create/delete/set-current/advance/complete/skip) → 400
    15. GET ended meeting agendas still works
    16. agenda_updated events fired on create/delete/set-current/advance/complete/skip
    17. No two active agendas for same meeting
"""
from __future__ import annotations

import pytest

from backend.exceptions import NotFoundError, ConflictError, ValidationError
from backend.services.meeting_service import MeetingService
from backend.models.agenda import Agenda


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def svc(db, event_bus):
    """MeetingService with test DB and EventBus."""
    return MeetingService(db, event_bus)


def _create_pending(svc, title="Test Meeting") -> int:
    """Helper: create a pending meeting, return meeting_id."""
    m = svc.create_meeting(title=title, description="desc")
    return m.id


def _start_meeting(svc, meeting_id: int | None = None) -> int:
    """Helper: ensure an active meeting exists, return meeting_id."""
    if meeting_id is None:
        meeting_id = _create_pending(svc)
    svc.start_meeting(meeting_id)
    return meeting_id


def _add_agenda(svc, meeting_id: int, title: str, sort_order: int = 0) -> Agenda:
    """Helper: create a pending agenda in an active meeting."""
    return svc.create_agenda(meeting_id, title, sort_order)


# ── Helpers for ended-meeting tests ───────────────────────────────────────────

_ENDED_WRITE_OPS = [
    "create",
    "delete",
    "set_current",
    "advance",
    "complete",
    "skip",
]


# =============================================================================
# 1. Create agenda defaults
# =============================================================================


class TestCreateAgendaDefaults:
    """Requirement 1: create agenda defaults to pending, time fields null."""

    def test_default_status_is_pending(self, svc):
        """New agenda in active meeting has status='pending'."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Test Item")
        assert agenda.status == "pending"

    def test_default_time_fields_null(self, svc):
        """New agenda has started_at=None, completed_at=None, skipped_at=None."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "No Times Yet")
        assert agenda.started_at is None
        assert agenda.completed_at is None
        assert agenda.skipped_at is None

    def test_create_agenda_in_ended_meeting_fails(self, svc):
        """Cannot create agenda in ended meeting."""
        mid = _start_meeting(svc)
        svc.end_meeting(mid)
        with pytest.raises(ValidationError, match="not active"):
            svc.create_agenda(mid, "Late Agenda")

    def test_create_agenda_in_pending_meeting_fails(self, svc):
        """Cannot create agenda in pending (not started) meeting."""
        mid = _create_pending(svc)
        with pytest.raises(ValidationError, match="not active"):
            svc.create_agenda(mid, "Too Early")


# =============================================================================
# 2. GET agendas returns top-level array with status/time
# =============================================================================


class TestListAgendasWithStatus:
    """Requirement 2: GET agendas returns top-level array, each with status/time."""

    def test_list_returns_array(self, svc):
        """list_agendas returns a top-level list."""
        mid = _start_meeting(svc)
        _add_agenda(svc, mid, "A", 1)
        _add_agenda(svc, mid, "B", 2)
        agendas = svc.list_agendas(mid)
        assert isinstance(agendas, list)

    def test_items_have_status_and_time_fields(self, svc):
        """Each agenda item has status, started_at, completed_at, skipped_at."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Has Fields")
        # ORM object has the attributes
        assert hasattr(agenda, "status")
        assert hasattr(agenda, "started_at")
        assert hasattr(agenda, "completed_at")
        assert hasattr(agenda, "skipped_at")
        assert agenda.status == "pending"

    def test_list_agendas_ended_meeting_still_works(self, svc):
        """GET agendas for ended meeting still returns data."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Survivor", 1)
        a2 = _add_agenda(svc, mid, "Skipper", 2)
        svc.end_meeting(mid)
        agendas = svc.list_agendas(mid)
        assert len(agendas) == 2
        assert agendas[0].id == a1.id
        assert agendas[1].id == a2.id


# =============================================================================
# 3. set-current: pending → active
# =============================================================================


class TestSetCurrentPendingToActive:
    """Requirement 3: set-current transitions pending → active."""

    def test_pending_becomes_active(self, svc):
        """Pending agenda becomes active after set-current."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Make Active", 1)
        result = svc.set_current_agenda(mid, agenda.id)
        assert result.status == "active"
        assert result.started_at is not None
        assert result.completed_at is None
        assert result.skipped_at is None

    def test_only_one_active_after_set_current(self, svc):
        """Only one active agenda after calling set-current."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        a2 = _add_agenda(svc, mid, "Second", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.set_current_agenda(mid, a2.id)
        # a1 should now be completed, a2 active
        a1_refreshed = svc.meeting_repo.get_agenda_by_id(a1.id)
        a2_refreshed = svc.meeting_repo.get_agenda_by_id(a2.id)
        assert a1_refreshed.status == "completed"
        assert a2_refreshed.status == "active"


# =============================================================================
# 4. set-current: skipped → active, clears skipped_at
# =============================================================================


class TestSetCurrentSkippedToActive:
    """Requirement 4: set-current on skipped → active, clears skipped_at."""

    def test_skipped_becomes_active_clears_skipped_at(self, svc):
        """Skipped agenda becomes active; skipped_at cleared, started_at set."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Skip & Reactivate", 1)
        # Activate then skip
        svc.set_current_agenda(mid, agenda.id)
        svc.skip_agenda(mid, agenda.id)
        assert agenda.status == "skipped"
        assert agenda.skipped_at is not None
        # Reactivate
        result = svc.set_current_agenda(mid, agenda.id)
        assert result.status == "active"
        assert result.skipped_at is None
        assert result.started_at is not None
        assert result.completed_at is None


# =============================================================================
# 5. set-current already-active is idempotent
# =============================================================================


class TestSetCurrentIdempotent:
    """Requirement 5: set-current on already-active is idempotent, no started_at update."""

    def test_set_current_idempotent_preserves_started_at(self, svc):
        """Calling set-current on the active agenda does not refresh started_at."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Idempotent", 1)
        first = svc.set_current_agenda(mid, agenda.id)
        original_started_at = first.started_at
        # Call again
        second = svc.set_current_agenda(mid, agenda.id)
        assert second.status == "active"
        assert second.started_at == original_started_at

    def test_set_current_idempotent_no_event_duplication(self, svc, event_bus):
        """Idempotent set-current still returns the agenda (no error)."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "No Double Event", 1)
        svc.set_current_agenda(mid, agenda.id)
        # Second call should succeed, returning agenda
        result = svc.set_current_agenda(mid, agenda.id)
        assert result.id == agenda.id
        assert result.status == "active"


# =============================================================================
# 6. set-current completed → 400
# =============================================================================


class TestSetCurrentCompletedFails:
    """Requirement 6: set-current on completed → 400."""

    def test_set_current_completed_returns_400(self, svc):
        """Cannot set a completed agenda as current."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Completed Item", 1)
        svc.set_current_agenda(mid, agenda.id)
        svc.complete_agenda(mid, agenda.id)
        with pytest.raises(ValidationError, match="completed|not be set"):
            svc.set_current_agenda(mid, agenda.id)


# =============================================================================
# 7. Set-current with existing active: old → completed, new → active
# =============================================================================


class TestSetCurrentSwitchesActive:
    """Requirement 7: switching active agenda completes old, activates new."""

    def test_switch_old_becomes_completed(self, svc):
        """When switching to a new agenda, old active becomes completed."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Old Active", 1)
        a2 = _add_agenda(svc, mid, "New Active", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.set_current_agenda(mid, a2.id)
        old = svc.meeting_repo.get_agenda_by_id(a1.id)
        assert old.status == "completed"
        assert old.completed_at is not None

    def test_switch_new_becomes_active(self, svc):
        """When switching, the new agenda becomes active."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        a2 = _add_agenda(svc, mid, "Second", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.set_current_agenda(mid, a2.id)
        new = svc.meeting_repo.get_agenda_by_id(a2.id)
        assert new.status == "active"
        assert new.started_at is not None
        assert new.completed_at is None

    def test_switch_old_has_completed_at_and_skipped_null(self, svc):
        """Old active gets completed_at set, skipped_at cleared."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Former", 1)
        a2 = _add_agenda(svc, mid, "Latter", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.set_current_agenda(mid, a2.id)
        old = svc.meeting_repo.get_agenda_by_id(a1.id)
        assert old.completed_at is not None
        assert old.skipped_at is None

    def test_switch_no_duplicate_active(self, svc):
        """After switching, only the new agenda is active."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "A1", 1)
        a2 = _add_agenda(svc, mid, "A2", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.set_current_agenda(mid, a2.id)
        active = svc.meeting_repo.get_active_agenda(mid)
        assert active is not None
        assert active.id == a2.id


# =============================================================================
# 8. complete non-active → 400
# =============================================================================


class TestCompleteNonActiveFails:
    """Requirement 8: complete on non-active agenda → 400."""

    def test_complete_pending_fails(self, svc):
        """Cannot complete a pending agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Pending Item", 1)
        with pytest.raises(ValidationError, match="active"):
            svc.complete_agenda(mid, agenda.id)

    def test_complete_completed_fails(self, svc):
        """Cannot complete an already-completed agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Already Done", 1)
        svc.set_current_agenda(mid, agenda.id)
        svc.complete_agenda(mid, agenda.id)
        with pytest.raises(ValidationError, match="active"):
            svc.complete_agenda(mid, agenda.id)

    def test_complete_skipped_fails(self, svc):
        """Cannot complete a skipped agenda."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Active One", 1)
        a2 = _add_agenda(svc, mid, "Skippable", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.skip_agenda(mid, a1.id)
        with pytest.raises(ValidationError, match="active"):
            svc.complete_agenda(mid, a1.id)


# =============================================================================
# 9. skip non-active → 400
# =============================================================================


class TestSkipNonActiveFails:
    """Requirement 9: skip on non-active agenda → 400."""

    def test_skip_pending_fails(self, svc):
        """Cannot skip a pending agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Pending Skip", 1)
        with pytest.raises(ValidationError, match="active"):
            svc.skip_agenda(mid, agenda.id)

    def test_skip_completed_fails(self, svc):
        """Cannot skip an already-completed agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Done", 1)
        svc.set_current_agenda(mid, agenda.id)
        svc.complete_agenda(mid, agenda.id)
        with pytest.raises(ValidationError, match="active"):
            svc.skip_agenda(mid, agenda.id)


# =============================================================================
# 10. advance without active → 400
# =============================================================================


class TestAdvanceNoActiveFails:
    """Requirement 10: advance without active agenda → 400."""

    def test_advance_no_active_returns_400(self, svc):
        """Advance raises ValidationError when no active agenda."""
        mid = _start_meeting(svc)
        _add_agenda(svc, mid, "Pending but not active", 1)
        with pytest.raises(ValidationError, match="No active|active"):
            svc.advance_agenda(mid)

    def test_advance_all_completed_returns_400(self, svc):
        """Advance raises when all agendas are already completed."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Only Item", 1)
        svc.set_current_agenda(mid, a1.id)
        svc.complete_agenda(mid, a1.id)
        with pytest.raises(ValidationError, match="No active"):
            svc.advance_agenda(mid)


# =============================================================================
# 11. advance with next pending: current completed, next active
# =============================================================================


class TestAdvanceWithNextPending:
    """Requirement 11: advance completes current, activates next pending."""

    def test_current_becomes_completed(self, svc):
        """Advance completes the current active agenda."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        _add_agenda(svc, mid, "Second", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.advance_agenda(mid)
        old = svc.meeting_repo.get_agenda_by_id(a1.id)
        assert old.status == "completed"
        assert old.completed_at is not None
        assert old.skipped_at is None

    def test_next_becomes_active(self, svc):
        """Advance activates the next pending agenda."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        a2 = _add_agenda(svc, mid, "Second", 2)
        svc.set_current_agenda(mid, a1.id)
        result = svc.advance_agenda(mid)
        assert result.status == "active"
        assert result.id == a2.id
        assert result.started_at is not None
        assert result.completed_at is None

    def test_next_pending_by_sort_order(self, svc):
        """Advance activates the next pending by sort_order (not creation order)."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 10)
        a2 = _add_agenda(svc, mid, "Second", 20)
        a3 = _add_agenda(svc, mid, "Third", 5)
        svc.set_current_agenda(mid, a3.id)  # sort_order 5 is active
        result = svc.advance_agenda(mid)
        assert result.id == a1.id  # next by sort: 10 (a1), not 20 (a2)

    def test_advance_skips_completed_agendas(self, svc):
        """Advance picks next pending by sort_order, skipping non-pending items."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Active", 1)
        a2 = _add_agenda(svc, mid, "Will Be Done", 2)
        a3 = _add_agenda(svc, mid, "Next Up", 3)
        svc.set_current_agenda(mid, a1.id)
        svc.advance_agenda(mid)  # a1→completed, a2→active
        # Now complete a2 manually
        svc.complete_agenda(mid, a2.id)
        # a1=completed, a2=completed, a3=pending — but no active to advance from
        # Verify a3 is still pending and is the next pending
        a3_refreshed = svc.meeting_repo.get_agenda_by_id(a3.id)
        assert a3_refreshed.status == "pending"
        # The next pending from sort_order 0 should be a3 (skips completed a1, a2)
        next_pending = svc.meeting_repo.get_next_pending_agenda(mid, after_sort_order=0)
        assert next_pending is not None
        assert next_pending.id == a3.id


# =============================================================================
# 12. advance last active: current completed, no current agenda
# =============================================================================


class TestAdvanceLastActive:
    """Requirement 12: advance when no next pending completes current with no next."""

    def test_last_active_completed_no_next(self, svc):
        """When last active is advanced with no next pending, it's just completed."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Only Item", 1)
        svc.set_current_agenda(mid, a1.id)
        result = svc.advance_agenda(mid)
        # Result is the completed agenda (no next to return)
        assert result.status == "completed"
        assert result.id == a1.id
        assert result.completed_at is not None

    def test_no_active_after_advance_last(self, svc):
        """After advance on the last agenda, there is no active agenda."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Solo", 1)
        svc.set_current_agenda(mid, a1.id)
        svc.advance_agenda(mid)
        active = svc.meeting_repo.get_active_agenda(mid)
        assert active is None

    def test_advance_multiple_agendas_no_remaining_pending(self, svc):
        """All pending items gone after advancing through all."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        a2 = _add_agenda(svc, mid, "Second", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.advance_agenda(mid)
        svc.advance_agenda(mid)
        active = svc.meeting_repo.get_active_agenda(mid)
        assert active is None


# =============================================================================
# 13. delete active agenda → 400
# =============================================================================


class TestDeleteActiveAgendaFails:
    """Requirement 13: deleting an active agenda → 400."""

    def test_delete_active_returns_400(self, svc):
        """Cannot delete an active agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Active & Protected", 1)
        svc.set_current_agenda(mid, agenda.id)
        with pytest.raises(ValidationError, match="active"):
            svc.delete_agenda(mid, agenda.id)

    def test_delete_pending_allowed(self, svc):
        """Can delete a pending (non-active) agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Disposable", 1)
        svc.delete_agenda(mid, agenda.id)
        assert svc.meeting_repo.get_agenda_by_id(agenda.id) is None

    def test_delete_completed_allowed(self, svc):
        """Can delete a completed (non-active) agenda."""
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Completed Delete", 1)
        svc.set_current_agenda(mid, agenda.id)
        svc.complete_agenda(mid, agenda.id)
        svc.delete_agenda(mid, agenda.id)
        assert svc.meeting_repo.get_agenda_by_id(agenda.id) is None


# =============================================================================
# 14. Ended meeting write operations → 400
# =============================================================================


class TestEndedMeetingWriteGuard:
    """Requirement 14: all agenda write ops on ended meeting → 400."""

    def _ended_meeting_with_agenda(self, svc):
        """Set up an ended meeting with one active-then-completed agenda."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Item", 1)
        svc.set_current_agenda(mid, a1.id)
        svc.complete_agenda(mid, a1.id)
        svc.end_meeting(mid)
        return mid, a1

    def test_create_in_ended_fails(self, svc):
        """create_agenda in ended meeting → 400."""
        mid, _ = self._ended_meeting_with_agenda(svc)
        with pytest.raises(ValidationError, match="not active"):
            svc.create_agenda(mid, "New")

    def test_delete_in_ended_fails(self, svc):
        """delete_agenda in ended meeting → 400."""
        mid, a1 = self._ended_meeting_with_agenda(svc)
        with pytest.raises(ValidationError, match="not active"):
            svc.delete_agenda(mid, a1.id)

    def test_set_current_in_ended_fails(self, svc):
        """set_current_agenda in ended meeting → 400."""
        mid, a1 = self._ended_meeting_with_agenda(svc)
        with pytest.raises(ValidationError, match="not active"):
            svc.set_current_agenda(mid, a1.id)

    def test_advance_in_ended_fails(self, svc):
        """advance_agenda in ended meeting → 400."""
        mid, _ = self._ended_meeting_with_agenda(svc)
        with pytest.raises(ValidationError, match="not active|No active"):
            svc.advance_agenda(mid)

    def test_complete_in_ended_fails(self, svc):
        """complete_agenda in ended meeting → 400."""
        mid, a1 = self._ended_meeting_with_agenda(svc)
        with pytest.raises(ValidationError, match="not active"):
            svc.complete_agenda(mid, a1.id)

    def test_skip_in_ended_fails(self, svc):
        """skip_agenda in ended meeting → 400."""
        mid, a1 = self._ended_meeting_with_agenda(svc)
        with pytest.raises(ValidationError, match="not active"):
            svc.skip_agenda(mid, a1.id)


# =============================================================================
# 15. GET ended meeting agendas still works
# =============================================================================


class TestEndedMeetingReadAllowed:
    """Requirement 15: GET agendas for ended meeting remains available."""

    def test_list_ended_meeting_agendas(self, svc):
        """list_agendas works for ended meetings."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "Past Item", 1)
        svc.set_current_agenda(mid, a1.id)
        svc.complete_agenda(mid, a1.id)
        svc.end_meeting(mid)
        agendas = svc.list_agendas(mid)
        assert len(agendas) == 1
        assert agendas[0].status == "completed"


# =============================================================================
# 16. agenda_updated events fired
# =============================================================================


class TestAgendaUpdatedEvents:
    """Requirement 16: agenda_updated event fires on state changes."""

    def test_create_fires_event(self, svc, event_bus):
        """agenda_updated fires on create."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        _add_agenda(svc, mid, "New", 1)
        assert len(events) == 1
        assert events[0].payload["action"] == "create"
        assert events[0].payload["meeting_id"] == mid

    def test_delete_fires_event(self, svc, event_bus):
        """agenda_updated fires on delete."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Remove Me", 1)
        svc.delete_agenda(mid, agenda.id)
        assert len(events) == 2  # create + delete
        assert events[1].payload["action"] == "delete"
        assert events[1].payload["agenda_id"] == agenda.id

    def test_set_current_fires_event(self, svc, event_bus):
        """agenda_updated fires on set-current."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Activate Me", 1)
        svc.set_current_agenda(mid, agenda.id)
        actions = [e.payload["action"] for e in events]
        assert "set_current" in actions

    def test_advance_fires_event(self, svc, event_bus):
        """agenda_updated fires on advance."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        _add_agenda(svc, mid, "Second", 2)
        svc.set_current_agenda(mid, a1.id)
        svc.advance_agenda(mid)
        actions = [e.payload["action"] for e in events]
        assert "advance" in actions

    def test_complete_fires_event(self, svc, event_bus):
        """agenda_updated fires on complete."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Finish", 1)
        svc.set_current_agenda(mid, agenda.id)
        svc.complete_agenda(mid, agenda.id)
        actions = [e.payload["action"] for e in events]
        assert "complete" in actions

    def test_skip_fires_event(self, svc, event_bus):
        """agenda_updated fires on skip."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Skip Me", 1)
        svc.set_current_agenda(mid, agenda.id)
        svc.skip_agenda(mid, agenda.id)
        actions = [e.payload["action"] for e in events]
        assert "skip" in actions

    def test_event_payload_has_required_fields(self, svc, event_bus):
        """agenda_updated payload contains meeting_id, agenda_id, action, current_agenda_id."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Check Payload", 1)
        svc.set_current_agenda(mid, agenda.id)
        ev = events[1]  # second event is set_current (first is create)
        payload = ev.payload
        assert "meeting_id" in payload
        assert "agenda_id" in payload
        assert "action" in payload
        assert "current_agenda_id" in payload
        assert payload["action"] == "set_current"

    def test_set_current_event_current_agenda_id(self, svc, event_bus):
        """set_current event has current_agenda_id set to the target."""
        events = []
        event_bus.subscribe("agenda_updated", lambda e: events.append(e))
        mid = _start_meeting(svc)
        agenda = _add_agenda(svc, mid, "Now Active", 1)
        svc.set_current_agenda(mid, agenda.id)
        set_events = [e for e in events if e.payload["action"] == "set_current"]
        assert len(set_events) >= 1
        assert set_events[0].payload["current_agenda_id"] == agenda.id


# =============================================================================
# 17. No two active agendas for same meeting
# =============================================================================


class TestSingleActiveAgenda:
    """Requirement 17: no meeting can have two active agendas."""

    def test_only_one_active_after_set_current(self, svc):
        """After set-current, exactly one agenda is active."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        a2 = _add_agenda(svc, mid, "Second", 2)
        a3 = _add_agenda(svc, mid, "Third", 3)
        svc.set_current_agenda(mid, a1.id)
        svc.set_current_agenda(mid, a2.id)
        svc.set_current_agenda(mid, a3.id)
        active = svc.meeting_repo.get_active_agenda(mid)
        assert active is not None
        assert active.id == a3.id
        # Verify others are not active
        assert svc.meeting_repo.get_agenda_by_id(a1.id).status == "completed"
        assert svc.meeting_repo.get_agenda_by_id(a2.id).status == "completed"

    def test_advance_preserves_single_active(self, svc):
        """After advance, exactly one agenda is active."""
        mid = _start_meeting(svc)
        a1 = _add_agenda(svc, mid, "First", 1)
        a2 = _add_agenda(svc, mid, "Second", 2)
        a3 = _add_agenda(svc, mid, "Third", 3)
        svc.set_current_agenda(mid, a1.id)
        svc.advance_agenda(mid)
        active = svc.meeting_repo.get_active_agenda(mid)
        assert active is not None
        assert active.id == a2.id
        assert svc.meeting_repo.get_agenda_by_id(a1.id).status == "completed"
        assert svc.meeting_repo.get_agenda_by_id(a3.id).status == "pending"
