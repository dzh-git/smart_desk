"""Local status broadcast server for the gesture controller.

Runs an async ``websockets`` server on ``127.0.0.1:8765`` inside a daemon
thread. The controller pushes state updates via :meth:`update`; the server
periodically broadcasts a JSON snapshot to every connected client.

Starting with this phase, the same port also serves a static Device Status Card
at ``http://127.0.0.1:8765/`` so operators can open a browser and see the
current camera/hand/control status without relying on the OpenCV debug window.
Static assets (CSS, JS, SVG) are served from the same port so the page works
out of the box.

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
import http
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("hands.status_server")

# websockets 13+ moved process_request to the new http11 Response API.
try:  # pragma: no cover - version dependent
    from websockets.http11 import Response as _WSResponse
    from websockets.datastructures import Headers as _WSHeaders

    _WSResponse_AVAILABLE = True
except ImportError:  # pragma: no cover - websockets 12.x
    _WSResponse = None  # type: ignore
    _WSHeaders = None  # type: ignore
    _WSResponse_AVAILABLE = False


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
        html_path: Optional[str] = None,
    ) -> None:
        self._host = host
        self._port = port
        self._broadcast_interval = broadcast_interval
        self._html_path = html_path or self._default_html_path()
        self._static_files = self._load_static_files()

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
            # Status card fields
            "hand_present": False,
            "hand_lost_duration": 0.0,
            "cooldown_until": 0.0,
            "intent_phase": "idle",
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
    def _default_html_path(self) -> str:
        module_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(module_dir, "frontend", "index.html")

    def _load_static_files(self) -> Dict[str, Tuple[bytes, str, http.HTTPStatus]]:
        """Load the status card page and its static assets into memory.

        The returned dictionary maps URL paths to ``(body, content_type, status)``.
        Missing assets produce a 404; a missing index.html specifically produces
        503 because the page is the primary product of this server.
        """
        frontend_dir = os.path.dirname(self._html_path)
        files: List[Tuple[str, str, str]] = [
            ("/", self._html_path, "text/html; charset=utf-8"),
            ("/styles.css", os.path.join(frontend_dir, "styles.css"), "text/css; charset=utf-8"),
            ("/app.js", os.path.join(frontend_dir, "app.js"), "application/javascript; charset=utf-8"),
            ("/radar.svg", os.path.join(frontend_dir, "radar.svg"), "image/svg+xml"),
        ]
        assets: Dict[str, Tuple[bytes, str, http.HTTPStatus]] = {}
        for path, filepath, content_type in files:
            try:
                with open(filepath, "rb") as f:
                    content = f.read()
                status = http.HTTPStatus.OK
            except Exception as exc:  # pragma: no cover - file may be missing
                logger.warning("static asset not found at %s: %r", filepath, exc)
                if path == "/":
                    content = b"Status card HTML not found."
                    content_type = "text/html; charset=utf-8"
                    status = http.HTTPStatus.SERVICE_UNAVAILABLE
                else:
                    content = f"Asset {path} not found.".encode("utf-8")
                    content_type = "text/plain; charset=utf-8"
                    status = http.HTTPStatus.NOT_FOUND
            assets[path] = (content, content_type, status)
        return assets

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
                process_request=self._process_request,
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
        logger.info(
            "status server listening on ws://%s:%s and http://%s:%s",
            self._host, self._port, self._host, self._port,
        )

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

    async def _process_request(self, *args: Any) -> Any:
        """HTTP request handler shared with the WebSocket server.

        ``websockets`` 12.x calls ``process_request(path, request_headers)`` and
        expects a ``(status, headers, body)`` tuple or ``None``.
        ``websockets`` 13+ calls ``process_request(connection, request)`` and
        expects a ``websockets.http11.Response`` object or ``None``.

        To avoid import-time version detection errors, we choose the return type
        based on the actual calling convention used by the server.
        """
        # Unpack the version-specific arguments and remember which style is used.
        if len(args) == 2 and hasattr(args[1], "path"):
            # websockets 13+: (connection, request)
            request = args[1]
            path = request.path
            headers = request.headers
            new_style = True
        elif len(args) >= 2:
            # websockets 12.x: (path, request_headers)
            path = args[0]
            headers = args[1]
            new_style = False
        elif len(args) >= 1:
            # websockets 12.x fallback
            path = args[0]
            headers = []
            new_style = False
        else:  # pragma: no cover - unexpected
            return None

        # Let WebSocket upgrade handshakes go through to the WebSocket handler.
        if self._is_websocket_upgrade(headers):
            return None

        if path in self._static_files:
            body, content_type, status = self._static_files[path]
            return self._build_response(status, body, content_type, new_style)

        # Unknown non-upgrade path.
        return self._build_response(
            http.HTTPStatus.NOT_FOUND,
            b"Not Found",
            "text/plain; charset=utf-8",
            new_style,
        )

    def _build_response(
        self,
        status: http.HTTPStatus,
        body: bytes,
        content_type: str,
        new_style: bool,
    ) -> Any:
        """Return either a ``websockets.http11.Response`` or a tuple.

        The format is chosen based on the calling convention detected in
        :meth:`_process_request`, not on an import-time version check, so we
        work on both legacy and new websockets implementations.
        """
        headers: List[Tuple[str, str]] = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
        ]
        if new_style and _WSResponse_AVAILABLE and _WSResponse is not None and _WSHeaders is not None:
            return _WSResponse(status.value, status.phrase, _WSHeaders(headers), body)
        return (status, headers, body)

    @staticmethod
    def _is_websocket_upgrade(headers: Any) -> bool:
        """Return True if the request is a WebSocket upgrade handshake."""
        # websockets 13+ Headers object supports get() with case-insensitive keys.
        if hasattr(headers, "get"):
            upgrade = headers.get("Upgrade", "")
            return isinstance(upgrade, str) and upgrade.lower() == "websocket"
        # websockets 12.x passes a list of (name, value) tuples.
        if isinstance(headers, list):
            for name, value in headers:
                if name.lower() == "upgrade" and value.lower() == "websocket":
                    return True
        return False

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
