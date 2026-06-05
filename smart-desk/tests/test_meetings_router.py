# tests/test_meetings_router.py
"""Integration tests for meetings and attendees router endpoints."""

import pytest

# CR-023: Shared client and reset_state fixtures are in tests/conftest.py.
# Activate reset_state (non-autouse) for all tests in this file.
pytestmark = pytest.mark.usefixtures("reset_state")


def test_list_meetings(client):
    resp = client.get("/api/meetings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_create_and_get_meeting(client):
    resp = client.post("/api/meetings", json={"title": "Test", "description": "Desc"})
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    resp2 = client.get(f"/api/meetings/{mid}")
    assert resp2.json()["data"]["title"] == "Test"


def test_start_and_end_meeting(client):
    resp = client.post("/api/meetings", json={"title": "Test"})
    mid = resp.json()["data"]["id"]
    resp2 = client.post(f"/api/meetings/{mid}/start")
    assert resp2.json()["data"]["status"] == "active"
    resp3 = client.post(f"/api/meetings/{mid}/end")
    assert resp3.json()["data"]["status"] == "finished"


def test_active_meeting(client):
    resp = client.get("/api/meetings/active")
    assert resp.status_code == 200
