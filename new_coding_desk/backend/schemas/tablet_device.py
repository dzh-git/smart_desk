"""Tablet provisioning and status DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    replace_existing: bool = Field(False, alias="replaceExisting")

    model_config = {"populate_by_name": True}


class TabletDeviceResponse(BaseModel):
    device_id: str = Field(validation_alias="id", serialization_alias="deviceId")
    seat_id: int = Field(serialization_alias="seatId")
    seat_alias: str = Field(serialization_alias="seatAlias")
    enabled: bool
    app_version: str | None = Field(
        default=None,
        serialization_alias="appVersion",
    )
    last_seen_at: datetime | None = Field(
        default=None,
        serialization_alias="lastSeenAt",
    )
    camera_status: str | None = Field(
        default=None,
        serialization_alias="cameraStatus",
    )
    face_model_status: str | None = Field(
        default=None,
        serialization_alias="faceModelStatus",
    )
    registered_templates_count: int | None = Field(
        default=None,
        serialization_alias="registeredTemplatesCount",
    )
    microphone_status: str | None = Field(
        default=None,
        serialization_alias="microphoneStatus",
    )
    meeting_websocket_status: str | None = Field(
        default=None,
        serialization_alias="meetingWebsocketStatus",
    )
    diagnostic_status: str | None = Field(
        default=None,
        serialization_alias="diagnosticStatus",
    )
    last_error: str | None = Field(
        default=None,
        serialization_alias="lastError",
    )

    model_config = {
        "from_attributes": True,
        "populate_by_name": True,
    }


class TabletDeviceHeartbeatRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=9, alias="seatId")
    app_version: str = Field(
        ...,
        min_length=1,
        max_length=64,
        alias="appVersion",
    )
    camera_status: Literal["READY", "ERROR", "UNKNOWN"] = Field(
        alias="cameraStatus",
    )
    face_model_status: Literal["READY", "ERROR", "UNKNOWN"] = Field(
        alias="faceModelStatus",
    )
    registered_templates_count: int = Field(
        ...,
        ge=0,
        le=100,
        alias="registeredTemplatesCount",
    )
    microphone_status: Literal["READY", "ERROR", "UNKNOWN"] = Field(
        alias="microphoneStatus",
    )
    meeting_websocket_status: Literal[
        "CONNECTED",
        "CONNECTING",
        "DISCONNECTED",
        "UNKNOWN",
    ] = Field(alias="meetingWebsocketStatus")
    diagnostic_status: Literal["READY", "ERROR", "UNKNOWN"] = Field(
        alias="diagnosticStatus",
    )
    last_error: str | None = Field(
        default=None,
        max_length=300,
        alias="lastError",
    )

    model_config = {"populate_by_name": True}


class TabletDeviceValidateRequest(BaseModel):
    seat_id: int = Field(..., ge=1, le=9, alias="seatId")
    app_version: str = Field(
        ...,
        min_length=1,
        max_length=64,
        alias="appVersion",
    )

    model_config = {"populate_by_name": True}
