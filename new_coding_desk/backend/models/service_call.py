"""
ServiceCall ORM model — per DATABASE_SCHEMA.md §10.

Repository: ServiceCallRepository.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from backend.database import Base


class ServiceCall(Base):
    __tablename__ = "service_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    service_type = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_service_calls_meeting_id", "meeting_id"),
        Index("ix_service_calls_seat_id", "seat_id"),
        Index("ix_service_calls_status", "status"),
    )
