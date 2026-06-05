"""
SpeechWSRegistry — tracks active /ws/speech WebSocket connections.

This registry ONLY manages speech uplink connections (per WEBSOCKET_PROTOCOL §3,
§7). It does NOT interact with the meeting broadcast channel or ws_service.

Responsibilities:
    - Register/unregister speech WS connections by (meeting_id, seat_id).
    - Close a speech WS from sync code (SeatService HTTP routes) via the
      captured main event loop.
    - Never touch broadcast rooms, stream_service sessions, or EventBus.

Connection lifecycle (Phase 5):
    handle_speech_ws() registers on accept, unregisters in finally block.
    close_seat() is called by SeatService when speaker seat changes,
    triggering the WS handler's natural cleanup path.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

from backend.websocket.event_handler import WebSocketEventHandler

logger = logging.getLogger(__name__)


class SpeechWSRegistry:
    """Registry for active speech WebSocket connections.

    Maps (meeting_id, seat_id) -> WebSocket for the speech uplink channel.
    All dict access happens on the asyncio event loop (WS handler thread)
    except close_seat() which can be called from sync HTTP routes.
    """

    def __init__(self) -> None:
        self._by_seat: dict[tuple[int, int], WebSocket] = {}
        self._by_ws: dict[int, tuple[int, int]] = {}
        # Phase 5: set of invalidated WS object ids — no longer allowed
        # to process business messages (speaker seat changed or duplicate
        # connection replaced them).
        self._invalidated: set[int] = set()

    # ── Public API ─────────────────────────────────────────────────────────────

    def register(self, meeting_id: int, seat_id: int, ws: WebSocket) -> None:
        """Register a speech WS connection.

        If an existing connection is already registered for the same key,
        the OLD connection is immediately invalidated and its close is
        scheduled on the event loop. The new connection replaces it.

        This prevents stale WS handlers from processing business messages
        after a newer connection takes over.
        """
        key = (meeting_id, seat_id)
        old_ws = self._by_seat.get(key)
        if old_ws is not None and old_ws is not ws:
            logger.warning(
                "Speech registry: closing duplicate WS for meeting=%d seat=%d",
                meeting_id, seat_id,
            )
            # Invalidate + close old connection so it stops processing
            self._invalidated.add(id(old_ws))
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._do_close(old_ws))
            except RuntimeError:
                loop = WebSocketEventHandler._main_loop
                if loop is not None and loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        self._do_close(old_ws), loop,
                    )
        self._by_seat[key] = ws
        self._by_ws[id(ws)] = key

    def unregister(self, meeting_id: int, seat_id: int, ws: WebSocket) -> None:
        """Remove a specific speech WS connection. Idempotent.

        Only removes if the stored WebSocket matches *ws* (identity check).
        This prevents a stale handler from removing a newer connection that
        was registered under the same key.
        """
        key = (meeting_id, seat_id)
        stored = self._by_seat.get(key)
        if stored is ws:
            self._by_seat.pop(key, None)
            self._by_ws.pop(id(ws), None)
        self._invalidated.discard(id(ws))

    def unregister_by_ws(self, ws: WebSocket) -> tuple[int, int] | None:
        """Remove a WS by its object identity.

        Only removes if the stored WebSocket matches *ws* (identity check).
        Returns (meeting_id, seat_id) if found, None otherwise.
        """
        wid = id(ws)
        key = self._by_ws.get(wid)
        if key is not None:
            stored = self._by_seat.get(key)
            if stored is ws:
                self._by_seat.pop(key, None)
                self._by_ws.pop(wid, None)
                self._invalidated.discard(wid)
                return key
        return None

    def get(self, meeting_id: int, seat_id: int) -> WebSocket | None:
        """Look up a speech WS by meeting and seat."""
        return self._by_seat.get((meeting_id, seat_id))

    def mark_invalidated(self, ws: WebSocket) -> None:
        """Mark a WS as invalidated — it should no longer process messages.

        The message loop in handle_speech_ws checks this flag before
        dispatching any business message (start, binary, end_hint).
        """
        self._invalidated.add(id(ws))

    def is_invalidated(self, ws: WebSocket) -> bool:
        """Check if a WS has been invalidated."""
        return id(ws) in self._invalidated

    def close_seat(self, meeting_id: int, seat_id: int) -> bool:
        """Schedule closing the speech WS for (meeting_id, seat_id).

        Thread-safe: can be called from sync HTTP route handlers.
        The actual close is scheduled on the main event loop.

        Registry and session cleanup happens in the WS handler's finally
        block — this method only triggers the close.

        Returns True if a connection was found and close was scheduled.
        """
        key = (meeting_id, seat_id)
        ws = self._by_seat.get(key)
        if ws is None:
            return False

        try:
            # Called from an async context (e.g. from within the WS handler)
            loop = asyncio.get_running_loop()
            loop.create_task(self._do_close(ws))
        except RuntimeError:
            # Called from sync code (HTTP route thread pool)
            loop = WebSocketEventHandler._main_loop
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._do_close(ws), loop,
                )
            else:
                logger.error(
                    "Speech registry: no event loop to close WS "
                    "for meeting=%d seat=%d",
                    meeting_id, seat_id,
                )
                return False
        return True

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _do_close(self, ws: WebSocket) -> None:
        """Close a speech WebSocket.

        Only the close itself — registry cleanup is handled by the WS
        handler's finally block (unregister + remove_session).
        """
        try:
            await ws.close(code=4001)
        except Exception:
            pass

    # ── Introspection ──────────────────────────────────────────────────────────

    @property
    def active_connections(self) -> list[tuple[int, int]]:
        """List all active (meeting_id, seat_id) pairs."""
        return list(self._by_seat.keys())


# Module-level singleton — shared across all speech WS connections.
speech_registry = SpeechWSRegistry()
