"""
seat_hardware — per-seat Arduino manager construction.

The final hardware is 9 Arduino Nanos, one per seat (seat 1 = host, 2..9 =
the other 8 seats). Each Nano controls an independent LED strip and is
flashed with the same ``smartdesk_lighting_controller.ino``; the only thing
that differs is the serial port.

This module turns the ``arduino.seats`` map in
config/smartdesk.integration.json into a ``{seat_id: ArduinoManager}`` dict
and provides helpers to start/stop them all. The firmware is NOT modified
for per-seat support — addressing is purely by which serial port a command
is sent to.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.hardware.arduino_manager import ArduinoManager

logger = logging.getLogger(__name__)

DEFAULT_BAUDRATE = 115200


def _seat_config(seat_id: int, port: Optional[str], base: dict) -> dict:
    """Build an ``ArduinoManager`` config dict for one seat."""
    cfg = dict(base)
    cfg["port"] = port
    # A seat is only enabled if it has a (non-empty) port assigned.
    cfg["enabled"] = bool(port) and bool(base.get("enabled", True))
    return cfg


def build_seat_managers(config: dict) -> dict[int, ArduinoManager]:
    """Construct one ``ArduinoManager`` per seat from config.

    Reads ``config["arduino"]["seats"]`` which maps seat_id (str) -> port
    (str). Returns ``{seat_id(int): ArduinoManager}``.

    Backward compatibility: if ``seats`` is absent but a single ``port`` key
    exists, it is mapped to seat 1 (legacy single-strip setup).
    """
    arduino_cfg = config.get("arduino", {}) or {}
    seats_map = arduino_cfg.get("seats") or {}

    base = {
        "enabled": bool(arduino_cfg.get("enabled", True)),
        "baudrate": int(arduino_cfg.get("baudrate", DEFAULT_BAUDRATE)),
        "write_timeout_seconds": float(arduino_cfg.get("write_timeout_seconds", 1.0)),
        "heartbeat_interval_seconds": float(
            arduino_cfg.get("heartbeat_interval_seconds", 5.0)
        ),
        "reconnect_interval_seconds": float(
            arduino_cfg.get("reconnect_interval_seconds", 3.0)
        ),
    }

    managers: dict[int, ArduinoManager] = {}
    for seat_key, port in seats_map.items():
        try:
            seat_id = int(seat_key)
        except (TypeError, ValueError):
            logger.warning("Invalid seat key %r in arduino.seats; skipping", seat_key)
            continue
        managers[seat_id] = ArduinoManager(_seat_config(seat_id, port, base))

    # Legacy fallback: single port, no seats map -> seat 1.
    if not managers and arduino_cfg.get("port"):
        managers[1] = ArduinoManager(_seat_config(1, arduino_cfg.get("port"), base))

    if not managers:
        logger.warning(
            "No arduino seats configured; desktop lighting disabled."
        )
    else:
        logger.info(
            "Built %d per-seat Arduino managers: %s",
            len(managers),
            {sid: m.port for sid, m in sorted(managers.items())},
        )
    return managers


def start_all(managers: dict[int, ArduinoManager]) -> None:
    """Start the reader thread for every seat manager (non-fatal per seat)."""
    for seat_id, mgr in sorted(managers.items()):
        try:
            mgr.start()
        except Exception:  # pragma: no cover - hardware dependent
            logger.exception("Failed to start ArduinoManager for seat %d", seat_id)


def stop_all(managers: dict[int, ArduinoManager]) -> None:
    """Stop every seat manager (close serial ports gracefully)."""
    for seat_id, mgr in sorted(managers.items()):
        try:
            mgr.stop()
        except Exception:  # pragma: no cover - hardware dependent
            logger.exception("Failed to stop ArduinoManager for seat %d", seat_id)
