"""
Vote module — Request/Response DTOs.

Per API_SPEC §8:
    VoteCreate, VoteSubmit, VoteResponse, VoteStatistics.
"""
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field


# ── Request ──────────────────────────────────────────────────────────────────


class VoteCreate(BaseModel):
    """POST /api/votes request body."""
    meeting_id: int
    title: str = Field(..., min_length=1, max_length=500)
    options: list[str] = Field(..., min_length=2)
    is_anonymous: bool = False


class VoteSubmit(BaseModel):
    """POST /api/votes/{vote_id}/submit request body."""
    attendee_id: int
    option: str = Field(..., min_length=1, max_length=200)


# ── Response ─────────────────────────────────────────────────────────────────


class VoteOptionStat(BaseModel):
    """Per-option result in statistics."""
    option: str
    count: int
    attendee_ids: list[int] | None = None  # null when anonymous


class VoteStatistics(BaseModel):
    """GET /api/votes/{vote_id}/statistics response."""
    vote_id: int
    title: str
    is_anonymous: bool
    status: str
    total_votes: int
    results: list[VoteOptionStat]


class VoteResponse(BaseModel):
    """Vote data returned to clients (used by 5 of 6 endpoints)."""
    id: int
    meeting_id: int
    title: str
    options: list[str]
    is_anonymous: bool
    status: str
    total_votes: int
    created_at: datetime
    closed_at: datetime | None = None
