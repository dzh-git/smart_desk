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
from typing import Optional, Protocol, runtime_checkable

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
        self.seat_ids: list[int] = sorted(seat_ids)

    # ── lifecycle (called by the /ws/seat endpoint) ─────────────────────────

    def register(self, seat_id: int, ws) -> None:
        self._conns[seat_id] = ws
        self._connected[seat_id] = True
        logger.info("[Gateway:net] seat %d agent connected", seat_id)

    def unregister(self, seat_id: int) -> None:
        self._conns.pop(seat_id, None)
        self._connected[seat_id] = False
        logger.info("[Gateway:net] seat %d agent disconnected", seat_id)

    def set_status(self, seat_id: int, connected: bool, mode: Optional[str] = None) -> None:
        self._connected[seat_id] = connected
        if mode:
            self._reported_mode[seat_id] = mode

    def reported_mode(self, seat_id: int) -> str:
        return self._reported_mode.get(seat_id, "IDLE")

    # ── SeatGatewayLike interface ───────────────────────────────────────────

    def send(self, seat_id: int, command: str, arg: Optional[str] = None) -> bool:
        ws = self._conns.get(seat_id)
        if ws is None or self._loop is None:
            return False
        msg: dict = {"type": "lighting", "cmd": command}
        if arg is not None:
            msg["arg"] = arg
        try:
            # Thread-safe: works whether called from a service thread or the
            # loop thread itself. Fire-and-forget (we do not await the future).
            asyncio.run_coroutine_threadsafe(ws.send_json(msg), self._loop)  # type: ignore[attr-defined]
            return True
        except Exception:
            logger.exception("[Gateway:net] send failed seat=%s cmd=%s", seat_id, command)
            return False

    def is_connected(self, seat_id: int) -> bool:
        return self._connected.get(seat_id, False)

    def port(self, seat_id: int) -> Optional[str]:
        # No serial port on the central host in distributed mode.
        return None


__all__ = ["SeatGatewayLike", "LocalSeatGateway", "SeatGateway"]
