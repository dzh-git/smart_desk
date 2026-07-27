"""
Attendee ORM model — per DATABASE_SCHEMA.md §5.

Repository: AttendeeRepository.
"""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from backend.database import Base


class Attendee(Base):
    __tablename__ = "attendees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    person_id = Column(String(64), ForeignKey("people.id"), nullable=True)
    name = Column(String(100), nullable=False)
    title = Column(String(100), default="")
    seat_id = Column(Integer, nullable=True)
    checked_in = Column(Boolean, default=False)

    __table_args__ = (
        Index("ix_attendees_meeting_id", "meeting_id"),
        Index("ix_attendees_seat_id", "seat_id"),
        Index("ix_attendees_person_id", "person_id"),
        UniqueConstraint(
            "meeting_id",
            "person_id",
            name="uq_attendees_meeting_person",
        ),
    )
