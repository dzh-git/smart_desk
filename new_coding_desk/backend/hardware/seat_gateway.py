"""
SeatGateway — the transport layer between LightingManager and per-seat hardware.

Two implementations share one interface, so ``LightingManager`` is agnostic to
the deployment topology:

* ``LocalSeatGateway``  — *dev / single-machine* mode (``deploy_mode=central``).
  Wraps the existing ``{seat_id: ArduinoManager}`` map; ``send()`` writes
  directly to the local serial port. This is what you use to test on one
  machine with all Arduinos plugged into the central host.

* ``SeatGateway``       — *production / distributed* mode
  (``deploy_mode=distributed``). Holds a ``{seat_id: WebSocket}`` registry of
  Seat Edge Agent connections; ``send()`` pushes a JSON lighting command down
  the agent's WebSocket (fire-and-forget, scheduled on the main event loop so
  it is safe to call from synchronous EventBus handler threads). The central
  host opens NO serial port in this mode — every Arduino lives on its seat's
  Windows terminal.

Interface (both):
    seat_ids : list[int]            — seats this gateway knows about
    send(seat_id, command, arg)     — push a protocol command (SET_MODE / ...)
    is_connected(seat_id)           — is the seat's hardware reachable now
    port(seat_id)                   — serial port label (None in distributed)

Protocol command reference: arduino_nano_controller/protocol.md
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from typing import Optional, Protocol, runtime_checkable

from backend.hardware.esp32_protocol import (
    COMMAND_ACK_TIMEOUT_SECONDS,
    COMMAND_MAX_ATTEMPTS,
    EVENT_CACHE_SIZE,
    HEARTBEAT_TIMEOUT_SECONDS,
    lighting_message,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class SeatGatewayLike(Protocol):
    """Minimal interface LightingManager depends on."""

    seat_ids: list[int]

    def send(self, seat_id: int, command: str, arg: Optional[str] = None) -> bool: ...
    def is_connected(self, seat_id: int) -> bool: ...
    def port(self, seat_id: int) -> Optional[str]: ...


class LocalSeatGateway:
    """Dev mode: each seat's ArduinoManager lives in-process on the central host.

    Exposes ``seat_managers`` so LightingManager can bind firmware ``pir_callback``
    handlers per seat (the central-mode WELCOME trigger path).
    """

    def __init__(self, seat_managers: dict) -> None:
        # seat_id -> ArduinoManager
        self.seat_managers: dict = dict(seat_managers)
        self.seat_ids: list[int] = sorted(self.seat_managers.keys())

    def send(self, seat_id: int, command: str, arg: Optional[str] = None) -> bool:
        mgr = self.seat_managers.get(seat_id)
        if mgr is None:
            logger.debug("[Gateway:local] no manager for seat %s", seat_id)
            return False
        try:
            return bool(mgr.send_command(command, arg))  # type: ignore[attr-defined]
        except Exception:
            logger.exception("[Gateway:local] send failed seat=%s cmd=%s", seat_id, command)
            return False

    def is_connected(self, seat_id: int) -> bool:
        mgr = self.seat_managers.get(seat_id)
        if mgr is None:
            return False
        try:
            return bool(mgr.is_connected)  # type: ignore[attr-defined]
        except Exception:
            return False

    def port(self, seat_id: int) -> Optional[str]:
        mgr = self.seat_managers.get(seat_id)
        if mgr is None:
            return None
        return getattr(mgr, "port", None)


class SeatGateway:
    """Distributed mode: route lighting commands to Seat Edge Agents over WS.

    The central host keeps NO serial connection. Each seat's Windows terminal
    runs a ``seat_agent`` that connects to ``/ws/seat/{seat_id}``; that endpoint
    calls :meth:`register` / :meth:`unregister`. ``send()`` schedules a
    ``ws.send_json`` coroutine on the captured event loop, so it is safe to call
    from synchronous EventBus handler threads (non-blocking, fire-and-forget).
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop], seat_ids: list[int]) -> None:
        self._loop = loop
        self._conns: dict[int, object] = {}            # seat_id -> WebSocket
        self._connected: dict[int, bool] = {sid: False for sid in seat_ids}
        self._reported_mode: dict[int, str] = {sid: "IDLE" for sid in seat_ids}
        self._last_error: dict[int, Optional[str]] = {sid: None for sid in seat_ids}
        self._last_ack_at: dict[int, Optional[float]] = {sid: None for sid in seat_ids}
        self._command_pending: dict[int, bool] = {sid: False for sid in seat_ids}
        self._client_type: dict[int, str] = {sid: "unknown" for sid in seat_ids}
        self._device_id: dict[int, Optional[str]] = {sid: None for sid in seat_ids}
        self._firmware_version: dict[int, Optional[str]] = {
            sid: None for sid in seat_ids
        }
        self._boot_id: dict[int, Optional[str]] = {sid: None for sid in seat_ids}
        self._last_heartbeat_at: dict[int, Optional[float]] = {
            sid: None for sid in seat_ids
        }
        self._last_sequence: dict[int, int] = {sid: -1 for sid in seat_ids}
        self._seen_event_ids: dict[int, OrderedDict[str, None]] = {
            sid: OrderedDict() for sid in seat_ids
        }
        self._sensor_ok: dict[int, Optional[bool]] = {
            sid: None for sid in seat_ids
        }
        self._pir: dict[int, Optional[bool]] = {sid: None for sid in seat_ids}
        self._distance_mm: dict[int, Optional[int]] = {
            sid: None for sid in seat_ids
        }
        self._downlink_sequence: dict[int, int] = {
            sid: 0 for sid in seat_ids
        }
        self._pending_command: dict[int, Optional[dict]] = {
            sid: None for sid in seat_ids
        }
        self._last_command_id: dict[int, Optional[str]] = {
            sid: None for sid in seat_ids
        }
        self.seat_ids: list[int] = sorted(seat_ids)

    # ── lifecycle (called by the /ws/seat endpoint) ─────────────────────────

    def register(self, seat_id: int, ws) -> None:
        self._conns[seat_id] = ws
        self._connected[seat_id] = True
        self._client_type[seat_id] = "unknown"
        logger.info("[Gateway:net] seat %d transport connected", seat_id)

    def unregister(self, seat_id: int) -> None:
        self._conns.pop(seat_id, None)
        self._connected[seat_id] = False
        logger.info("[Gateway:net] seat %d transport disconnected", seat_id)

    def configure_legacy_session(self, seat_id: int) -> None:
        self._client_type[seat_id] = "windows_agent"
        self._last_heartbeat_at[seat_id] = time.time()

    def configure_esp32_session(
        self,
        seat_id: int,
        *,
        device_id: str,
        firmware_version: str,
        boot_id: str,
    ) -> None:
        if self._boot_id.get(seat_id) != boot_id:
            self._last_sequence[seat_id] = -1
        self._client_type[seat_id] = "esp32"
        self._device_id[seat_id] = device_id
        self._firmware_version[seat_id] = firmware_version
        self._boot_id[seat_id] = boot_id
        self._last_heartbeat_at[seat_id] = time.time()
        self._connected[seat_id] = True
        self._last_error[seat_id] = None

    def accept_sequence(self, seat_id: int, sequence: int) -> bool:
        if sequence <= self._last_sequence.get(seat_id, -1):
            return False
        self._last_sequence[seat_id] = sequence
        return True

    def accept_event(
        self,
        seat_id: int,
        *,
        event_id: str,
        sequence: int,
    ) -> str:
        seen = self._seen_event_ids[seat_id]
        if event_id in seen:
            return "duplicate"
        if not self.accept_sequence(seat_id, sequence):
            return "out_of_order"
        seen[event_id] = None
        while len(seen) > EVENT_CACHE_SIZE:
            seen.popitem(last=False)
        return "accepted"

    def accept_occupancy_event(
        self,
        seat_id: int,
        *,
        event_id: str,
        sequence: int,
    ) -> str:
        """Backward-compatible name for the generic event deduplicator."""
        return self.accept_event(
            seat_id,
            event_id=event_id,
            sequence=sequence,
        )

    def record_heartbeat(
        self,
        seat_id: int,
        *,
        mode: str,
        sensor_ok: bool | None = None,
    ) -> None:
        self._last_heartbeat_at[seat_id] = time.time()
        self._connected[seat_id] = True
        self._reported_mode[seat_id] = mode
        if sensor_ok is not None:
            self._sensor_ok[seat_id] = sensor_ok

    def record_occupancy_evidence(
        self,
        seat_id: int,
        *,
        pir: bool,
        distance_mm: int | None,
        sensor_ok: bool | None,
    ) -> None:
        self._pir[seat_id] = pir
        self._distance_mm[seat_id] = distance_mm
        if sensor_ok is not None:
            self._sensor_ok[seat_id] = sensor_ok
        self._last_heartbeat_at[seat_id] = time.time()

    def record_sensor_error(
        self,
        seat_id: int,
        *,
        component: str,
        error_code: str,
    ) -> None:
        self._sensor_ok[seat_id] = False
        self._last_error[seat_id] = f"{component}:{error_code}"
        self._last_heartbeat_at[seat_id] = time.time()

    def heartbeat_expired(
        self,
        seat_id: int,
        *,
        now: float | None = None,
    ) -> bool:
        if self._client_type.get(seat_id) != "esp32":
            return False
        last = self._last_heartbeat_at.get(seat_id)
        return (
            last is not None
            and (now if now is not None else time.time()) - last
            > HEARTBEAT_TIMEOUT_SECONDS
        )

    def mark_heartbeat_timeout(self, seat_id: int) -> None:
        self._connected[seat_id] = False
        self._last_error[seat_id] = "HEARTBEAT_TIMEOUT"

    def is_duplicate_command_ack(
        self,
        seat_id: int,
        command_id: str,
    ) -> bool:
        return self._last_command_id.get(seat_id) == command_id

    def set_status(
        self,
        seat_id: int,
        connected: bool,
        mode: Optional[str] = None,
        *,
        last_error: Optional[str] = None,
        last_ack_at: Optional[float] = None,
        command_pending: Optional[bool] = None,
    ) -> None:
        self._connected[seat_id] = connected
        self._client_type[seat_id] = "windows_agent"
        self._last_heartbeat_at[seat_id] = time.time()
        if mode:
            self._reported_mode[seat_id] = mode
        self._last_error[seat_id] = last_error
        if last_ack_at is not None:
            self._last_ack_at[seat_id] = last_ack_at
        if command_pending is not None:
            self._command_pending[seat_id] = command_pending

    def reported_mode(self, seat_id: int) -> str:
        return self._reported_mode.get(seat_id, "IDLE")

    def diagnostics(self, seat_id: int) -> dict:
        return {
            "device_type": self._client_type.get(seat_id, "unknown"),
            "device_id": self._device_id.get(seat_id),
            "firmware_version": self._firmware_version.get(seat_id),
            "last_heartbeat_at": self._last_heartbeat_at.get(seat_id),
            "last_sequence": self._last_sequence.get(seat_id, -1),
            "sensor_ok": self._sensor_ok.get(seat_id),
            "pir": self._pir.get(seat_id),
            "distance_mm": self._distance_mm.get(seat_id),
            "last_error": self._last_error.get(seat_id),
            "last_ack_at": self._last_ack_at.get(seat_id),
            "command_pending": self._command_pending.get(seat_id, False),
            "pending_command_id": (
                self._pending_command.get(seat_id) or {}
            ).get("command_id"),
        }

    # ── SeatGatewayLike interface ───────────────────────────────────────────

    def send(self, seat_id: int, command: str, arg: Optional[str] = None) -> bool:
        ws = self._conns.get(seat_id)
        if ws is None or self._loop is None:
            return False
        if self._client_type.get(seat_id) == "esp32":
            if command == "SET_MODE":
                mode = arg or ""
            elif command == "OFF":
                mode = "OFF"
            else:
                self._last_error[seat_id] = f"COMMAND_UNSUPPORTED:{command}"
                return False
            self._downlink_sequence[seat_id] += 1
            command_id = str(uuid.uuid4())
            try:
                msg = lighting_message(
                    command_id=command_id,
                    sequence=self._downlink_sequence[seat_id],
                    mode=mode,
                )
            except ValueError as error:
                self._last_error[seat_id] = str(error)
                return False
            pending = {
                "command_id": command_id,
                "message": msg,
                "sent_at": time.time(),
                "attempts": 1,
            }
        else:
            msg = {"type": "lighting", "cmd": command}
            if arg is not None:
                msg["arg"] = arg
            pending = None
        try:
            # Thread-safe: works whether called from a service thread or the
            # loop thread itself. Fire-and-forget (we do not await the future).
            asyncio.run_coroutine_threadsafe(ws.send_json(msg), self._loop)  # type: ignore[attr-defined]
            self._command_pending[seat_id] = True
            self._pending_command[seat_id] = pending
            return True
        except Exception:
            logger.exception("[Gateway:net] send failed seat=%s cmd=%s", seat_id, command)
            return False

    def retry_due_command(
        self,
        seat_id: int,
        *,
        now: float | None = None,
    ) -> str:
        pending = self._pending_command.get(seat_id)
        if pending is None:
            return "none"
        current_time = now if now is not None else time.time()
        if current_time - pending["sent_at"] < COMMAND_ACK_TIMEOUT_SECONDS:
            return "waiting"
        if pending["attempts"] >= COMMAND_MAX_ATTEMPTS:
            self._last_error[seat_id] = "COMMAND_ACK_TIMEOUT"
            self._command_pending[seat_id] = False
            self._pending_command[seat_id] = None
            return "failed"
        ws = self._conns.get(seat_id)
        if ws is None or self._loop is None:
            return "offline"
        try:
            asyncio.run_coroutine_threadsafe(
                ws.send_json(pending["message"]),  # type: ignore[attr-defined]
                self._loop,
            )
            pending["attempts"] += 1
            pending["sent_at"] = current_time
            return "retried"
        except Exception:
            logger.exception("[Gateway:esp32] retry failed seat=%s", seat_id)
            return "offline"

    def acknowledge_command(
        self,
        seat_id: int,
        *,
        command_id: str,
        success: bool,
        current_mode: str,
        error_code: str | None = None,
    ) -> str:
        pending = self._pending_command.get(seat_id)
        if pending is None:
            if self._last_command_id.get(seat_id) == command_id:
                return "duplicate"
            self._last_error[seat_id] = "UNKNOWN_COMMAND_ACK"
            return "unknown"
        if pending["command_id"] != command_id:
            self._last_error[seat_id] = "STALE_COMMAND_ACK"
            return "stale"

        self._pending_command[seat_id] = None
        self._command_pending[seat_id] = False
        self._last_command_id[seat_id] = command_id
        self._last_ack_at[seat_id] = time.time()
        self._reported_mode[seat_id] = current_mode
        self._last_error[seat_id] = (
            None if success else (error_code or "COMMAND_REJECTED")
        )
        return "applied" if success else "rejected"

    def is_connected(self, seat_id: int) -> bool:
        return self._connected.get(seat_id, False)

    def port(self, seat_id: int) -> Optional[str]:
        # No serial port on the central host in distributed mode.
        return None


__all__ = ["SeatGatewayLike", "LocalSeatGateway", "SeatGateway"]
