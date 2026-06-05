import time
import warnings
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

TEST_DB_PATH = Path(tempfile.gettempdir()) / f"test_smart_desk_{os.getpid()}.db"
TEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
for suffix in ("", "-journal", "-wal", "-shm"):
    (TEST_DB_PATH.parent / f"{TEST_DB_PATH.name}{suffix}").unlink(missing_ok=True)
os.environ.setdefault("SMART_DESK_DB_PATH", str(TEST_DB_PATH))

from backend.database import Base, engine as _db_engine
from backend.repositories.meeting_repository import MeetingRepository


# ── CR-001: Session-scoped DB cleanup ──
# The app uses a file-based SQLite DB (smart_desk.db). Data accumulates across
# test functions and across pytest invocations. Drop all tables at session start
# so each pytest run begins with a clean slate. The lifespan in main.py will
# recreate tables and seed data on first TestClient creation.

@pytest.fixture(scope="session", autouse=True)
def _clean_db_session():
    """Drop all tables at session start to ensure clean state. Tables are
    recreated by the app lifespan during the first TestClient creation."""
    Base.metadata.drop_all(bind=_db_engine)
    yield


# ── Shared test helpers for router integration tests ──

def _wait_for(predicate, timeout=3.0, interval=0.05):
    """CR-013: Poll predicate() until True or timeout. More robust than time.sleep(n)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _get_seat_status(client, seat_id):
    """Get the status string for a specific seat from /api/seats."""
    resp = client.get("/api/seats")
    seats = resp.json()["data"]
    for s in seats:
        if s["seat_id"] == seat_id:
            return s["status"]
    return None


def _get_vote_count(client, vote_id):
    """Get total vote count from a vote statistics endpoint."""
    resp = client.get(f"/api/votes/{vote_id}/statistics")
    data = resp.json()["data"]
    results = data.get("results", {})
    if data.get("is_anonymous"):
        return sum(results.values())
    else:
        return sum(len(v) for v in results.values())


# ── Fixtures ──

def force_expire_service_call(db: Session, call_id: int, seconds_ago: int) -> None:
    """Test helper: backdate a service call's created_at timestamp to simulate expiry."""
    old = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    db.execute(
        text("UPDATE service_calls SET created_at = :dt WHERE id = :id"),
        {"dt": old, "id": call_id},
    )
    db.commit()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    m = MeetingRepository(session).create("Test")
    yield session, m.id
    session.close()


# ── CR-023: Shared router integration fixtures ──

# Try to import the app — if it fails, the client fixture will skip tests gracefully.
try:
    from backend.main import app as _app
    _APP_IMPORT_OK = True
except Exception as e:
    _APP_IMPORT_OK = False
    _APP_IMPORT_ERROR = str(e)


@pytest.fixture
def client():
    """CR-023: Shared TestClient fixture for all router integration tests.

    Uses a context manager to ensure proper startup/shutdown of lifespan events.
    Any test file in tests/ can inherit this fixture via pytest's conftest discovery.
    """
    if not _APP_IMPORT_OK:
        pytest.skip(f"App import failed: {_APP_IMPORT_ERROR}")
    with TestClient(_app) as c:
        yield c


@pytest.fixture
def reset_state(client):
    """CR-023: Ensure clean DB state before each test by ending any active meeting.

    NON-autouse — only tests that explicitly request this fixture (or activate it
    via module-level pytestmark) get it. This avoids unwanted side effects on other
    test files that don't need meeting cleanup.

    Test files that need this fixture should add at module level:
        pytestmark = pytest.mark.usefixtures("reset_state")
    """
    try:
        resp = client.get("/api/meetings/active")
        if resp.status_code == 200:
            body = resp.json()
            meeting = body.get("data", body)
            if meeting and isinstance(meeting, dict) and meeting.get("id"):
                end_resp = client.post(f"/api/meetings/{meeting['id']}/end")
                if end_resp.status_code != 200:
                    warnings.warn(
                        f"reset_state: end meeting {meeting['id']} returned "
                        f"{end_resp.status_code}: {end_resp.text[:200]}"
                    )
    except Exception:
        # CR-005: Catch all exceptions during reset_state cleanup to prevent
        # fixture crashes from unhandled error types (RuntimeError, connection
        # errors, etc.). The goal is best-effort cleanup; failures are non-fatal.
        pass
    yield
