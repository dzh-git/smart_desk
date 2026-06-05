# tests/test_seats_router.py
"""Integration tests for seats router endpoints 鈥?checkin, speaker seat, debug simulation."""

from collections import Counter

import pytest

from backend.services import event_bus as eb_module

# CR-023: Shared client and reset_state fixtures are in tests/conftest.py.
# Activate reset_state (non-autouse) for all tests in this file.
pytestmark = pytest.mark.usefixtures("reset_state")


def test_list_seats(client):
    resp = client.get("/api/seats")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    data = resp.json()["data"]
    assert len(data) == 10


def test_get_speaker_seat(client):
    resp = client.get("/api/seats/speaker")
    assert resp.status_code == 200
    assert resp.json()["data"]["seat_id"] is None


def test_checkin_requires_attendee_id(client):
    resp = client.post("/api/seats/3/checkin", json={"attendee_id": 999})
    assert resp.status_code == 404  # ATTENDEE_NOT_FOUND


def test_clear_speaker_seat_no_active_meeting(client):
    """CR-002: DELETE /api/seats/speaker should fail when no meeting is active."""
    resp = client.delete("/api/seats/speaker")
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "NO_ACTIVE_MEETING"


# -- CR-008: Proper error codes for different seat states --

def test_checkin_preassigned_vacant_seat_succeeds(client):
    """Manual/tablet check-in succeeds for a pre-assigned seat even before TOF occupancy."""
    resp = client.post("/api/meetings", json={"title": "CR008 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.post(f"/api/meetings/{mid}/attendees",
                       json={"name": "TestUser", "title": "QA", "seat_id": 3})
    assert resp.status_code == 201
    aid = resp.json()["data"]["id"]

    resp = client.post("/api/seats/3/checkin", json={"attendee_id": aid})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "checked_in"

    client.post(f"/api/meetings/{mid}/end")


def test_checkin_already_checked_in_returns_409(client):
    """CR-008: checkin on already-checked-in seat returns 409 SEAT_ALREADY_CHECKED_IN."""
    resp = client.post("/api/meetings", json={"title": "CR008 Test 2"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.post(f"/api/meetings/{mid}/attendees",
                       json={"name": "TestUser2", "title": "QA", "seat_id": 3})
    assert resp.status_code == 201
    aid = resp.json()["data"]["id"]

    resp = client.post("/api/debug/simulate/3?action=occupied")
    assert resp.status_code == 200

    resp = client.post("/api/seats/3/checkin", json={"attendee_id": aid})
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "checked_in"

    resp = client.post("/api/seats/3/checkin", json={"attendee_id": aid})
    assert resp.status_code == 409
    assert "ALREADY_CHECKED_IN" in resp.json()["error_code"]

    client.post(f"/api/meetings/{mid}/end")


# -- CR-009: debug_simulate must not publish duplicate EventBus events --

def test_debug_simulate_no_duplicate_events(client):
    """CR-009: debug_simulate should publish seat_occupied exactly once, not twice."""
    resp = client.post("/api/meetings", json={"title": "CR009 Test"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")

    resp = client.post(f"/api/meetings/{mid}/attendees",
                       json={"name": "CR009User", "title": "Test", "seat_id": 3})
    assert resp.status_code == 201

    publish_counts: Counter[str] = Counter()
    original_publish = None

    try:
        def counting_publish(event):
            publish_counts[event.name] += 1
            if original_publish:
                original_publish(event)

        original_publish = eb_module.event_bus.publish
        eb_module.event_bus.publish = counting_publish

        resp = client.post("/api/debug/simulate/3?action=occupied")
        assert resp.status_code == 200

        seat_occupied_count = publish_counts.get("seat_occupied", 0)
        assert seat_occupied_count == 1, (
            f"Expected 1 seat_occupied event, got {seat_occupied_count}. "
            f"All counts: {dict(publish_counts)}"
        )

        resp = client.post("/api/debug/simulate/3?action=vacant")
        assert resp.status_code == 200

        seat_vacant_count = publish_counts.get("seat_vacant", 0)
        assert seat_vacant_count == 1, (
            f"Expected 1 seat_vacant event, got {seat_vacant_count}. "
            f"All counts: {dict(publish_counts)}"
        )

    finally:
        if original_publish:
            eb_module.event_bus.publish = original_publish

    client.post(f"/api/meetings/{mid}/end")

