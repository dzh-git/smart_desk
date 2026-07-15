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
    seats_total = int(config.get("seats_total", 9))

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
    assigned_ports: dict[str, int] = {}
    for seat_key, port in seats_map.items():
        try:
            seat_id = int(seat_key)
        except (TypeError, ValueError):
            logger.warning("Invalid seat key %r in arduino.seats; skipping", seat_key)
            continue
        if not 1 <= seat_id <= seats_total:
            logger.warning(
                "Seat %d is outside configured range 1..%d; skipping",
                seat_id, seats_total,
            )
            continue
        normalized_port = str(port).upper() if port else None
        if normalized_port and normalized_port in assigned_ports:
            logger.error(
                "Serial port %s is assigned to both seat %d and seat %d; disabling seat %d",
                normalized_port, assigned_ports[normalized_port], seat_id, seat_id,
            )
            port = None
        elif normalized_port:
            assigned_ports[normalized_port] = seat_id
        managers[seat_id] = ArduinoManager(_seat_config(seat_id, port, base))

    # Preserve the complete logical seat map even before every controller is
    # installed. Missing/null ports become explicit disabled managers.
    if seats_map:
        for seat_id in range(1, seats_total + 1):
            if seat_id not in managers:
                managers[seat_id] = ArduinoManager(
                    _seat_config(seat_id, None, base),
                )
            if not managers[seat_id].port:
                logger.warning("No serial port configured for seat %d", seat_id)

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
        try:
            from serial.tools import list_ports  # type: ignore

            available = {p.device.upper() for p in list_ports.comports()}
            for sid, manager in sorted(managers.items()):
                if manager.enabled and manager.port and manager.port.upper() not in available:
                    logger.warning(
                        "Configured Arduino port is not currently present: seat=%d port=%s available=%s",
                        sid, manager.port, sorted(available),
                    )
        except Exception:
            logger.debug("Unable to enumerate serial ports during startup", exc_info=True)
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
