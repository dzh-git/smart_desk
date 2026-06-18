"""Local status broadcast server for the gesture controller.

Runs an async ``websockets`` server on ``127.0.0.1:8765`` inside a daemon
thread. The controller pushes state updates via :meth:`update`; the server
periodically broadcasts a JSON snapshot to every connected client.

Design rules:
    - **Never crash the controller.** Any failure (port in use, missing
      ``websockets`` package, send error) is logged and swallowed. If the
      server cannot start, the controller keeps running without it.
    - **No business coupling.** The wire format here is the contract a future
      ``/display`` overlay will consume; nothing on the backend FastAPI side
      imports or depends on this server.
    - **Optional.** ``GestureConfig.status_server_enabled=False`` (CLI
      ``--no-server``) skips starting it entirely.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("hands.status_server")


class GestureStatusServer:
    """Threaded wrapper around an asyncio websockets server.

    Public API is synchronous (``update``, ``start``, ``stop``) so the
    controller's frame loop never has to touch asyncio directly.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        broadcast_interval: float = 0.2,
    ) -> None:
        self._host = host
        self._port = port
        self._broadcast_interval = broadcast_interval

        self._state: Dict[str, Any] = {
            "mode": "standby",
            "gesture": "none",
            "action": "idle",
            "camera_ok": False,
            "control_enabled": True,
            "paused": True,
            "fps": 0.0,
            "connected_clients": 0,
            "timestamp": 0.0,
        }
        self._lock = threading.Lock()

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._server: Optional[Any] = None
        self._clients: Set[Any] = set()
        self._running = False
        self._start_error: Optional[BaseException] = None

    # ── public sync API ────────────────────────────────────────────────────
    def update(self, **fields: Any) -> None:
        """Merge partial state. Safe to call from the controller thread."""
        with self._lock:
            self._state.update(fields)
            self._state["timestamp"] = time.time()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self) -> bool:
        """Spawn the server thread. Returns False if it could not start."""
        if self._running:
            return True
        self._start_error = None
        self._thread = threading.Thread(
            target=self._run_loop,
            name="hands-status-ws",
            daemon=True,
        )
        self._thread.start()
        # Give the loop a brief moment to record any startup failure.
        time.sleep(0.05)
        if self._start_error is not None:
            logger.warning("status server failed to start: %r", self._start_error)
            return False
        return True

    def stop(self) -> None:
        """Signal the server thread to stop. Safe to call multiple times."""
        if not self._running:
            return
        self._running = False
        loop = self._loop
        stop_event = self._stop_event
        if loop and stop_event and loop.is_running():
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except Exception:  # pragma: no cover - defensive
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    # ── internals ──────────────────────────────────────────────────────────
    def _run_loop(self) -> None:
        try:
            asyncio.run(self._async_main())
        except Exception as exc:  # pragma: no cover - environment dependent
            logger.exception("status server loop crashed")
            self._start_error = exc
            self._running = False

    async def _async_main(self) -> None:
        try:
            import websockets
        except ImportError:
            self._start_error = ImportError("websockets not installed")
            logger.warning("websockets package missing; status server disabled")
            return

        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        try:
            self._server = await websockets.serve(
                self._client_handler,
                self._host,
                self._port,
            )
        except OSError as exc:
            # Port in use / permission denied — most common failure.
            self._start_error = exc
            logger.warning("status server could not bind %s:%s — %s", self._host, self._port, exc)
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._start_error = exc
            logger.exception("status server failed to start")
            return

        self._running = True
        logger.info("status server listening on ws://%s:%s", self._host, self._port)

        broadcaster = asyncio.ensure_future(self._broadcast_loop())
        try:
            await self._stop_event.wait()
        finally:
            broadcaster.cancel()
            try:
                await broadcaster
            except (asyncio.CancelledError, Exception):
                pass
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # pragma: no cover
                pass
            self._running = False

    async def _client_handler(self, ws: Any) -> None:
        """Per-connection handler. Registers the client and keeps it alive."""
        self._clients.add(ws)
        self.update(connected_clients=len(self._clients))
        # Send an immediate snapshot so a newly connected client isn't blank.
        try:
            await ws.send(json.dumps(self.snapshot()))
        except Exception:  # pragma: no cover
            pass
        try:
            # We don't expect inbound messages; just keep the socket open and
            # discard anything the client sends.
            async for _ in ws:
                pass
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            self.update(connected_clients=len(self._clients))

    async def _broadcast_loop(self) -> None:
        """Periodically push the latest snapshot to every client."""
        while self._running:
            payload = json.dumps(self.snapshot())
            # Snapshot the client set under no lock; websockets set ops are
            # mutated only on the loop thread.
            dead: list = []
            for ws in list(self._clients):
                try:
                    await ws.send(payload)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self._clients.discard(ws)
            if dead:
                self.update(connected_clients=len(self._clients))
            await asyncio.sleep(self._broadcast_interval)
