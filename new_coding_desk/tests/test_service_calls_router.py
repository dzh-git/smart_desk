"""Integration tests for service call router endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base
from tests.conftest import TEST_ENGINE, TestSessionLocal

client = TestClient(app)


def _create_meeting() -> int:
    """Create and start a meeting, return meeting_id."""
    resp = client.post("/api/meetings", json={"title": "SC Meeting", "description": "test"})
    assert resp.status_code == 201, f"Create meeting failed: {resp.json()}"
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")
    return mid


# ── POST /api/service-calls ─────────────────────────────────────────────────


def test_create_service_call():
    """POST /api/service-calls creates a call and returns 201 with unified format."""
    mid = _create_meeting()
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3,
        "service_type": "coffee",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["seat_id"] == 3
    assert body["data"]["service_type"] == "coffee"
    assert body["data"]["status"] == "pending"


def test_finished_meeting_cannot_create_a_service_call():
    mid = _create_meeting()
    assert client.post(f"/api/meetings/{mid}/end").status_code == 200
    url = f"/api/service-calls?meeting_id={mid}"

    response = client.post(url, json={"seat_id": 3, "service_type": "coffee"})

    assert response.status_code == 400
    assert response.json()["detail"] == "MEETING_FINISHED"
    assert client.get(url).json()["data"] == []


@pytest.mark.parametrize("action", ["resolve", "cancel"])
def test_finished_meeting_preserves_pending_service_call_history(action):
    mid = _create_meeting()
    url = f"/api/service-calls?meeting_id={mid}"
    call = client.post(url, json={"seat_id": 3, "service_type": "coffee"})
    assert call.status_code == 201
    call_id = call.json()["data"]["id"]
    assert client.post(f"/api/meetings/{mid}/end").status_code == 200

    response = client.post(f"/api/service-calls/{call_id}/{action}")

    assert response.status_code == 400
    assert response.json()["detail"] == "MEETING_FINISHED"
    assert client.get(url).json()["data"] == [call.json()["data"]]


def test_create_service_call_duplicate_blocked():
    """POST /api/service-calls returns 409 if seat already has pending call."""
    mid = _create_meeting()
    client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "coffee",
    })
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "water",
    })
    assert resp.status_code == 409


def test_create_service_call_invalid_type():
    """POST /api/service-calls with invalid service_type returns validation error."""
    mid = _create_meeting()
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "pizza",
    })
    assert resp.status_code in (400, 422)


# ── GET /api/service-calls ──────────────────────────────────────────────────


def test_list_service_calls():
    """GET /api/service-calls returns list of calls for a meeting."""
    mid = _create_meeting()
    client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 1, "service_type": "tea",
    })
    client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "coffee",
    })

    resp = client.get(f"/api/service-calls?meeting_id={mid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["data"]) == 2


def test_list_service_calls_empty():
    """GET /api/service-calls returns empty list when no calls."""
    mid = _create_meeting()
    resp = client.get(f"/api/service-calls?meeting_id={mid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []


# ── GET /api/service-calls/current ──────────────────────────────────────────


def test_get_current_call_exists():
    """GET /api/service-calls/current returns pending call for a seat."""
    mid = _create_meeting()
    client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 5, "service_type": "water",
    })

    resp = client.get(f"/api/service-calls/current?meeting_id={mid}&seat_id=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] is not None
    assert body["data"]["seat_id"] == 5


def test_get_current_call_none():
    """GET /api/service-calls/current returns null when no pending call."""
    mid = _create_meeting()
    resp = client.get(f"/api/service-calls/current?meeting_id={mid}&seat_id=5")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] is None


# ── POST /api/service-calls/{call_id}/resolve ───────────────────────────────


def test_resolve_call():
    """POST /api/service-calls/{id}/resolve resolves a pending call."""
    mid = _create_meeting()
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "coffee",
    })
    cid = resp.json()["data"]["id"]

    resp = client.post(f"/api/service-calls/{cid}/resolve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "resolved"


def test_resolve_call_not_found():
    """POST /api/service-calls/999/resolve returns 404."""
    resp = client.post("/api/service-calls/999/resolve")
    assert resp.status_code == 404


def test_resolve_already_resolved():
    """POST /api/service-calls/{id}/resolve on already resolved returns 400."""
    mid = _create_meeting()
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "coffee",
    })
    cid = resp.json()["data"]["id"]
    client.post(f"/api/service-calls/{cid}/resolve")

    resp = client.post(f"/api/service-calls/{cid}/resolve")
    assert resp.status_code == 400


# ── POST /api/service-calls/{call_id}/cancel ────────────────────────────────


def test_cancel_call():
    """POST /api/service-calls/{id}/cancel cancels a pending call."""
    mid = _create_meeting()
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "coffee",
    })
    cid = resp.json()["data"]["id"]

    resp = client.post(f"/api/service-calls/{cid}/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "cancelled"


def test_cancel_call_not_found():
    """POST /api/service-calls/999/cancel returns 404."""
    resp = client.post("/api/service-calls/999/cancel")
    assert resp.status_code == 404


def test_cancel_already_cancelled():
    """POST /api/service-calls/{id}/cancel on already cancelled returns 400."""
    mid = _create_meeting()
    resp = client.post(f"/api/service-calls?meeting_id={mid}", json={
        "seat_id": 3, "service_type": "coffee",
    })
    cid = resp.json()["data"]["id"]
    client.post(f"/api/service-calls/{cid}/cancel")

    resp = client.post(f"/api/service-calls/{cid}/cancel")
    assert resp.status_code == 400
