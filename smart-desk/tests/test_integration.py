# tests/test_integration.py
"""Black-box integration tests: full meeting lifecycle through HTTP API."""

import pytest

# CR-023: Shared client and reset_state fixtures are in tests/conftest.py.
# Activate reset_state (non-autouse) for all tests in this file.
pytestmark = pytest.mark.usefixtures("reset_state")


class TestMeetingLifecycle:
    """Full meeting flow: create → start → operate → end."""

    def test_create_and_start_meeting(self, client):
        # Create meeting
        resp = client.post("/api/meetings", json={
            "title": "Integration Test Meeting",
            "description": "Testing full lifecycle"
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["success"] is True
        meeting_id = data["data"]["id"]
        assert data["data"]["status"] == "pending"

        # Creating another pending meeting while first is still pending — should succeed
        # (spec only rejects creation when an *active* meeting exists)
        resp2 = client.post("/api/meetings", json={"title": "Second"})
        assert resp2.status_code == 201

        # Start meeting
        resp = client.post(f"/api/meetings/{meeting_id}/start")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"

        # Now creating another when one is active
        resp3 = client.post("/api/meetings", json={"title": "Third"})
        assert resp3.status_code == 400  # ACTIVE_MEETING_EXISTS

        # Get active meeting
        resp = client.get("/api/meetings/active")
        assert resp.json()["data"]["id"] == meeting_id

    def test_seat_lifecycle(self, client):
        # First create and start meeting
        resp = client.post("/api/meetings", json={"title": "Seat Test"})
        mid = resp.json()["data"]["id"]
        start_resp = client.post(f"/api/meetings/{mid}/start")
        assert start_resp.status_code == 200

        # Add attendee
        resp = client.post(f"/api/meetings/{mid}/attendees", json={
            "name": "Test User", "title": "Engineer", "seat_id": 3
        })
        assert resp.status_code == 201
        aid = resp.json()["data"]["id"]

        # List seats
        resp = client.get("/api/seats")
        assert resp.status_code == 200
        assert len(resp.json()["data"]) == 10

        # Simulate seat occupied (via debug endpoint)
        sim_resp = client.post("/api/debug/simulate/3?action=occupied")
        assert sim_resp.status_code == 200

        # Checkin (must provide attendee_id now per spec B3)
        resp = client.post(f"/api/seats/3/checkin", json={"attendee_id": aid})
        assert resp.status_code == 200

        # Re-checkin must return 409 (SEAT_ALREADY_CHECKED_IN)
        resp2 = client.post(f"/api/seats/3/checkin", json={"attendee_id": aid})
        assert resp2.status_code == 409

        # Set speaker seat
        resp = client.post("/api/seats/speaker", json={"seat_id": 3})
        assert resp.status_code == 200
        assert resp.json()["data"]["seat_id"] == 3

        # Clear speaker seat
        resp = client.delete("/api/seats/speaker")
        assert resp.status_code == 200
        assert resp.json()["data"]["seat_id"] is None

    def test_vote_lifecycle(self, client):
        # Setup: create + start meeting + add attendee
        resp = client.post("/api/meetings", json={"title": "Vote Test"})
        mid = resp.json()["data"]["id"]
        start_resp = client.post(f"/api/meetings/{mid}/start")
        assert start_resp.status_code == 200
        resp = client.post(f"/api/meetings/{mid}/attendees", json={
            "name": "Voter", "seat_id": 1
        })
        aid = resp.json()["data"]["id"]

        # Create vote
        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "Test Vote",
            "options": ["Yes", "No", "Abstain"], "is_anonymous": False
        })
        assert resp.status_code == 201
        vid = resp.json()["data"]["id"]

        # Get active vote
        resp = client.get(f"/api/votes/active?meeting_id={mid}")
        assert resp.json()["data"]["id"] == vid

        # Cast vote
        resp = client.post(f"/api/votes/{vid}/submit", json={
            "attendee_id": aid, "option": "Yes"
        })
        assert resp.status_code == 200

        # Get statistics (accessible to Seat tablets per C9)
        resp = client.get(f"/api/votes/{vid}/statistics")
        assert resp.status_code == 200
        stats = resp.json()["data"]
        assert stats["results"]["Yes"] == [aid]

        # Close vote
        resp = client.post(f"/api/votes/{vid}/close")
        assert resp.status_code == 200

    def test_service_call_lifecycle(self, client):
        # Setup
        resp = client.post("/api/meetings", json={"title": "SC Test"})
        mid = resp.json()["data"]["id"]
        start_resp = client.post(f"/api/meetings/{mid}/start")
        assert start_resp.status_code == 200

        # Create service call
        resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
            "seat_id": 4, "service_type": "coffee"
        })
        assert resp.status_code == 201
        cid = resp.json()["data"]["id"]

        # Duplicate pending rejected (one per seat)
        resp2 = client.post(f"/api/service-calls?meeting_id={mid}", json={
            "seat_id": 4, "service_type": "tea"
        })
        assert resp2.status_code == 409  # SERVICE_CALL_ALREADY_PENDING

        # List
        resp = client.get(f"/api/service-calls?meeting_id={mid}")
        assert len(resp.json()["data"]) == 1

        # Resolve
        resp = client.post(f"/api/service-calls/{cid}/resolve")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "resolved"

    def test_end_meeting_cleans_up(self, client):
        """Verify meeting end resets seats, clears speaker, auto-closes votes."""
        resp = client.post("/api/meetings", json={"title": "End Test"})
        mid = resp.json()["data"]["id"]
        start_resp = client.post(f"/api/meetings/{mid}/start")
        assert start_resp.status_code == 200

        # Add attendee + checkin + set speaker
        resp = client.post(f"/api/meetings/{mid}/attendees", json={
            "name": "User", "seat_id": 3
        })
        aid = resp.json()["data"]["id"]
        sim_resp = client.post("/api/debug/simulate/3?action=occupied")
        assert sim_resp.status_code == 200
        checkin_resp = client.post(f"/api/seats/3/checkin", json={"attendee_id": aid})
        assert checkin_resp.status_code == 200
        spk_resp = client.post("/api/seats/speaker", json={"seat_id": 3})
        assert spk_resp.status_code == 200

        # Create open vote
        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "End Test Vote",
            "options": ["A", "B"], "is_anonymous": False
        })
        vid = resp.json()["data"]["id"]

        # End meeting
        resp = client.post(f"/api/meetings/{mid}/end")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "finished"

        # Verify seats reset (system has exactly 10 seats per DATABASE_SCHEMA.md)
        resp = client.get("/api/seats")
        seats_data = resp.json()["data"]
        assert len(seats_data) == 10, f"Expected 10 seats, got {len(seats_data)}"
        for seat in seats_data:
            assert seat["status"] == "vacant"

        # Verify speaker seat cleared
        resp = client.get("/api/seats/speaker")
        assert resp.json()["data"]["seat_id"] is None

        # Verify vote auto-closed
        resp = client.get(f"/api/votes/{vid}")
        assert resp.json()["data"]["status"] == "closed"

        # Dashboard
        resp = client.get(f"/api/dashboard?meeting_id={mid}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["meeting"]["status"] == "finished"

    def test_translation_endpoints(self, client):
        # Setup
        resp = client.post("/api/meetings", json={"title": "Trans Test"})
        mid = resp.json()["data"]["id"]
        start_resp = client.post(f"/api/meetings/{mid}/start")
        assert start_resp.status_code == 200

        # Preload status (router uses /api/translations prefix, returns unified envelope)
        resp = client.get("/api/translations/preload/status")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"]["ready"], bool)

        # History (empty)
        resp = client.get(f"/api/translations?meeting_id={mid}")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_unified_response_format(self, client):
        """All endpoints return {"success": bool, "message": str, "data": ...}"""
        # GET endpoints (success paths)
        get_endpoints = [
            ("GET", "/api/meetings/active"),
            ("GET", "/api/seats"),
            ("GET", "/api/seats/speaker"),
        ]
        for method, path in get_endpoints:
            resp = client.get(path)
            data = resp.json()
            assert "success" in data, f"{path}: missing 'success'"
            assert "message" in data, f"{path}: missing 'message'"
            assert "data" in data, f"{path}: missing 'data'"

        # POST endpoint (success path)
        resp = client.post("/api/meetings", json={"title": "Format Test"})
        data = resp.json()
        assert "success" in data, "POST /api/meetings: missing 'success'"
        assert data["success"] is True, "POST /api/meetings: success must be True"
        assert "message" in data, "POST /api/meetings: missing 'message'"
        assert "data" in data, "POST /api/meetings: missing 'data'"
        assert data["data"] is not None, "POST /api/meetings: data must not be null on success"
        # Cleanup: end meeting if created
        if data.get("data") and isinstance(data["data"], dict):
            mid = data["data"].get("id")
            if mid:
                client.post(f"/api/meetings/{mid}/end")

        # Error response must include error_code (per API_SPEC.md sections 1 and 11)
        resp = client.get("/api/meetings/99999")
        assert resp.status_code == 404
        err_data = resp.json()
        assert "success" in err_data, "error response: missing 'success'"
        assert err_data["success"] is False, "error response: success must be False"
        assert "message" in err_data, "error response: missing 'message'"
        assert "error_code" in err_data, "error response: missing 'error_code'"
        assert err_data.get("data") is None, "error response: data must be null"
