"""Protected tablet provisioning API."""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.exceptions import ConflictError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.tablet_device import (
    TabletDeviceProvisionRequest,
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
