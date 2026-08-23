"""Encrypted, centrally managed face templates and model policy."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text

from backend.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FaceTemplate(Base):
    __tablename__ = "face_templates"

    person_id = Column(String(64), ForeignKey("people.id"), primary_key=True)
    model_version = Column(String(128), nullable=False)
    model_hash = Column(String(64), nullable=False, index=True)
    pipeline_version = Column(Integer, nullable=False)
    embedding_dimension = Column(Integer, nullable=False, default=256)
    normal_sample_count = Column(Integer, nullable=False)
    fill_light_sample_count = Column(Integer, nullable=False)
    encrypted_payload = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class FaceModelPolicy(Base):
    __tablename__ = "face_model_policies"

    model_hash = Column(String(64), primary_key=True)
    model_version = Column(String(128), nullable=False)
    pipeline_version = Column(Integer, nullable=False)
    threshold = Column(Float, nullable=False)
    threshold_status = Column(String(32), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )
