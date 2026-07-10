"""Load seat_agent_config.json (seat_id, serial_port, central_ws_url, ...)."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "baudrate": 115200,
    "write_timeout_seconds": 1.0,
    "heartbeat_interval_seconds": 5.0,
    "reconnect_interval_seconds": 3.0,
}


def _candidate_paths() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        Path.cwd() / "seat_agent_config.json",
        here / "seat_agent_config.json",
        here.parent / "seat_agent_config.json",
    ]


def load_config() -> dict:
    """Find and parse seat_agent_config.json, merged over DEFAULTS.

    Required keys: seat_id (int), serial_port (str, e.g. "COM5"),
    central_ws_url (str, e.g. "ws://192.168.1.10:8000").
    """
    cfg = dict(DEFAULTS)
    src = None
    for p in _candidate_paths():
        if p.exists():
            try:
                cfg.update(json.loads(p.read_text(encoding="utf-8")))
                src = p
                break
            except Exception as exc:
                raise RuntimeError(f"Failed to parse {p}: {exc}")
    if src is None:
        raise RuntimeError(
            "seat_agent_config.json not found. Copy seat_agent/seat_agent_config.example.json "
            "to seat_agent_config.json and fill in seat_id / serial_port / central_ws_url."
        )

    # Allow env overrides for quick per-terminal setup.
    if os.environ.get("SEAT_ID"):
        cfg["seat_id"] = int(os.environ["SEAT_ID"])
    if os.environ.get("SERIAL_PORT"):
        cfg["serial_port"] = os.environ["SERIAL_PORT"]
    if os.environ.get("CENTRAL_WS_URL"):
        cfg["central_ws_url"] = os.environ["CENTRAL_WS_URL"]

    for key in ("seat_id", "serial_port", "central_ws_url"):
        if not cfg.get(key):
            raise RuntimeError(f"seat_agent_config.json missing required key: {key}")
    cfg["seat_id"] = int(cfg["seat_id"])
    cfg["_source"] = str(src)
    return cfg
