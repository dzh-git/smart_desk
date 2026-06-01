"""Shared test fixtures for SmartDesk backend tests."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from backend.database import Base
from backend.events.event_bus import EventBus
from backend.repositories.seat_repository import SeatRepository


# ── Database ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def engine():
    """In-memory SQLite engine — fresh per test."""
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
    """DB session with seat_states (1..10) and speaker_seat seeded."""
    SeatRepository.init_seats(db)
    return db


# ── EventBus ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def event_bus():
    """Fresh EventBus per test with auto-cleanup."""
    bus = EventBus()
    yield bus
    # Clear all subscribers
    bus._subscribers.clear()
