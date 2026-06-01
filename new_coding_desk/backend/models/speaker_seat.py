"""
SpeakerSeat ORM model — per DATABASE_SCHEMA.md §7.

Repository: SeatRepository.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, DateTime
from backend.database import Base


class SpeakerSeat(Base):
    __tablename__ = "speaker_seat"

    id = Column(Integer, primary_key=True, default=1)
    seat_id = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)
