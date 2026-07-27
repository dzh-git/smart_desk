"""Tablet provisioning and status DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TabletDeviceProvisionRequest(BaseModel):
    device_id: str = Field(
        ...,
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
        alias="deviceId",
    )
    seat_id: int = Field(..., ge=1, le=9, alias="seatId")
    device_token: str = Field(
        ...,
        min_length=24,
        max_length=256,
        alias="deviceToken",
    )
    enabled: bool = True

    model_config = {"populate_by_name": True}


class TabletDeviceResponse(BaseModel):
    device_id: str = Field(validation_alias="id", serialization_alias="deviceId")
    seat_id: int = Field(serialization_alias="seatId")
    enabled: bool
    app_version: str | None = Field(
        default=None,
        serialization_alias="appVersion",
    )
    last_seen_at: datetime | None = Field(
        default=None,
        serialization_alias="lastSeenAt",
    )
    last_error: str | None = Field(
        default=None,
        serialization_alias="lastError",
    )

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }
