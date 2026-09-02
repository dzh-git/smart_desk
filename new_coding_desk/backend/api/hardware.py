"""
Hardware status API — expose per-seat hardware & gesture service status.

GET /api/hardware/status
    Returns, for each seat, its reachability (enabled / connected / port /
    ACK-confirmed mode, intended mode and diagnostics), plus the gesture
    service state. Works in both deploy modes:
      * central     — reads from the local ArduinoManagers (serial).
      * distributed — reads from the SeatGateway (agent-reported online state).
    Always responds 200 even when offline, so the management UI can render
    red/green dots without special-casing errors.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.hardware import (
    deploy_mode,
    seat_ids,
    seat_managers,
    get_seat_gateway,
    get_lighting_manager,
    gesture_config,
)
from backend.hardware.seat_gateway import SeatGateway
from backend.repositories.tablet_device_repository import (
    TabletDeviceRepository,
)
from backend.utils import _ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hardware", tags=["hardware"])
DEFAULT_TABLET_OFFLINE_TIMEOUT_SECONDS = 45


async def _probe_tcp(host: str, port: int, timeout: float = 1.0) -> bool:
    """Lightweight TCP reachability probe (gesture service is a WS server)."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


def _tablet_timeout_seconds() -> int:
    try:
        configured = int(
            os.environ.get(
                "SMARTDESK_TABLET_OFFLINE_TIMEOUT_SECONDS",
                str(DEFAULT_TABLET_OFFLINE_TIMEOUT_SECONDS),
            )
        )
    except ValueError:
        return DEFAULT_TABLET_OFFLINE_TIMEOUT_SECONDS
    return max(10, min(configured, 300))


def _heartbeat_age_seconds(
    last_seen_at: datetime | None,
    *,
    now: datetime,
) -> float | None:
    if last_seen_at is None:
        return None
    comparable = (
        last_seen_at.replace(tzinfo=timezone.utc)
        if last_seen_at.tzinfo is None
        else last_seen_at.astimezone(timezone.utc)
    )
    return max(0.0, (now - comparable).total_seconds())


@router.get("/status")
async def hardware_status(db: Session = Depends(get_db)):
    g = gesture_config
    url = g.get("status_ws_url", "")
    host, port = "127.0.0.1", 8765
    if url:
        parsed = urlparse(url)
        host = parsed.hostname or host
        port = parsed.port or port

    gesture_online = False
    if g.get("enabled", False):
        gesture_online = await _probe_tcp(host, port)

    lm = get_lighting_manager()
    gateway = get_seat_gateway()

    seats = []
    if deploy_mode == "central":
        for seat_id in sorted(seat_managers.keys()):
            mgr = seat_managers[seat_id]
            intended = lm.seat_mode.get(seat_id, "IDLE") if lm is not None else "IDLE"
            seats.append(
                {
                    "seat_id": seat_id,
                    "enabled": mgr.enabled,
                    "connected": mgr.is_connected,
                    "port": mgr.port,
                    "current_mode": mgr.current_mode,
                    "intended_mode": intended,
                    "command_pending": mgr.command_pending,
                    "last_ack_at": mgr.last_ack_at,
                    "last_error": mgr.last_error,
                }
            )
    else:
        # distributed: status comes from the SeatGateway (agent-reported).
        for seat_id in seat_ids:
            if (
                isinstance(gateway, SeatGateway)
                and gateway.heartbeat_expired(seat_id)
            ):
                gateway.mark_heartbeat_timeout(seat_id)
            connected = (
                gateway.is_connected(seat_id) if isinstance(gateway, SeatGateway) else False
            )
            diag = gateway.diagnostics(seat_id) if isinstance(gateway, SeatGateway) else {}
            applied = (
                gateway.reported_mode(seat_id)
                if isinstance(gateway, SeatGateway)
                else "UNKNOWN"
            )
            seats.append(
                {
                    "seat_id": seat_id,
                    "enabled": connected,
                    "connected": connected,
                    "port": None,
                    "current_mode": applied,
                    "intended_mode": (
                        lm.seat_mode.get(seat_id, "IDLE") if lm is not None else "IDLE"
                    ),
                    "command_pending": diag.get("command_pending", False),
                    "last_ack_at": diag.get("last_ack_at"),
                    "last_error": diag.get("last_error"),
                    "device_type": diag.get("device_type", "unknown"),
                    "device_id": diag.get("device_id"),
                    "firmware_version": diag.get("firmware_version"),
                    "last_heartbeat_at": diag.get("last_heartbeat_at"),
                    "last_sequence": diag.get("last_sequence"),
                    "sensor_ok": diag.get("sensor_ok"),
                    "pir": diag.get("pir"),
                    "distance_mm": diag.get("distance_mm"),
                    "pending_command_id": diag.get(
                        "pending_command_id"
                    ),
                }
            )

    now = datetime.now(timezone.utc)
    tablet_timeout = _tablet_timeout_seconds()
    tablet_by_seat = {
        device.seat_id: device
        for device in TabletDeviceRepository(db).list_all()
    }
    tablets = []
    for seat_id in range(1, 10):
        device = tablet_by_seat.get(seat_id)
        age = _heartbeat_age_seconds(
            device.last_seen_at if device is not None else None,
            now=now,
        )
        online = bool(
            device is not None
            and device.enabled
            and age is not None
            and age <= tablet_timeout
        )
        tablets.append(
            {
                "seat_id": seat_id,
                "seat_alias": f"tablet-seat-{seat_id:02d}",
                "provisioned": device is not None,
                "device_id": device.id if device is not None else None,
                "enabled": device.enabled if device is not None else False,
                "online": online,
                "last_heartbeat_at": (
                    device.last_seen_at if device is not None else None
                ),
                "heartbeat_age_seconds": age,
                "app_version": (
                    device.app_version if device is not None else None
                ),
                "camera_status": (
                    device.camera_status if device is not None else None
                ),
                "face_model_status": (
                    device.face_model_status if device is not None else None
                ),
                "registered_templates_count": (
                    device.registered_templates_count
                    if device is not None
                    else None
                ),
                "microphone_status": (
                    device.microphone_status if device is not None else None
                ),
                "meeting_websocket_status": (
                    device.meeting_websocket_status
                    if device is not None
                    else None
                ),
                "diagnostic_status": (
                    device.diagnostic_status if device is not None else None
                ),
                "last_error": (
                    device.last_error if device is not None else None
                ),
                "face_template_meeting_id": (
                    device.face_template_meeting_id
                    if device is not None
                    else None
                ),
                "face_template_set_revision": (
                    device.face_template_set_revision
                    if device is not None
                    else None
                ),
                "face_template_sync_count": (
                    device.face_template_sync_count
                    if device is not None
                    else None
                ),
                "face_template_sync_status": (
                    device.face_template_sync_status
                    if device is not None
                    else None
                ),
                "face_template_sync_error": (
                    device.face_template_sync_error
                    if device is not None
                    else None
                ),
            }
        )

    return _ok(
        {
            "deploy_mode": deploy_mode,
            "seats": seats,
            "tablets": tablets,
            "tablet_offline_timeout_seconds": tablet_timeout,
            "integrated": bool(seats) and any(s["connected"] for s in seats),
            "gesture": {
                "enabled": g.get("enabled", False),
                "status_ws_url": url,
                "online": gesture_online,
            },
        }
    )
