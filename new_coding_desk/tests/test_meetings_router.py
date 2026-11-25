"""Integration tests for meeting discovery and attendee lifecycle guards."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models.meeting import Meeting
from tests.conftest import TestSessionLocal

client = TestClient(app)


def test_pending_lookup_filters_history_before_selecting_latest_meetings():
    with TestSessionLocal() as db:
        db.add_all([Meeting(title="Past meeting", status="finished") for _ in range(200)])
        db.commit()

    earlier = client.post("/api/meetings", json={"title": "Earlier draft"})
    latest = client.post("/api/meetings", json={"title": "Latest draft"})
    assert earlier.status_code == latest.status_code == 201

    response = client.get("/api/meetings", params={"status": "pending"})

    assert response.status_code == 200
    assert [meeting["id"] for meeting in response.json()["data"]] == [
        latest.json()["data"]["id"],
        earlier.json()["data"]["id"],
    ]


@pytest.mark.parametrize("method", ["POST", "DELETE"])
def test_finished_meeting_keeps_roster_readable_and_blocks_writes(method):
    meeting = client.post("/api/meetings", json={"title": "Read-only roster"})
    assert meeting.status_code == 201
    meeting_id = meeting.json()["data"]["id"]
    roster_url = f"/api/meetings/{meeting_id}/attendees"
    attendee = client.post(roster_url, json={"name": "Alice"})
    assert attendee.status_code == 200
    attendee_id = attendee.json()["data"]["id"]
    assert client.post(f"/api/meetings/{meeting_id}/start").status_code == 200
    assert client.post(f"/api/meetings/{meeting_id}/end").status_code == 200

    if method == "POST":
        response = client.post(roster_url, json={"name": "Bob"})
    else:
        response = client.delete(f"{roster_url}/{attendee_id}")

    assert response.status_code == 400
    assert response.json()["error_code"] == "MEETING_FINISHED"
    roster = client.get(roster_url)
    assert roster.status_code == 200
    assert roster.json()["data"] == [attendee.json()["data"]]
