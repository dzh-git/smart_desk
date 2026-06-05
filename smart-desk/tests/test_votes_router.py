"""Integration tests for votes router.

Uses shared fixtures from conftest.py (client, reset_state).
"""
import pytest


pytestmark = pytest.mark.usefixtures("reset_state")


class TestCreateVote:
    """Tests for POST /api/votes"""

    def test_create_vote(self, client):
        """Task 014 Step 4: Create vote returns 201 with success=True."""
        resp = client.post("/api/meetings", json={"title": "VM", "description": "test"})
        assert resp.status_code == 201
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "Test Vote",
            "options": ["Yes", "No"], "is_anonymous": False,
        })
        assert resp.status_code == 201
        assert resp.json()["success"] is True

    def test_create_vote_empty_title_returns_400(self, client):
        """CR-001: Empty title should return 400 not 500."""
        resp = client.post("/api/meetings", json={"title": "VM", "description": "test"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "",
            "options": ["A", "B"],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "INVALID_VOTE_DATA"

    def test_create_vote_whitespace_title_returns_400(self, client):
        """CR-001: Whitespace-only title should return 400."""
        resp = client.post("/api/meetings", json={"title": "VM", "description": "test"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "   ",
            "options": ["A", "B"],
        })
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "INVALID_VOTE_DATA"

    def test_create_vote_duplicate_open_blocked(self, client):
        """SR-004: Creating a second open vote when one already exists returns 409."""
        resp = client.post("/api/meetings", json={"title": "VM", "description": "test"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "First Vote",
            "options": ["Yes", "No"],
        })
        assert resp.status_code == 201

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "Second Vote",
            "options": ["A", "B"],
        })
        assert resp.status_code == 409
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "DUPLICATE_OPEN_VOTE"


class TestGetActiveVote:
    """Tests for GET /api/votes/active"""

    def test_get_active_vote_returns_none_when_no_votes(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.get(f"/api/votes/active?meeting_id={mid}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"] is None

    def test_get_active_vote_returns_active(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        resp = client.get(f"/api/votes/active?meeting_id={mid}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["title"] == "V1"
        assert data["status"] == "open"


class TestGetVoteById:
    """Tests for GET /api/votes/{vote_id}"""

    def test_get_vote_returns_200(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        vid = resp.json()["data"]["id"]

        resp = client.get(f"/api/votes/{vid}")
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == vid

    def test_get_vote_not_found_returns_404(self, client):
        resp = client.get("/api/votes/99999")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "VOTE_NOT_FOUND"


class TestCastVote:
    """Tests for POST /api/votes/{vote_id}/submit"""

    def test_cast_vote_success(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        # Create attendees
        client.post(f"/api/meetings/{mid}/attendees", json={"name": "Alice", "title": "Dev"})
        client.post(f"/api/meetings/{mid}/attendees", json={"name": "Bob", "title": "QA"})

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        vid = resp.json()["data"]["id"]

        resp = client.post(f"/api/votes/{vid}/submit", json={
            "attendee_id": 1, "option": "Yes",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_cast_vote_not_found_returns_404(self, client):
        resp = client.post("/api/votes/99999/submit", json={
            "attendee_id": 1, "option": "Yes",
        })
        assert resp.status_code == 404

    def test_cast_vote_invalid_option_returns_400(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post(f"/api/meetings/{mid}/attendees", json={"name": "Alice", "title": "Dev"})

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        vid = resp.json()["data"]["id"]

        resp = client.post(f"/api/votes/{vid}/submit", json={
            "attendee_id": 1, "option": "Maybe",
        })
        assert resp.status_code == 400


class TestVoteStatistics:
    """Tests for GET /api/votes/{vote_id}/statistics"""

    def test_get_statistics_anonymous(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post(f"/api/meetings/{mid}/attendees", json={"name": "Alice", "title": "Dev"})

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"], "is_anonymous": True,
        })
        vid = resp.json()["data"]["id"]

        client.post(f"/api/votes/{vid}/submit", json={
            "attendee_id": 1, "option": "Yes",
        })

        resp = client.get(f"/api/votes/{vid}/statistics")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["is_anonymous"] is True
        assert data["results"]["Yes"] >= 1

    def test_get_statistics_named(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post(f"/api/meetings/{mid}/attendees", json={"name": "Alice", "title": "Dev"})

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"], "is_anonymous": False,
        })
        vid = resp.json()["data"]["id"]

        client.post(f"/api/votes/{vid}/submit", json={
            "attendee_id": 1, "option": "Yes",
        })

        resp = client.get(f"/api/votes/{vid}/statistics")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["is_anonymous"] is False
        assert 1 in data["results"]["Yes"]

    def test_get_statistics_not_found_returns_404(self, client):
        resp = client.get("/api/votes/99999/statistics")
        assert resp.status_code == 404


class TestCloseVote:
    """Tests for POST /api/votes/{vote_id}/close"""

    def test_close_vote_success(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        vid = resp.json()["data"]["id"]

        resp = client.post(f"/api/votes/{vid}/close")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "closed"

    def test_close_vote_not_found_returns_404(self, client):
        resp = client.post("/api/votes/99999/close")
        assert resp.status_code == 404

    def test_cast_closed_vote_returns_400(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post(f"/api/meetings/{mid}/attendees", json={"name": "Alice", "title": "Dev"})

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        vid = resp.json()["data"]["id"]

        client.post(f"/api/votes/{vid}/close")

        resp = client.post(f"/api/votes/{vid}/submit", json={
            "attendee_id": 1, "option": "Yes",
        })
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "VOTE_CLOSED"

    def test_close_already_closed_returns_400(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        vid = resp.json()["data"]["id"]

        client.post(f"/api/votes/{vid}/close")
        resp = client.post(f"/api/votes/{vid}/close")
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "VOTE_ALREADY_CLOSED"


class TestUnifiedResponseFormat:
    """Verify all vote endpoints use unified response format."""

    def test_success_response_envelope(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/votes", json={
            "meeting_id": mid, "title": "V1",
            "options": ["Yes", "No"],
        })
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "data" in body
        assert body["success"] is True
        assert body["message"] == "OK"

    def test_error_response_envelope(self, client):
        resp = client.get("/api/votes/99999")
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "error_code" in body
        assert "data" in body
        assert body["success"] is False
        assert body["data"] is None

    def test_validation_error_uses_unified_format(self, client):
        """CR-004: Pydantic validation errors must use unified response format."""
        resp = client.post("/api/votes", json={
            "meeting_id": 1,
            "title": "Test",
            "options": ["single"],  # violates min_length=2
        })
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "error_code" in body
        assert "data" in body
        assert body["success"] is False
        assert body["data"] is None
        assert body["error_code"] == "VALIDATION_ERROR"
