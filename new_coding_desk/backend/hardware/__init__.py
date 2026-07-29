"""
Hardware integration package.

Deployment topology (historical proposal: docs/archive/project-proposal/智能会议桌项目计划书.docx):
    Arduino Nano -> seat Windows terminal (local USB serial) -> central host
    (WebSocket + REST). The central host opens NO serial port in production.

Two deploy modes (config/smartdesk.integration.json -> ``deploy_mode``):

* ``central``     (dev / single-machine): the central host opens the local
  serial ports directly via ``seat_managers`` (``{seat_id: ArduinoManager}``).
  Use this to test on one machine with Arduinos plugged into the host.

* ``distributed`` (compatibility): the central host talks to Windows Seat Edge
  Agents over WebSocket.
* ``esp32`` (production): ESP32 controllers connect directly to the same
  versioned WebSocket endpoint.
  ``seat_managers`` is empty here.

In both modes a ``SeatGatewayLike`` gateway is built (``LocalSeatGateway`` or
``SeatGateway``) and consumed by ``LightingManager``. The gateway is created in
the app lifespan (it needs the running event loop in distributed mode) and held
here so ``api/hardware.py`` can read per-seat status at request time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional

from backend.hardware.arduino_manager import ArduinoManager
from backend.hardware.lighting_manager import LightingManager
from backend.hardware.seat_gateway import LocalSeatGateway, SeatGateway
from backend.hardware.seat_hardware import build_seat_managers

logger = logging.getLogger(__name__)


def load_integration_config() -> dict:
    """Locate and parse config/smartdesk.integration.json."""
    configured_path = os.environ.get("SMARTDESK_CONFIG_PATH", "").strip()
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.extend([
        Path(__file__).resolve().parents[2] / "config" / "smartdesk.integration.json",
        Path(__file__).resolve().parents[3] / "config" / "smartdesk.integration.json",
        Path.cwd() / "config" / "smartdesk.integration.json",
    ])
    for path in candidates:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", path, exc)
    logger.warning("smartdesk.integration.json not found; hardware disabled.")
    return {}


_config = load_integration_config()
gesture_config = _config.get("gesture", {})
deploy_mode = (_config.get("deploy_mode") or "central").strip().lower()
if deploy_mode not in ("central", "distributed", "esp32"):
    logger.warning("Unknown deploy_mode %r; falling back to 'central'.", deploy_mode)
    deploy_mode = "central"


def _resolve_seat_ids() -> list[int]:
    """Determine the seat ids from config (seats map or seats_total)."""
    seats_map = (_config.get("arduino", {}) or {}).get("seats") or {}
    if seats_map:
        try:
            return sorted(int(k) for k in seats_map.keys())
        except (TypeError, ValueError):
            pass
    total = int(_config.get("seats_total", 9))
    return list(range(1, total + 1))


seat_ids: list[int] = _resolve_seat_ids()

# Demo / single-strip mode: when set, only this seat responds to lighting.
# null = broadcast to all seats (production); integer = only that seat.
lighting_config = _config.get("lighting") or {}
demo_seat_id: Optional[int] = lighting_config.get("demo_seat_id")

# In central mode, build the per-seat serial managers at import (ports NOT yet
# opened). In network modes, the central host owns no serial ports.
seat_managers: dict[int, ArduinoManager] = (
    build_seat_managers(_config) if deploy_mode == "central" else {}
)

# Gateway / LightingManager holders — populated by the app lifespan.
_seat_gateway: Optional[object] = None
_lighting_manager: Optional[LightingManager] = None


def build_gateway(loop: Optional[asyncio.AbstractEventLoop] = None):
    """Build the seat gateway for the active deploy mode (called from lifespan)."""
    if deploy_mode == "central":
        return LocalSeatGateway(seat_managers)
    return SeatGateway(loop, seat_ids)


def get_seat_gateway():
    """Return the gateway singleton (None before lifespan runs)."""
    return _seat_gateway


def set_seat_gateway(gateway) -> None:
    global _seat_gateway
    _seat_gateway = gateway


def get_lighting_manager() -> Optional[LightingManager]:
    return _lighting_manager


def set_lighting_manager(lm: LightingManager) -> None:
    global _lighting_manager
    _lighting_manager = lm


__all__ = [
    "load_integration_config",
    "deploy_mode",
    "seat_ids",
    "seat_managers",
    "demo_seat_id",
    "build_gateway",
    "get_seat_gateway",
    "set_seat_gateway",
    "get_lighting_manager",
    "set_lighting_manager",
    "gesture_config",
]
