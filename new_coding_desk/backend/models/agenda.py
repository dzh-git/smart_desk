"""
Agenda ORM model — per DATABASE_SCHEMA.md §4.

Repository: MeetingRepository.
"""
from __future__ import annotations

from sqlalchemy import Column, Integer, String, ForeignKey, Index
from backend.database import Base


class Agenda(Base):
    __tablename__ = "agendas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    title = Column(String(500), nullable=False)
    sort_order = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_agendas_meeting_id", "meeting_id"),
    )
