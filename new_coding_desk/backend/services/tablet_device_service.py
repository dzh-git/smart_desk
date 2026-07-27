"""Provision and authenticate Android tablets without storing raw tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.exceptions import ConflictError, NotFoundError, ValidationError
from backend.models.tablet_device import TabletDevice
from backend.repositories.tablet_device_repository import TabletDeviceRepository

PBKDF2_ITERATIONS = 210_000
TOKEN_PREFIX = "pbkdf2_sha256"
MIN_TOKEN_LENGTH = 24


def hash_device_token(token: str, *, salt: bytes | None = None) -> str:
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValidationError(
            f"Device token must contain at least {MIN_TOKEN_LENGTH} characters",
            "DEVICE_TOKEN_TOO_SHORT",
        )
    actual_salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        token.encode("utf-8"),
        actual_salt,
        PBKDF2_ITERATIONS,
    )
    return "$".join(
        (
            TOKEN_PREFIX,
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(actual_salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_device_token(token: str, encoded: str) -> bool:
    try:
        prefix, iterations, salt_text, digest_text = encoded.split("$", 3)
        if prefix != TOKEN_PREFIX:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            token.encode("utf-8"),
            salt,
            int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError):
        return False


class TabletDeviceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = TabletDeviceRepository(db)

    def provision(
        self,
        *,
        device_id: str,
        seat_id: int,
        token: str,
        enabled: bool = True,
    ) -> TabletDevice:
        if not 1 <= seat_id <= 9:
            raise ValidationError(
                "Tablet seat_id must be between 1 and 9",
                "DEVICE_SEAT_INVALID",
            )
        if not device_id or len(device_id) > 64:
            raise ValidationError(
                "Tablet device_id is invalid",
                "DEVICE_ID_INVALID",
            )

        seat_owner = self.repo.get_by_seat(seat_id)
        if seat_owner is not None and seat_owner.id != device_id:
            raise ConflictError(
                f"Seat {seat_id} is already bound to {seat_owner.id}",
                "DEVICE_SEAT_ALREADY_BOUND",
            )

        device = self.repo.get_by_id(device_id)
        if device is None:
            device = TabletDevice(id=device_id, seat_id=seat_id)
        device.seat_id = seat_id
        device.enabled = enabled
        device.token_hash = hash_device_token(token)
        try:
            return self.repo.save(device)
        except IntegrityError as error:
            self.db.rollback()
            raise ConflictError(
                "Tablet device binding conflicts with an existing device",
                "DEVICE_BINDING_CONFLICT",
            ) from error

    def authenticate(
        self,
        *,
        device_id: str,
        seat_id: int,
        token: str | None,
    ) -> TabletDevice:
        device = self.repo.get_by_id(device_id)
        if device is None:
            raise NotFoundError(
                f"Tablet device {device_id} is not provisioned",
                "DEVICE_NOT_PROVISIONED",
            )
        if not device.enabled:
            raise ValidationError(
                f"Tablet device {device_id} is disabled",
                "DEVICE_DISABLED",
            )
        if device.seat_id != seat_id:
            raise ValidationError(
                (
                    f"Tablet device {device_id} is bound to seat "
                    f"{device.seat_id}, not seat {seat_id}"
                ),
                "DEVICE_SEAT_MISMATCH",
            )
        if not token or not verify_device_token(token, device.token_hash):
            raise ValidationError(
                "Tablet device authentication failed",
                "DEVICE_AUTH_FAILED",
            )
        return device

    def record_heartbeat(
        self,
        *,
        device_id: str,
        seat_id: int,
        token: str | None,
        app_version: str,
        camera_status: str,
        face_model_status: str,
        registered_templates_count: int,
        microphone_status: str,
        meeting_websocket_status: str,
        diagnostic_status: str,
        last_error: str | None,
    ) -> TabletDevice:
        device = self.authenticate(
            device_id=device_id,
            seat_id=seat_id,
            token=token,
        )
        device.app_version = app_version
        device.last_seen_at = datetime.now(timezone.utc)
        device.camera_status = camera_status
        device.face_model_status = face_model_status
        device.registered_templates_count = registered_templates_count
        device.microphone_status = microphone_status
        device.meeting_websocket_status = meeting_websocket_status
        device.diagnostic_status = diagnostic_status
        device.last_error = last_error
        return self.repo.save(device)
