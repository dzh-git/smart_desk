"""Durable identity event idempotency record."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String

from backend.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IdentityCheckInEvent(Base):
    __tablename__ = "identity_checkin_events"

    event_id = Column(String(64), primary_key=True)
    device_id = Column(
        String(64),
        ForeignKey("tablet_devices.id"),
        nullable=False,
        index=True,
    )
    seat_id = Column(Integer, nullable=False)
    person_id = Column(
        String(64),
        ForeignKey("people.id"),
        nullable=False,
        index=True,
    )
    attendee_id = Column(
        Integer,
        ForeignKey("attendees.id"),
        nullable=False,
    )
    similarity = Column(Float, nullable=False)
    verification_level = Column(String(32), nullable=False)
    model_version = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
