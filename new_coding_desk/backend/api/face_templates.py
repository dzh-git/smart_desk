"""Seat 1 face-template management and participant-tablet sync APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.exceptions import ConflictError, NotFoundError, ValidationError
from backend.schemas import ApiResponse
from backend.schemas.face_template import (
    FaceSeatAssignmentsRequest,
    FaceSeatAssignmentsResponse,
    FaceTemplateBundleResponse,
    FaceTemplateLibraryResponse,
    FaceTemplateSaveResult,
    FaceTemplateSyncAckRequest,
    FaceTemplateUploadRequest,
    FaceTransportKeyRequest,
    ServerTransportKeyResponse,
)
from backend.services.face_template_service import FaceTemplateService

router = APIRouter(prefix="/api/face-templates", tags=["face-templates"])
device_router = APIRouter(
    prefix="/api/tablet-devices",
    tags=["tablet-face-sync"],
)


def _error(error: Exception, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ApiResponse.fail(
            getattr(error, "message", str(error)),
            getattr(error, "error_code", "FACE_TEMPLATE_ERROR"),
        ).model_dump(),
    )


def _status(error: Exception) -> int:
    if isinstance(error, NotFoundError):
        return 404
    if isinstance(error, ConflictError):
        return 409
    code = getattr(error, "error_code", "")
    if code in {"DEVICE_AUTH_FAILED", "HOST_DEVICE_REQUIRED"}:
        return 403
    return 400


@router.get(
    "/transport-key",
    response_model=ApiResponse[ServerTransportKeyResponse],
)
def get_server_transport_key(db: Session = Depends(get_db)):
    return ApiResponse.ok(
        ServerTransportKeyResponse(
            publicKeyPem=FaceTemplateService(db).server_transport_key(),
        )
    )


@router.get("", response_model=ApiResponse[FaceTemplateLibraryResponse])
def list_templates(
    device_id: str = Query(alias="deviceId"),
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    service = FaceTemplateService(db)
    try:
        service.authenticate_host(device_id=device_id, token=token)
        return ApiResponse.ok(service.list_library())
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@router.put(
    "/{person_id}",
    response_model=ApiResponse[FaceTemplateSaveResult],
)
def save_template(
    person_id: str,
    body: FaceTemplateUploadRequest,
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    service = FaceTemplateService(db)
    try:
        service.authenticate_host(device_id=body.device_id, token=token)
        result = service.save_encrypted_upload(
            person_id=person_id,
            envelope=body.envelope.model_dump(by_alias=True),
        )
        return ApiResponse.ok(result)
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@router.delete("/{person_id}", response_model=ApiResponse[None])
def delete_template(
    person_id: str,
    device_id: str = Query(alias="deviceId"),
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    service = FaceTemplateService(db)
    try:
        service.authenticate_host(device_id=device_id, token=token)
        service.delete_template(person_id)
        return ApiResponse.ok()
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@router.get(
    "/meetings/{meeting_id}/assignments",
    response_model=ApiResponse[FaceSeatAssignmentsResponse],
)
def get_assignments(
    meeting_id: int,
    device_id: str = Query(alias="deviceId"),
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    service = FaceTemplateService(db)
    try:
        service.authenticate_host(device_id=device_id, token=token)
        return ApiResponse.ok(service.get_assignments(meeting_id))
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@router.put(
    "/meetings/{meeting_id}/assignments",
    response_model=ApiResponse[FaceSeatAssignmentsResponse],
)
def update_assignments(
    meeting_id: int,
    body: FaceSeatAssignmentsRequest,
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    service = FaceTemplateService(db)
    try:
        service.authenticate_host(device_id=body.device_id, token=token)
        return ApiResponse.ok(
            service.update_assignments(meeting_id, body.assignments)
        )
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@device_router.put(
    "/{device_id}/face-transport-key",
    response_model=ApiResponse[dict],
)
def register_transport_key(
    device_id: str,
    body: FaceTransportKeyRequest,
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    try:
        fingerprint = FaceTemplateService(db).register_device_key(
            device_id=device_id,
            seat_id=body.seat_id,
            token=token,
            public_key_pem=body.public_key_pem,
        )
        return ApiResponse.ok({"fingerprint": fingerprint})
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@device_router.get(
    "/{device_id}/face-template-bundle",
    response_model=ApiResponse[FaceTemplateBundleResponse],
)
def get_template_bundle(
    device_id: str,
    seat_id: int = Query(alias="seatId", ge=2, le=9),
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    try:
        meeting_id, revision, count, envelope = FaceTemplateService(db).build_active_bundle(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
        return ApiResponse.ok(
            FaceTemplateBundleResponse(
                meetingId=meeting_id,
                templateSetRevision=revision,
                templateCount=count,
                envelope=envelope,
            )
        )
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))


@device_router.post(
    "/{device_id}/face-template-sync-ack",
    response_model=ApiResponse[None],
)
def acknowledge_template_sync(
    device_id: str,
    body: FaceTemplateSyncAckRequest,
    token: str | None = Header(None, alias="X-SmartDesk-Device-Token"),
    db: Session = Depends(get_db),
):
    try:
        FaceTemplateService(db).record_sync_ack(
            device_id=device_id,
            seat_id=body.seat_id,
            token=token,
            meeting_id=body.meeting_id,
            revision=body.template_set_revision,
            template_count=body.template_count,
            status=body.status,
            error=body.error,
        )
        return ApiResponse.ok()
    except (NotFoundError, ConflictError, ValidationError) as error:
        return _error(error, _status(error))
