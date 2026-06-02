from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from backend.database import Base
from backend.repositories.meeting_repository import MeetingRepository


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
