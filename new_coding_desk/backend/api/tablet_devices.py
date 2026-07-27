"""Protected tablet provisioning API."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.exceptions import ConflictError, NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.tablet_device import (
    TabletDeviceProvisionRequest,
    TabletDeviceHeartbeatRequest,
    TabletDeviceResponse,
)
from backend.services.tablet_device_service import TabletDeviceService

router = APIRouter(prefix="/api/tablet-devices", tags=["tablet-devices"])


def _error(error, status_code: int) -> JSONResponse:
    return JSONResponse(
        content=ApiResponse.fail(
            error.message,
            error.error_code,
        ).model_dump(),
        status_code=status_code,
    )


def _provisioning_allowed(token: str | None) -> bool:
    expected = os.environ.get("SMARTDESK_DEVICE_PROVISIONING_TOKEN", "")
    return (
        len(expected) >= 24
        and token is not None
        and hmac.compare_digest(token, expected)
    )


@router.post(
    "/provision",
    response_model=ApiResponse[TabletDeviceResponse],
    status_code=201,
)
def provision_tablet(
    body: TabletDeviceProvisionRequest,
    db: Session = Depends(get_db),
    provisioning_token: str | None = Header(
        default=None,
        alias="X-SmartDesk-Provisioning-Token",
    ),
):
    """Create or rotate a tablet binding; disabled unless an admin token exists."""
    if not _provisioning_allowed(provisioning_token):
        return JSONResponse(
            content=ApiResponse.fail(
                "Tablet provisioning is disabled or unauthorized",
                "DEVICE_PROVISIONING_UNAUTHORIZED",
            ).model_dump(),
            status_code=403,
        )
    try:
        device = TabletDeviceService(db).provision(
            device_id=body.device_id,
            seat_id=body.seat_id,
            token=body.device_token,
            enabled=body.enabled,
        )
    except ConflictError as error:
        return _error(error, 409)
    except ValidationError as error:
        return _error(error, 400)
    return ApiResponse.ok(
        data=TabletDeviceResponse.model_validate(device),
    )


@router.post(
    "/{device_id}/heartbeat",
    response_model=ApiResponse[TabletDeviceResponse],
)
def tablet_heartbeat(
    device_id: str,
    body: TabletDeviceHeartbeatRequest,
    db: Session = Depends(get_db),
    device_token: str | None = Header(
        default=None,
        alias="X-SmartDesk-Device-Token",
    ),
):
    """Record authenticated, non-biometric tablet operational status."""
    try:
        device = TabletDeviceService(db).record_heartbeat(
            device_id=device_id,
            seat_id=body.seat_id,
            token=device_token,
            app_version=body.app_version,
            camera_status=body.camera_status,
            face_model_status=body.face_model_status,
            registered_templates_count=body.registered_templates_count,
            microphone_status=body.microphone_status,
            meeting_websocket_status=body.meeting_websocket_status,
            diagnostic_status=body.diagnostic_status,
            last_error=body.last_error,
        )
    except NotFoundError as error:
        return _error(error, 404)
    except ValidationError as error:
        return _error(error, 400)
    return ApiResponse.ok(
        data=TabletDeviceResponse.model_validate(device),
    )
