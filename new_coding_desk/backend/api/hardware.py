"""
Hardware status API — expose per-seat hardware & gesture service status.

GET /api/hardware/status
    Returns, for each seat, its reachability (enabled / connected / port /
    current_mode), plus the gesture service state. Works in both deploy modes:
      * central     — reads from the local ArduinoManagers (serial).
      * distributed — reads from the SeatGateway (agent-reported online state).
    Always responds 200 even when offline, so the management UI can render
    red/green dots without special-casing errors.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from fastapi import APIRouter

from backend.hardware import (
    deploy_mode,
    seat_ids,
    seat_managers,
    get_seat_gateway,
    get_lighting_manager,
    gesture_config,
)
from backend.hardware.seat_gateway import SeatGateway
from backend.utils import _ok

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hardware", tags=["hardware"])


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


@router.get("/status")
async def hardware_status():
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
            seats.append(
                {
                    "seat_id": seat_id,
                    "enabled": mgr.enabled,
                    "connected": mgr.is_connected,
                    "port": mgr.port,
                    "current_mode": (
                        lm.seat_mode.get(seat_id, "IDLE") if lm is not None else "IDLE"
                    ),
                }
            )
    else:
        # distributed: status comes from the SeatGateway (agent-reported).
        for seat_id in seat_ids:
            connected = (
                gateway.is_connected(seat_id) if isinstance(gateway, SeatGateway) else False
            )
            seats.append(
                {
                    "seat_id": seat_id,
                    "enabled": connected,
                    "connected": connected,
                    "port": None,
                    "current_mode": (
                        lm.seat_mode.get(seat_id, "IDLE") if lm is not None else "IDLE"
                    ),
                }
            )

    return _ok(
        {
            "deploy_mode": deploy_mode,
            "seats": seats,
            "integrated": bool(seats) and any(s["connected"] for s in seats),
            "gesture": {
                "enabled": g.get("enabled", False),
                "status_ws_url": url,
                "online": gesture_online,
            },
        }
    )
