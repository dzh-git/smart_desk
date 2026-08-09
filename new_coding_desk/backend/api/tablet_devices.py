"""Protected tablet provisioning API."""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.exceptions import ConflictError, NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.tablet_device import (
    TabletDeviceProvisionRequest,
    TabletDeviceHeartbeatRequest,
    TabletDeviceResponse,
    TabletDeviceValidateRequest,
)
from backend.services.tablet_device_service import TabletDeviceService
from backend.security.rate_limit import (
    SlidingWindowRateLimiter,
    bounded_env_int,
)
from backend.security.structured_log import log_security_event

router = APIRouter(prefix="/api/tablet-devices", tags=["tablet-devices"])
logger = logging.getLogger(__name__)
provision_rate_limiter = SlidingWindowRateLimiter()
heartbeat_rate_limiter = SlidingWindowRateLimiter()


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
    request: Request,
    db: Session = Depends(get_db),
    provisioning_token: str | None = Header(
        default=None,
        alias="X-SmartDesk-Provisioning-Token",
    ),
):
    """Create or rotate a tablet binding; disabled unless an admin token exists."""
    client_host = request.client.host if request.client else "unknown"
    rate_decision = provision_rate_limiter.check(
        client_host,
        limit=bounded_env_int(
            "SMARTDESK_PROVISION_RATE_LIMIT_PER_MINUTE",
            10,
            minimum=1,
            maximum=120,
        ),
        window_seconds=60,
    )
    if not rate_decision.allowed:
        return _rate_limited_response(
            rate_decision.retry_after_seconds,
            event="tablet_provision_rate_limited",
            client=client_host,
        )
    if not _provisioning_allowed(provisioning_token):
        log_security_event(
            logger,
            event="tablet_provision",
            level=logging.WARNING,
            client=client_host,
            device_id=body.device_id,
            seat_id=body.seat_id,
            result="unauthorized",
        )
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
            replace_existing=body.replace_existing,
        )
    except ConflictError as error:
        return _error(error, 409)
    except ValidationError as error:
        return _error(error, 400)
    log_security_event(
        logger,
        event="tablet_provision",
        device_id=body.device_id,
        seat_id=body.seat_id,
        result="accepted",
        replace_existing=body.replace_existing,
    )
    return ApiResponse.ok(
        data=TabletDeviceResponse.model_validate(device),
    )


@router.post(
    "/{device_id}/validate",
    response_model=ApiResponse[TabletDeviceResponse],
)
def validate_tablet_binding(
    device_id: str,
    body: TabletDeviceValidateRequest,
    db: Session = Depends(get_db),
    device_token: str | None = Header(
        default=None,
        alias="X-SmartDesk-Device-Token",
    ),
):
    """Validate a stored tablet binding before loading its seat page."""
    try:
        device = TabletDeviceService(db).validate_binding(
            device_id=device_id,
            seat_id=body.seat_id,
            token=device_token,
            app_version=body.app_version,
        )
    except NotFoundError as error:
        return _error(error, 404)
    except ValidationError as error:
        status = {
            "DEVICE_AUTH_FAILED": 401,
            "DEVICE_DISABLED": 403,
            "DEVICE_SEAT_MISMATCH": 409,
        }.get(error.error_code, 400)
        return _error(error, status)
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
    rate_decision = heartbeat_rate_limiter.check(
        f"{device_id}:{body.seat_id}",
        limit=bounded_env_int(
            "SMARTDESK_TABLET_HEARTBEAT_RATE_LIMIT_PER_MINUTE",
            30,
            minimum=1,
            maximum=240,
        ),
        window_seconds=60,
    )
    if not rate_decision.allowed:
        return _rate_limited_response(
            rate_decision.retry_after_seconds,
            event="tablet_heartbeat_rate_limited",
            device_id=device_id,
            seat_id=body.seat_id,
        )
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
        _log_heartbeat_result(device_id, body.seat_id, error.error_code)
        return _error(error, 404)
    except ValidationError as error:
        _log_heartbeat_result(device_id, body.seat_id, error.error_code)
        return _error(error, 400)
    _log_heartbeat_result(device_id, body.seat_id, "OK")
    return ApiResponse.ok(
        data=TabletDeviceResponse.model_validate(device),
    )


def _rate_limited_response(
    retry_after: int,
    *,
    event: str,
    **fields,
) -> JSONResponse:
    log_security_event(
        logger,
        event=event,
        level=logging.WARNING,
        result="rejected",
        **fields,
    )
    response = JSONResponse(
        content=ApiResponse.fail(
            "Device request rate limit exceeded",
            "RATE_LIMITED",
        ).model_dump(),
        status_code=429,
    )
    response.headers["Retry-After"] = str(retry_after)
    return response


def _log_heartbeat_result(
    device_id: str,
    seat_id: int,
    result: str,
) -> None:
    log_security_event(
        logger,
        event="tablet_heartbeat",
        level=(logging.INFO if result == "OK" else logging.WARNING),
        device_id=device_id,
        seat_id=seat_id,
        result=result,
    )
