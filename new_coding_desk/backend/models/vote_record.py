"""
VoteRecord ORM model — per DATABASE_SCHEMA.md §9.

Repository: VoteRepository.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, Index
from backend.database import Base


class VoteRecord(Base):
    __tablename__ = "vote_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(Integer, ForeignKey("votes.id"), nullable=False)
    attendee_id = Column(Integer, ForeignKey("attendees.id"), nullable=False)
    option = Column(String(200), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("vote_id", "attendee_id", name="uq_vote_attendee"),
        Index("ix_vote_records_vote_id", "vote_id"),
    )
