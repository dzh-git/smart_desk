"""Integration tests for vote router endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import Base
from backend.models.vote import Vote
from tests.conftest import TEST_ENGINE, TestSessionLocal

client = TestClient(app)


def _create_meeting() -> int:
    """Create and start a meeting, return meeting_id."""
    resp = client.post("/api/meetings", json={"title": "Test Meeting", "description": "test"})
    assert resp.status_code == 201, f"Create meeting failed: {resp.json()}"
    mid = resp.json()["data"]["id"]
    client.post(f"/api/meetings/{mid}/start")
    return mid


@pytest.fixture
def legacy_open_vote():
    """Older releases let clients open new votes after a meeting ended."""
    mid = _create_meeting()
    attendee = client.post(f"/api/meetings/{mid}/attendees", json={"name": "Alice"})
    assert attendee.status_code == 200
    attendee_id = attendee.json()["data"]["id"]
    assert client.post(f"/api/meetings/{mid}/end").status_code == 200
    with TestSessionLocal() as db:
        vote = Vote(
            meeting_id=mid,
            title="Late vote",
            options_json='["Yes", "No"]',
            status="open",
        )
        db.add(vote)
        db.commit()
        return vote.id, attendee_id


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


def test_legacy_open_vote_does_not_block_a_new_meeting_vote(legacy_open_vote):
    vote_id, _ = legacy_open_vote
    assert client.get("/api/votes/active").json()["data"] is None
    mid = _create_meeting()

    response = client.post("/api/votes", json={
        "meeting_id": mid,
        "title": "Current decision",
        "options": ["Yes", "No"],
    })

    assert response.status_code == 201
    assert client.post(f"/api/meetings/{mid}/end").status_code == 200
    assert client.get("/api/votes/active").json()["data"] is None
    past = client.get(f"/api/votes/{vote_id}")
    assert past.status_code == 200
    assert past.json()["data"]["status"] == "open"


@pytest.mark.parametrize("action", ["submit", "close"])
def test_legacy_open_vote_in_finished_meeting_is_read_only(legacy_open_vote, action):
    vote_id, attendee_id = legacy_open_vote
    vote_url = f"/api/votes/{vote_id}"
    ballot = {"attendee_id": attendee_id, "option": "Yes"} if action == "submit" else None

    response = client.post(f"{vote_url}/{action}", json=ballot)

    assert response.status_code == 400
    assert response.json()["detail"] == "MEETING_FINISHED"
    stats = client.get(f"{vote_url}/statistics").json()["data"]
    assert stats["total_votes"] == 0
    assert stats["status"] == "open"


def test_list_votes_by_meeting_includes_closed_vote():
    """GET /api/votes?meeting_id= returns closed vote history."""
    mid = _create_meeting()
    resp = client.post("/api/votes", json={
        "meeting_id": mid, "title": "Historical Vote",
        "options": ["Yes", "No"], "is_anonymous": False
    })
    vid = resp.json()["data"]["id"]
    client.post(f"/api/votes/{vid}/submit", json={
        "attendee_id": 1, "option": "Yes",
    })
    client.post(f"/api/votes/{vid}/close")

    resp = client.get(f"/api/votes?meeting_id={mid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"][0]["id"] == vid
    assert body["data"][0]["status"] == "closed"

    stats_resp = client.get(f"/api/votes/{vid}/statistics")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()["data"]
    assert stats["status"] == "closed"
    assert stats["total_votes"] == 1


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


def test_finished_meeting_cannot_open_a_vote():
    mid = _create_meeting()
    assert client.post(f"/api/meetings/{mid}/end").status_code == 200

    response = client.post("/api/votes", json={
        "meeting_id": mid,
        "title": "Too late",
        "options": ["Yes", "No"],
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "MEETING_FINISHED"
    assert client.get("/api/votes/active").json()["data"] is None


def test_attendee_with_vote_history_cannot_be_deleted():
    mid = _create_meeting()
    roster_url = f"/api/meetings/{mid}/attendees"
    attendee = client.post(roster_url, json={"name": "Alice"})
    assert attendee.status_code == 200
    attendee_id = attendee.json()["data"]["id"]
    vote = client.post("/api/votes", json={
        "meeting_id": mid,
        "title": "Decision",
        "options": ["Yes", "No"],
    })
    assert vote.status_code == 201
    vote_id = vote.json()["data"]["id"]
    assert client.post(f"/api/votes/{vote_id}/submit", json={
        "attendee_id": attendee_id,
        "option": "Yes",
    }).status_code == 200

    deleted = client.delete(f"{roster_url}/{attendee_id}")

    assert deleted.status_code == 409
    assert deleted.json()["error_code"] == "ATTENDEE_HAS_HISTORY"
    assert client.get(roster_url).json()["data"][0]["id"] == attendee_id


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
