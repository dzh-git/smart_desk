"""
Service Call module — Request/Response DTOs.

Per API_SPEC §9:
    ServiceCallCreate, ServiceCallResponse.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ── Request ──────────────────────────────────────────────────────────────────


class ServiceCallCreate(BaseModel):
    """POST /api/service-calls request body."""
    meeting_id: int
    seat_id: int
    service_type: Literal["coffee", "tea", "water", "other"]


# ── Response ─────────────────────────────────────────────────────────────────


class ServiceCallResponse(BaseModel):
    """Service call data returned to clients."""
    id: int
    meeting_id: int
    seat_id: int
    service_type: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}
