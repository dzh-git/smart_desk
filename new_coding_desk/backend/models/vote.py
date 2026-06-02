"""
Vote ORM model — per DATABASE_SCHEMA.md §8.

Repository: VoteRepository.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Index
from backend.database import Base


class Vote(Base):
    __tablename__ = "votes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    title = Column(String(500), nullable=False)
    options_json = Column(Text, default="[]")
    is_anonymous = Column(Boolean, default=False)
    status = Column(String(20), nullable=False, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_votes_meeting_id", "meeting_id"),
        Index("ix_votes_status", "status"),
    )
