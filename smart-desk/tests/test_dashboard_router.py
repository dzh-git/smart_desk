"""Integration tests for dashboard router (Task 015)."""

import pytest

pytestmark = pytest.mark.usefixtures("reset_state")


def test_get_dashboard(client):
    """GET /api/dashboard?meeting_id=N should return dashboard data with success envelope."""
    resp = client.get("/api/dashboard?meeting_id=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message"] == "OK"
    data = body["data"]
    assert "meeting" in data
    assert "speaker_seat" in data
    assert "active_vote" in data
    assert "pending_service_calls" in data
    assert "seats" in data


def test_get_dashboard_missing_param(client):
    """GET /api/dashboard without meeting_id should return 422."""
    resp = client.get("/api/dashboard")
    assert resp.status_code == 422


def test_get_dashboard_nonexistent_meeting_returns_404(client):
    """CR-011: GET /api/dashboard?meeting_id=99999 should return 404 for nonexistent meeting."""
    resp = client.get("/api/dashboard?meeting_id=99999")
    assert resp.status_code == 404
