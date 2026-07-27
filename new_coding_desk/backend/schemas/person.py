"""Stable person identity DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


PERSON_ID_PATTERN = r"^[A-Za-z0-9._-]{3,64}$"


class PersonCreate(BaseModel):
    id: str = Field(..., pattern=PERSON_ID_PATTERN)
    name: str = Field(..., min_length=1, max_length=100)


class PersonResponse(BaseModel):
    id: str
    name: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
