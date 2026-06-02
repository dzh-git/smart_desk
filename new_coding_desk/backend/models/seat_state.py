"""
SeatState ORM model — per DATABASE_SCHEMA.md §6.

Repository: SeatRepository.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Index
from backend.database import Base


class SeatState(Base):
    __tablename__ = "seat_states"

    seat_id = Column(Integer, primary_key=True)
    status = Column(String(20), nullable=False, default="vacant")
    attendee_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_seat_states_status", "status"),
    )
