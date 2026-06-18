"""
Agenda ORM model — per DATABASE_SCHEMA.md §4.

Phase 1 extensions:
    - status (pending|active|completed|skipped)
    - started_at, completed_at, skipped_at timestamps

Repository: MeetingRepository.
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index
from backend.database import Base


class Agenda(Base):
    __tablename__ = "agendas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    title = Column(String(500), nullable=False)
    sort_order = Column(Integer, default=0)

    # Phase 1: agenda state machine fields
    status = Column(String(20), default="pending", nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    skipped_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_agendas_meeting_id", "meeting_id"),
    )
