"""Integration tests for service calls router."""
import pytest


pytestmark = pytest.mark.usefixtures("reset_state")


class TestCreateServiceCall:
    """Tests for POST /api/service-calls"""

    def test_create_service_call_returns_201(self, client):
        resp = client.post("/api/meetings", json={"title": "VM", "description": "test"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 3, "service_type": "coffee",
        })
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["seat_id"] == 3
        assert body["data"]["service_type"] == "coffee"
        assert body["data"]["status"] == "pending"

    def test_create_duplicate_pending_returns_409(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 5, "service_type": "water",
        })
        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 5, "service_type": "tea",
        })
        assert resp.status_code == 409
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "SERVICE_CALL_ALREADY_PENDING"

    def test_create_with_custom_text(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 2, "service_type": "other", "custom_text": "Extra napkins please",
        })
        assert resp.status_code == 201
        assert resp.json()["data"]["custom_text"] == "Extra napkins please"


class TestListServiceCalls:
    """Tests for GET /api/service-calls"""

    def test_list_returns_empty(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.get(f"/api/service-calls?meeting_id={mid}")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_list_returns_created_calls(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 1, "service_type": "coffee",
        })
        client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 2, "service_type": "tea",
        })

        resp = client.get(f"/api/service-calls?meeting_id={mid}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2


class TestGetCurrentCall:
    """Tests for GET /api/service-calls/current"""

    def test_current_returns_none_when_no_call(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.get(f"/api/service-calls/current?meeting_id={mid}&seat_id=3")
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    def test_current_returns_pending_call(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 4, "service_type": "tea",
        })

        resp = client.get(f"/api/service-calls/current?meeting_id={mid}&seat_id=4")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["seat_id"] == 4
        assert data["service_type"] == "tea"
        assert data["status"] == "pending"


class TestResolveAndCancel:
    """Tests for POST /api/service-calls/{call_id}/resolve and /cancel"""

    def test_resolve_call_returns_200(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 6, "service_type": "coffee",
        })
        call_id = resp.json()["data"]["id"]

        resp = client.post(f"/api/service-calls/{call_id}/resolve")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "resolved"

    def test_resolve_not_found_returns_404(self, client):
        resp = client.post("/api/service-calls/99999/resolve")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "SERVICE_CALL_NOT_FOUND"

    def test_cancel_call_returns_200(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 7, "service_type": "water",
        })
        call_id = resp.json()["data"]["id"]

        resp = client.post(f"/api/service-calls/{call_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "cancelled"
        assert resp.json()["data"]["cancel_reason"] == "manual"

    def test_cancel_not_found_returns_404(self, client):
        resp = client.post("/api/service-calls/99999/cancel")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "SERVICE_CALL_NOT_FOUND"

    def test_resolve_already_resolved_returns_400(self, client):
        """CR-011: Resolving an already-resolved call returns 400 not 200."""
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 1, "service_type": "coffee",
        })
        call_id = resp.json()["data"]["id"]
        resp = client.post(f"/api/service-calls/{call_id}/resolve")
        assert resp.status_code == 200

        resp = client.post(f"/api/service-calls/{call_id}/resolve")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "SERVICE_CALL_NOT_PENDING"

    def test_cancel_already_cancelled_returns_400(self, client):
        """CR-011: Cancelling an already-cancelled call returns 400 not 200."""
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 2, "service_type": "tea",
        })
        call_id = resp.json()["data"]["id"]
        resp = client.post(f"/api/service-calls/{call_id}/cancel")
        assert resp.status_code == 200

        resp = client.post(f"/api/service-calls/{call_id}/cancel")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "SERVICE_CALL_NOT_PENDING"

    def test_create_after_resolve_allows_new_call(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 8, "service_type": "coffee",
        })
        call_id = resp.json()["data"]["id"]
        client.post(f"/api/service-calls/{call_id}/resolve")

        # Same seat can now create a new call
        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 8, "service_type": "tea",
        })
        assert resp.status_code == 201


class TestUnifiedResponseFormat:
    """Verify all service-call endpoints use unified response format."""

    def test_success_response_envelope(self, client):
        resp = client.post("/api/meetings", json={"title": "VM"})
        mid = resp.json()["data"]["id"]
        client.post(f"/api/meetings/{mid}/start")

        resp = client.post("/api/service-calls", params={"meeting_id": mid}, json={
            "seat_id": 9, "service_type": "coffee",
        })
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "data" in body
        assert body["success"] is True
        assert body["message"] == "OK"

    def test_error_response_envelope(self, client):
        resp = client.post("/api/service-calls/99999/resolve")
        body = resp.json()
        assert "success" in body
        assert "message" in body
        assert "error_code" in body
        assert "data" in body
        assert body["success"] is False
        assert body["data"] is None
