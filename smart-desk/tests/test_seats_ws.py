# tests/test_seats_ws.py
"""Integration tests for WebSocket and EventBus seat-related operations."""

import pytest

from backend.services import event_bus as eb_module
from backend.repositories.meeting_repository import MeetingRepository as _MR
from backend.services.desk_coordinator import desk
from backend.services.seat_service import SeatService
from tests.conftest import _wait_for, _get_seat_status, _get_vote_count

# CR-023: Shared client and reset_state fixtures are in tests/conftest.py.
# Activate reset_state (non-autouse) for all tests in this file.
pytestmark = pytest.mark.usefixtures("reset_state")


# -- CR-010: WebSocket vote_cast must not cast with fake attendee_id --

def test_vote_cast_no_attendee_skips_casting(client):
    """CR-010: vote_cast from seat with no attendee must not create a fake VoteRecord."""
    resp = client.post("/api/meetings", json={"title": "CR010 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.post("/api/votes",
                       json={"meeting_id": mid, "title": "Test Vote", "options": ["Yes", "No", "Abstain"]})
    assert resp.status_code == 201
    vid = resp.json()["data"]["id"]

    initial_count = _get_vote_count(client, vid)

    with client.websocket_connect(f"/ws/{mid}?seat=5") as ws:
        ws.send_json({"type": "vote_cast", "payload": {"vote_id": vid, "option": "Yes"}})
        # CR-013: Poll to confirm async processing occurred without creating a record
        assert not _wait_for(
            lambda: _get_vote_count(client, vid) != initial_count,
            timeout=0.5,
        ), "Vote count changed unexpectedly during wait period"

    after_count = _get_vote_count(client, vid)
    assert after_count == initial_count, (
        f"Expected no new vote records (initial={initial_count}), "
        f"but got after={after_count}"
    )

    # Now assign an attendee to seat 5 and verify casting works
    resp = client.post(f"/api/meetings/{mid}/attendees",
                       json={"name": "CR010User", "title": "Voter", "seat_id": 5})
    assert resp.status_code == 201

    with client.websocket_connect(f"/ws/{mid}?seat=5") as ws:
        ws.send_json({"type": "vote_cast", "payload": {"vote_id": vid, "option": "Yes"}})
        assert _wait_for(
            lambda: _get_vote_count(client, vid) > initial_count,
            timeout=2.0,
        ), (f"Vote count did not increase: initial={initial_count}, "
            "expected vote record to be created for attendee at seat 5")

    after_count2 = _get_vote_count(client, vid)
    assert after_count2 > initial_count, (
        f"Expected vote record to be created for attendee at seat 5, "
        f"but count stayed at {after_count2}"
    )

    client.post(f"/api/meetings/{mid}/end")


# -- CR-011: WebSocket seat_occupied/seat_vacant must persist DB SeatState --

def test_ws_seat_occupied_persists_db_state(client):
    """CR-011: WebSocket seat_occupied must update DB to occupied_unchecked."""
    resp = client.post("/api/meetings", json={"title": "CR011 Occupied Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.get("/api/seats")
    seat3 = [s for s in resp.json()["data"] if s["seat_id"] == 3][0]
    assert seat3["status"] == "vacant", f"Expected vacant, got {seat3['status']}"

    with client.websocket_connect(f"/ws/{mid}?seat=3") as ws:
        ws.send_json({"type": "seat_occupied"})
        assert _wait_for(
            lambda: _get_seat_status(client, 3) == "occupied_unchecked",
            timeout=2.0,
        ), "Seat 3 did not change to occupied_unchecked within timeout"

    status = _get_seat_status(client, 3)
    assert status == "occupied_unchecked", f"Expected occupied_unchecked, got {status}"

    client.post(f"/api/meetings/{mid}/end")


def test_ws_seat_vacant_persists_db_state(client):
    """CR-011: WebSocket seat_vacant must update DB back to vacant."""
    resp = client.post("/api/meetings", json={"title": "CR011 Vacant Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    with client.websocket_connect(f"/ws/{mid}?seat=3") as ws:
        ws.send_json({"type": "seat_occupied"})
        assert _wait_for(
            lambda: _get_seat_status(client, 3) == "occupied_unchecked",
            timeout=2.0,
        ), "Seat 3 did not change to occupied_unchecked within timeout"

    assert _get_seat_status(client, 3) == "occupied_unchecked"

    with client.websocket_connect(f"/ws/{mid}?seat=3") as ws:
        ws.send_json({"type": "seat_vacant"})
        assert _wait_for(
            lambda: _get_seat_status(client, 3) == "vacant",
            timeout=2.0,
        ), "Seat 3 did not change back to vacant within timeout"

    status = _get_seat_status(client, 3)
    assert status == "vacant", f"Expected vacant, got {status}"

    client.post(f"/api/meetings/{mid}/end")


def test_debug_simulate_still_persists_db_state(client):
    """CR-011: debug_simulate must still persist DB state (via _on_serial now)."""
    resp = client.post("/api/meetings", json={"title": "CR011 DebugSim Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.post("/api/debug/simulate/7?action=occupied")
    assert resp.status_code == 200

    resp = client.get("/api/seats")
    seat7 = [s for s in resp.json()["data"] if s["seat_id"] == 7][0]
    assert seat7["status"] == "occupied_unchecked", (
        f"Expected occupied_unchecked, got {seat7['status']}"
    )

    resp = client.post("/api/debug/simulate/7?action=vacant")
    assert resp.status_code == 200

    resp = client.get("/api/seats")
    seat7_after = [s for s in resp.json()["data"] if s["seat_id"] == 7][0]
    assert seat7_after["status"] == "vacant", (
        f"Expected vacant, got {seat7_after['status']}"
    )

    client.post(f"/api/meetings/{mid}/end")


# -- CR-014: EventBus handlers must see DB-persisted state during seat events --

def test_event_handler_sees_persisted_seat_state(client):
    """CR-014: EventBus handlers running on seat_occupied must see updated DB state."""
    resp = client.post("/api/meetings", json={"title": "CR014 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    handler_saw_status = []

    def checking_handler(event):
        db_status = _get_seat_status(client, event.payload["seat_id"])
        handler_saw_status.append(db_status)

    try:
        eb_module.event_bus.subscribe("seat_occupied", checking_handler)

        resp = client.post("/api/debug/simulate/5?action=occupied")
        assert resp.status_code == 200

        assert len(handler_saw_status) == 1, (
            f"Expected handler to be called once, got {len(handler_saw_status)}"
        )
        assert handler_saw_status[0] == "occupied_unchecked", (
            f"Handler should see occupied_unchecked in DB, saw {handler_saw_status[0]}"
        )

    finally:
        eb_module.event_bus.unsubscribe("seat_occupied", checking_handler)

    client.post(f"/api/meetings/{mid}/end")


# -- CR-017: DB exceptions in _persist_seat_state must not crash serial processing --

def test_persist_seat_state_exception_does_not_crash(client):
    """CR-017: DB failure in _persist_seat_state must not crash serial processing thread
    or prevent EventBus publishing."""
    resp = client.post("/api/meetings", json={"title": "CR017 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    original_on_occupied = SeatService.on_seat_occupied

    def broken_on_occupied(self, meeting_id, seat_id):
        raise RuntimeError("Simulated DB failure - CR-017")

    SeatService.on_seat_occupied = broken_on_occupied

    try:
        # _persist_seat_state must catch exception internally
        try:
            desk._persist_seat_state(3, "occupied", mid)
        except RuntimeError:
            pytest.fail(
                "_persist_seat_state must catch DB exceptions internally "
                "and not propagate them"
            )
    finally:
        SeatService.on_seat_occupied = original_on_occupied

    # Also verify _on_serial survives DB failure
    SeatService.on_seat_occupied = broken_on_occupied
    publish_seen = []

    def tracking_handler(event):
        publish_seen.append(event.name)

    try:
        eb_module.event_bus.subscribe("seat_occupied", tracking_handler)

        resp = client.post("/api/debug/simulate/7?action=occupied")
        assert resp.status_code == 200, (
            f"debug_simulate should succeed despite DB failure, "
            f"got {resp.status_code}: {resp.text}"
        )

        assert "seat_occupied" in publish_seen, (
            "EventBus seat_occupied must still be published when DB persist fails"
        )

    finally:
        eb_module.event_bus.unsubscribe("seat_occupied", tracking_handler)
        SeatService.on_seat_occupied = original_on_occupied

    client.post(f"/api/meetings/{mid}/end")


# -- CR-019: EventBus seat_occupied/seat_vacant must carry correct meeting_id --

def test_seat_occupied_event_has_correct_meeting_id(client):
    """CR-019: seat_occupied EventBus event must carry the active meeting's ID."""
    resp = client.post("/api/meetings", json={"title": "CR019 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    event_payloads = []

    def capture_handler(event):
        event_payloads.append(dict(event.payload))

    try:
        eb_module.event_bus.subscribe("seat_occupied", capture_handler)

        resp = client.post("/api/debug/simulate/3?action=occupied")
        assert resp.status_code == 200

        assert len(event_payloads) >= 1, (
            f"Expected at least 1 seat_occupied event, got {len(event_payloads)}"
        )
        assert event_payloads[0]["meeting_id"] == mid, (
            f"Expected meeting_id={mid} in event payload, "
            f"got {event_payloads[0]['meeting_id']}"
        )
        assert event_payloads[0]["seat_id"] == 3

    finally:
        eb_module.event_bus.unsubscribe("seat_occupied", capture_handler)

    client.post(f"/api/meetings/{mid}/end")


def test_seat_vacant_event_has_correct_meeting_id(client):
    """CR-019: seat_vacant EventBus event must also carry the active meeting's ID."""
    resp = client.post("/api/meetings", json={"title": "CR019 Vacant Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.post("/api/debug/simulate/5?action=occupied")
    assert resp.status_code == 200

    event_payloads = []

    def capture_handler(event):
        event_payloads.append(dict(event.payload))

    try:
        eb_module.event_bus.subscribe("seat_vacant", capture_handler)

        resp = client.post("/api/debug/simulate/5?action=vacant")
        assert resp.status_code == 200

        assert len(event_payloads) >= 1, (
            f"Expected at least 1 seat_vacant event, got {len(event_payloads)}"
        )
        assert event_payloads[0]["meeting_id"] == mid, (
            f"Expected meeting_id={mid} in event payload, "
            f"got {event_payloads[0]['meeting_id']}"
        )
        assert event_payloads[0]["seat_id"] == 5

    finally:
        eb_module.event_bus.unsubscribe("seat_vacant", capture_handler)

    client.post(f"/api/meetings/{mid}/end")


# -- CR-022: Meeting lookup exception in _on_serial must not crash serial thread --

def test_on_serial_survives_meeting_lookup_failure(client):
    """CR-022: Exceptions during meeting_id lookup in _on_serial must not crash
    the serial processing thread. EventBus events must still publish using
    fallback legacy_id from _seat_meeting."""
    resp = client.post("/api/meetings", json={"title": "CR022 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    event_payloads = []

    def capture_handler(event):
        event_payloads.append(dict(event.payload))

    # Simulate DB query failure by monkey-patching MeetingRepository.get_active
    # to raise. _on_serial must catch this and fall back to legacy_id without
    # crashing the serial processing thread.
    _orig_get_active = _MR.get_active

    def broken_get_active(self):
        raise RuntimeError("Simulated DB query failure - CR-022 meeting lookup")

    original_publish = eb_module.event_bus.publish

    def counting_publish(event):
        event_payloads.append(event.name)
        original_publish(event)

    try:
        eb_module.event_bus.subscribe("seat_occupied", capture_handler)
        eb_module.event_bus.publish = counting_publish
        _MR.get_active = broken_get_active

        # Call _on_serial directly — get_active fails, should fall back to legacy_id
        desk._on_serial(3, {"type": "seat_occupied"})

        # Event should still be published despite DB query failure
        assert len(event_payloads) >= 1, (
            f"Expected seat_occupied event despite DB query failure, "
            f"got payloads: {event_payloads}"
        )

    finally:
        eb_module.event_bus.unsubscribe("seat_occupied", capture_handler)
        eb_module.event_bus.publish = original_publish
        _MR.get_active = _orig_get_active

    client.post(f"/api/meetings/{mid}/end")
