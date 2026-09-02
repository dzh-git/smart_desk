"""
Shared test fixtures — replaces the production database with an in-memory
SQLite database so tests never touch smart_desk.db.

Strategy (Phase 04 review fix):
    1. Module-level code creates a test engine + SessionLocal for an in-memory
       database. This runs BEFORE any test file is imported.
    2. Overrides `backend.database.engine` / `backend.database.SessionLocal`
       so every subsequent import gets the test versions.
    3. Imports `backend.main` (triggering FastAPI app creation) and overrides
       `backend.main.engine` / `backend.main.SessionLocal` so the lifespan
       handler also uses the test database.
    4. Overrides the `get_db` FastAPI dependency so HTTP request sessions
       use the test database.
    5. An autuse function-scoped fixture (`_reset_db`) drops/recreates tables
       and re-seeds seat_states before each test.

Legacy fixtures from Phase 01 (used by service-level tests):
    - `engine`     → per-function in-memory SQLite engine
    - `db`         → per-function session
    - `seeded_db`  → db with seat_states seeded
    - `event_bus`  → fresh EventBus per test
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# ── Override the production database BEFORE any test module imports it ──────

import tempfile
import os

import backend.database as db_module

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Use a temporary file so all connections share the same database.
# :memory: creates a separate DB per connection, which breaks the
# _override_get_db → HTTP request flow.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".test.db", delete=False)
_tmp_db_path = _tmp_db.name
_tmp_db.close()

TEST_ENGINE = create_engine(
    f"sqlite:///{_tmp_db_path}",
    connect_args={"check_same_thread": False},
)
TestSessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=TEST_ENGINE,
)

# Replace production module-level singletons
db_module.engine = TEST_ENGINE
db_module.SessionLocal = TestSessionLocal

# ── Import backend.main AFTER the database override ─────────────────────────
# This ensures backend.main.engine and backend.main.SessionLocal are set from
# the already-overridden backend.database module.

import backend.main as main_module
from backend.main import app
from backend.database import Base, get_db

# Belt-and-suspenders: also override main's references
main_module.engine = TEST_ENGINE
main_module.SessionLocal = TestSessionLocal

# ── Override the get_db FastAPI dependency ──────────────────────────────────


def _override_get_db() -> Generator[Session, None, None]:
    """Yield a session from the test database."""
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db

# ── Autouse fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="function", autouse=True)
def _reset_db(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Drop and recreate all tables, re-seed seat_states, before each test.

    Operates exclusively on TEST_ENGINE — never touches smart_desk.db.
    """
    from backend.repositories.seat_repository import SeatRepository

    Base.metadata.create_all(bind=TEST_ENGINE)
    db = TestSessionLocal()
    try:
        SeatRepository.init_seats(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    yield

    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)


# ── Legacy fixtures (used by service-level tests) ────────────────────────────


@pytest.fixture(scope="function")
def engine():
    """In-memory SQLite engine — fresh per test (for service-level tests)."""
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture(scope="function")
def db(engine):
    """Transaction-per-test session."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="function")
def seeded_db(db):
    """DB session with seat_states (1..9) and speaker_seat seeded."""
    from backend.repositories.seat_repository import SeatRepository
    SeatRepository.init_seats(db)
    return db


@pytest.fixture(scope="function")
def event_bus():
    """Fresh EventBus per test with auto-cleanup."""
    from backend.events.event_bus import EventBus
    bus = EventBus()
    yield bus
    bus._subscribers.clear()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Use asyncio backend for anyio-marked async tests (trio not installed)."""
    return "asyncio"


def pytest_sessionfinish(session: pytest.Session) -> None:  # type: ignore[arg-type]
    """Remove the temp test database file after all tests complete."""
    try:
        os.unlink(_tmp_db_path)
    except OSError:
        pass
