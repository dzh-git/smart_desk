"""Tests verifying VoteService.cast() and ServiceCallService.create() publish to EventBus.

These services replaced persist_vote_cast and persist_service_call in the WebSocket handler.
They must publish to EventBus so the ws_event_bridge can broadcast to all clients.
"""
from __future__ import annotations

import pytest

from backend.database import SessionLocal
from backend.models import Meeting, Vote, Attendee, ServiceCall
from backend.repositories.vote_repository import VoteRepository
from backend.repositories.service_call_repository import ServiceCallRepository
from backend.services.event_bus import event_bus, BaseEvent
from backend.services.vote_service import VoteService, VoteNotFoundError
from backend.services.service_call_service import ServiceCallService


# ---------------------------------------------------------------------------
# VoteService.cast() -> vote_updated event
# ---------------------------------------------------------------------------

class TestVoteServiceEventPublish:
    """VoteService.cast() publishes vote_updated to EventBus on successful cast."""

    def test_vote_cast_publishes_vote_updated(self):
        """Successful vote cast via VoteService publishes vote_updated."""
        db = SessionLocal()
        try:
            meeting = Meeting(title="CR025-Vote-Meeting", status="active")
            db.add(meeting)
            db.flush()
            mid = meeting.id

            vote = Vote(meeting_id=mid, title="CR025-Vote",
                        options=["yes", "no", "abstain"])
            db.add(vote)
            db.flush()
            vid = vote.id

            att = Attendee(meeting_id=mid, name="CR025-Tester", seat_id=88)
            db.add(att)
            db.commit()

            received = []

            def handler(event):
                received.append(event)

            event_bus.subscribe("vote_updated", handler)
            try:
                vs = VoteService(event_bus, VoteRepository(db))
                vs.cast(mid, vid, att.id, "yes")
                assert len(received) == 1, (
                    f"Expected 1 vote_updated event, got {len(received)}"
                )
                evt = received[0]
                assert evt.name == "vote_updated"
                assert evt.payload["meeting_id"] == mid, (
                    f"CR-027: vote_updated payload must include meeting_id, "
                    f"got {evt.payload}"
                )
                assert evt.payload["vote_id"] == vid
            finally:
                event_bus.unsubscribe("vote_updated", handler)

            db.delete(att)
            db.delete(vote)
            db.delete(meeting)
            db.commit()
        finally:
            db.close()

    def test_vote_cast_raises_on_invalid_vote(self):
        """VoteService.cast() raises VoteNotFoundError for nonexistent vote ID."""
        db = SessionLocal()
        try:
            meeting = Meeting(title="CR025-BadVote", status="active")
            db.add(meeting)
            db.flush()
            mid = meeting.id
            db.commit()

            received = []

            def handler(event):
                received.append(event)

            event_bus.subscribe("vote_updated", handler)
            try:
                vs = VoteService(event_bus, VoteRepository(db))
                with pytest.raises(VoteNotFoundError):
                    vs.cast(mid, 99999, 1, "yes")
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
# ServiceCallService.create() -> service_call_created event
# ---------------------------------------------------------------------------

class TestServiceCallServiceEventPublish:
    """ServiceCallService.create() publishes service_call_created to EventBus."""

    def test_service_call_create_publishes_service_call_created(self):
        """ServiceCallService.create() publishes service_call_created on creation."""
        db = SessionLocal()
        try:
            meeting = Meeting(title="CR025-SC-Meeting", status="active")
            db.add(meeting)
            db.flush()
            mid = meeting.id

            att = Attendee(meeting_id=mid, name="CR025-SC-Tester", seat_id=77)
            db.add(att)
            db.commit()

            received = []

            def handler(event):
                received.append(event)

            event_bus.subscribe("service_call_created", handler)
            try:
                scs = ServiceCallService(event_bus, ServiceCallRepository(db))
                sc = scs.create(mid, 77, "coffee", attendee_id=att.id)
                assert sc is not None, "ServiceCallService.create() should succeed"
                assert len(received) == 1, (
                    f"Expected 1 service_call_created event, got {len(received)}"
                )
                evt = received[0]
                assert evt.name == "service_call_created"
                assert evt.payload["meeting_id"] == mid, (
                    f"CR-028: service_call_created payload must include meeting_id, "
                    f"got {evt.payload}"
                )
                assert evt.payload["seat_id"] == 77
                assert evt.payload["service_type"] == "coffee"
                assert evt.payload["call_id"] == sc.id
            finally:
                event_bus.unsubscribe("service_call_created", handler)

            db.query(ServiceCall).filter(
                ServiceCall.id == sc.id
            ).delete()
            db.delete(att)
            db.delete(meeting)
            db.commit()
        finally:
            db.close()
