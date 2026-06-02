"""
TranslationRecord ORM model — per DATABASE_SCHEMA.md §11.

Repository: TranslationRepository.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from backend.database import Base


class TranslationRecord(Base):
    __tablename__ = "translation_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_id = Column(Integer, ForeignKey("meetings.id"), nullable=False)
    seat_id = Column(Integer, nullable=False)
    source_lang = Column(String(10), nullable=False, default="auto")
    target_lang = Column(String(10), nullable=False, default="auto")
    source_text = Column(Text, nullable=False, default="")
    translated_text = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_translation_records_meeting_id", "meeting_id"),
        Index("ix_translation_records_seat_id", "seat_id"),
    )
