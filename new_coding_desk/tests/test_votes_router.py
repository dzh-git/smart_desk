"""Integration tests for vote router endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base
from tests.conftest import TEST_ENGINE, TestSessionLocal

client = TestClient(app)


def _create_meeting() -> int:
    """Create and start a meeting, return meeting_id."""
    resp = client.post("/api/meetings", json={"title": "Test Meeting", "description": "test"})
    assert resp.status_code == 201, f"Create meeting failed: {resp.json()}"
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")
    return mid


# ── GET /api/votes/active ────────────────────────────────────────────────────


def test_get_active_vote_empty():
    """GET /api/votes/active returns null data when no vote exists."""
    resp = client.get("/api/votes/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] is None


def test_get_active_vote_with_vote():
    """GET /api/votes/active returns active vote after creation."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Active Vote",
        "options": ["Yes", "No"], "is_anonymous": False
    })
    assert resp.status_code == 201
    vid = resp.json()["data"]["id"]

    resp = client.get("/api/votes/active")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == vid


# ── POST /api/votes ──────────────────────────────────────────────────────────


def test_create_vote():
    """POST /api/votes creates a vote and returns 201."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid,
        "title": "Test Vote",
        "options": ["Yes", "No"],
        "is_anonymous": False,
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["title"] == "Test Vote"
    assert body["data"]["options"] == ["Yes", "No"]
    assert body["data"]["status"] == "open"


def test_create_vote_empty_title_blocked():
    """POST /api/votes with empty title returns 400."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid,
        "title": "",
        "options": ["Yes", "No"],
    })
    assert resp.status_code == 400


def test_create_vote_duplicate_open_blocked():
    """POST /api/votes when open vote exists returns 409."""
    mid = _create_meeting()
    client.post("/api/votes", json={
        "meeting_id": mid, "title": "First",
        "options": ["A", "B"],
    })
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Second",
        "options": ["C", "D"],
    })
    assert resp.status_code == 409


# ── GET /api/votes/{vote_id} ─────────────────────────────────────────────────


def test_get_vote():
    """GET /api/votes/{id} returns vote details."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Detail",
        "options": ["A", "B"],
    })
    vid = resp.json()["data"]["id"]

    resp = client.get(f"/api/votes/{vid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["id"] == vid


def test_get_vote_not_found():
    """GET /api/votes/999 returns 404."""
    resp = client.get("/api/votes/999")
    assert resp.status_code == 404


# ── POST /api/votes/{vote_id}/submit ─────────────────────────────────────────


def test_cast_vote():
    """POST /api/votes/{id}/submit casts a ballot."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Ballot",
        "options": ["Yes", "No"],
    })
    vid = resp.json()["data"]["id"]

    resp = client.post(f"/api/votes/{vid}/submit", json={
        "attendee_id": 1, "option": "Yes",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


def test_cast_vote_closed():
    """POST /api/votes/{id}/submit on closed vote returns 400."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "CloseMe",
        "options": ["A", "B"],
    })
    vid = resp.json()["data"]["id"]
    client.post(f"/api/votes/{vid}/close")

    resp = client.post(f"/api/votes/{vid}/submit", json={
        "attendee_id": 1, "option": "A",
    })
    assert resp.status_code == 400


def test_cast_vote_not_found():
    """POST /api/votes/999/submit returns 404."""
    resp = client.post("/api/votes/999/submit", json={
        "attendee_id": 1, "option": "A",
    })
    assert resp.status_code == 404


# ── GET /api/votes/{vote_id}/statistics ───────────────────────────────────────


def test_get_vote_statistics():
    """GET /api/votes/{id}/statistics returns vote results."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Stats",
        "options": ["Yes", "No"], "is_anonymous": False,
    })
    vid = resp.json()["data"]["id"]
    client.post(f"/api/votes/{vid}/submit", json={
        "attendee_id": 1, "option": "Yes",
    })

    resp = client.get(f"/api/votes/{vid}/statistics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["vote_id"] == vid
    assert body["data"]["total_votes"] == 1


def test_get_vote_statistics_not_found():
    """GET /api/votes/999/statistics returns 404."""
    resp = client.get("/api/votes/999/statistics")
    assert resp.status_code == 404


# ── POST /api/votes/{vote_id}/close ──────────────────────────────────────────


def test_close_vote():
    """POST /api/votes/{id}/close closes the vote."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Close",
        "options": ["A", "B"],
    })
    vid = resp.json()["data"]["id"]

    resp = client.post(f"/api/votes/{vid}/close")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "closed"


def test_close_vote_not_found():
    """POST /api/votes/999/close returns 404."""
    resp = client.post("/api/votes/999/close")
    assert resp.status_code == 404
