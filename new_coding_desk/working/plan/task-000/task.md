# Task 000: Pre-Implementation Black-Box Integration Tests (Red Phase)

## Project Overview

- **Goal:** Migrate SmartDesk from direct callback architecture to EventBus-driven decoupled architecture
- **Architecture:** Router → Service → Repository → SQLite, with in-process EventBus for decoupling
- **Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0, SQLite, WebSocket

## Task Objective

Write the full-system black-box integration tests BEFORE any implementation code. These tests will FAIL initially (red phase of TDD) because none of the new Service/Repository/EventBus infrastructure exists yet. They exercise the full meeting lifecycle through HTTP API endpoints and verify unified response format. Task 024 will later run these same tests and fix bugs discovered.

**IMPORTANT:** This task ONLY writes the failing tests. Do NOT implement any production code here. The tests must fail on first run due to missing imports, modules, and endpoints.

This is Task 0 of 26.

---

**Files:**
- Create: `D:\learning\smart_desktop\smart-desk\tests\test_integration.py`

- [ ] **Step 1: Write the black-box integration test — full meeting lifecycle**

```python
# tests/test_integration.py
"""Black-box integration tests: full meeting lifecycle through HTTP API.
These tests MUST FAIL initially — they exercise endpoints and services
that do not yet exist. This is the RED phase of TDD."""

import pytest
from fastapi.testclient import TestClient


# Attempt to import app — will fail early if backend can't start
try:
    from backend.main import app
    _APP_IMPORT_OK = True
except Exception as e:
    _APP_IMPORT_OK = False
    _APP_IMPORT_ERROR = str(e)


@pytest.fixture
def client():
    """Create TestClient. Fails early if app cannot be imported."""
    if not _APP_IMPORT_OK:
        pytest.skip(f"App import failed (expected in red phase): {_APP_IMPORT_ERROR}")
    return TestClient(app)


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

        # Create meeting must reject if active meeting exists
        resp2 = client.post("/api/meetings", json={"title": "Second"})
        assert resp2.status_code == 400  # ACTIVE_MEETING_EXISTS not yet triggered since not started

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
        client.post(f"/api/meetings/{mid}/start")

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
        client.post("/api/debug/simulate/3?action=occupied")

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
        client.post(f"/api/meetings/{mid}/start")
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
        client.post(f"/api/meetings/{mid}/start")

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
        client.post(f"/api/meetings/{mid}/start")

        # Add attendee + checkin + set speaker
        resp = client.post(f"/api/meetings/{mid}/attendees", json={
            "name": "User", "seat_id": 3
        })
        aid = resp.json()["data"]["id"]
        client.post(f"/api/seats/3/checkin", json={"attendee_id": aid})
        client.post("/api/seats/speaker", json={"seat_id": 3})

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

        # Verify seats reset
        resp = client.get("/api/seats")
        for seat in resp.json()["data"]:
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
        client.post(f"/api/meetings/{mid}/start")

        # Preload status
        resp = client.get("/api/translations/preload/status")
        assert resp.status_code == 200
        assert "ready" in resp.json()["data"]

        # History (empty)
        resp = client.get(f"/api/translations?meeting_id={mid}")
        assert resp.status_code == 200
        assert isinstance(resp.json()["data"], list)

    def test_unified_response_format(self, client):
        """All endpoints return {"success": bool, "message": str, "data": ...}"""
        endpoints = [
            ("GET", "/api/meetings/active"),
            ("GET", "/api/seats"),
            ("GET", "/api/seats/speaker"),
        ]
        for method, path in endpoints:
            resp = client.get(path)
            data = resp.json()
            assert "success" in data, f"{path}: missing 'success'"
            assert "message" in data, f"{path}: missing 'message'"
            assert "data" in data, f"{path}: missing 'data'"
```

- [ ] **Step 2: Run the tests — EXPECT FAILURE (Red Phase)**

```bash
cd D:\learning\smart_desktop\smart-desk && pytest tests/test_integration.py -v --tb=short 2>&1
```

Expected: All tests FAIL. Failures may include:
- ImportError (modules not created yet)
- 404 (endpoints not registered yet)
- AttributeError (schemas not defined yet)
- AssertionError (unified response format not implemented)

**Document the failure output** — this is the baseline that subsequent tasks will fix. The tests should all pass by Task 024.
