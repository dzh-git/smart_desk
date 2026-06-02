"""Tests verifying persist helper functions publish to EventBus (CR-008).

persist_vote_cast and persist_service_call are called from main.py's
ws_endpoint for WebSocket-initiated operations. They must publish to
EventBus so the ws_event_bridge can broadcast to all clients.
"""
from __future__ import annotations

import pytest

from backend.database import SessionLocal
from backend.models import Meeting, Vote, Attendee, ServiceCall
from backend.services.event_bus import event_bus, BaseEvent
from backend.routers.votes import persist_vote_cast
from backend.routers.service_calls import persist_service_call


# ---------------------------------------------------------------------------
# persist_vote_cast -> vote_updated event
# ---------------------------------------------------------------------------

class TestPersistVoteCastEventPublish:
    """persist_vote_cast publishes vote_updated to EventBus on successful cast."""

    def test_persist_vote_cast_publishes_vote_updated(self):
        """Successful vote cast via persist_vote_cast publishes vote_updated."""
        db = SessionLocal()
        try:
            # Setup: meeting + vote + attendee
            meeting = Meeting(title="CR008-Test-Meeting", status="active")
            db.add(meeting)
            db.flush()
            mid = meeting.id

            vote = Vote(meeting_id=mid, title="CR008-Vote",
                        options=["yes", "no", "abstain"])
            db.add(vote)
            db.flush()
            vid = vote.id

            att = Attendee(meeting_id=mid, name="CR008-Tester", seat_id=88)
            db.add(att)
            db.commit()

            received = []

            def handler(event):
                received.append(event)

            event_bus.subscribe("vote_updated", handler)
            try:
                result = persist_vote_cast(mid, vid, 88, "yes")
                assert result is not None, "persist_vote_cast should succeed"
                assert len(received) == 1, (
                    f"Expected 1 vote_updated event, got {len(received)}"
                )
                evt = received[0]
                assert evt.name == "vote_updated"
                assert evt.payload["meeting_id"] == mid
                assert evt.payload["vote_id"] == vid
            finally:
                event_bus.unsubscribe("vote_updated", handler)

            # Cleanup
            db.delete(att)
            db.delete(vote)
            db.delete(meeting)
            db.commit()
        finally:
            db.close()

    def test_persist_vote_cast_no_publish_on_invalid_vote(self):
        """persist_vote_cast does NOT publish when vote is invalid/not found."""
        db = SessionLocal()
        try:
            meeting = Meeting(title="CR008-BadVote", status="active")
            db.add(meeting)
            db.flush()
            mid = meeting.id
            db.commit()

            received = []

            def handler(event):
                received.append(event)

            event_bus.subscribe("vote_updated", handler)
            try:
                result = persist_vote_cast(mid, 99999, 1, "yes")
                assert result is None, (
                    "persist_vote_cast should return None for nonexistent vote"
                )
                assert len(received) == 0, (
                    f"Expected 0 events for invalid vote, got {len(received)}"
                )
            finally:
                event_bus.unsubscribe("vote_updated", handler)

            db.delete(meeting)
            db.commit()
        finally:
            db.close()


# ---------------------------------------------------------------------------
# persist_service_call -> service_call_created event
# ---------------------------------------------------------------------------

class TestPersistServiceCallEventPublish:
    """persist_service_call publishes service_call_created to EventBus."""

    def test_persist_service_call_publishes_service_call_created(self):
        """persist_service_call publishes service_call_created on creation."""
        db = SessionLocal()
        try:
            meeting = Meeting(title="CR008-SC-Meeting", status="active")
            db.add(meeting)
            db.flush()
            mid = meeting.id

            att = Attendee(meeting_id=mid, name="CR008-SC-Tester", seat_id=77)
            db.add(att)
            db.commit()

            received = []

            def handler(event):
                received.append(event)

            event_bus.subscribe("service_call_created", handler)
            try:
                sc = persist_service_call(mid, 77, "coffee")
                assert sc is not None, "persist_service_call should succeed"
                assert len(received) == 1, (
                    f"Expected 1 service_call_created event, got {len(received)}"
                )
                evt = received[0]
                assert evt.name == "service_call_created"
                assert evt.payload["meeting_id"] == mid
                assert evt.payload["seat_id"] == 77
                assert evt.payload["service_type"] == "coffee"
            finally:
                event_bus.unsubscribe("service_call_created", handler)

            # Cleanup: service call + attendee + meeting
            db.query(ServiceCall).filter(
                ServiceCall.id == sc.id
            ).delete()
            db.delete(att)
            db.delete(meeting)
            db.commit()
        finally:
            db.close()
