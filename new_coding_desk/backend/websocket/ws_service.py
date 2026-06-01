"""
WebSocketService — per-meeting room and connection management.

Per WEBSOCKET_PROTOCOL §2-8, §11:
    Interface:
        connect(meeting_id, websocket)     → accept + add to room
        disconnect(meeting_id, websocket)  → remove from room
        broadcast(meeting_id, message)     → send to all in room

Per §12: WebSocketService is called ONLY by WebSocketEventHandler,
never directly by Services.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class Connection:
    """A single WebSocket client connection."""

    def __init__(self, ws: WebSocket, seat_id: int = 0) -> None:
        self.ws = ws
        self.seat_id = seat_id


class MeetingRoom:
    """All connections for one meeting."""

    def __init__(self, meeting_id: int) -> None:
        self.meeting_id = meeting_id
        self.connections: list[Connection] = []

    def add(self, conn: Connection) -> None:
        self.connections.append(conn)

    def remove(self, ws: WebSocket) -> None:
        self.connections = [c for c in self.connections if c.ws is not ws]

    @property
    def seat_ids(self) -> list[int]:
        return [c.seat_id for c in self.connections if c.seat_id > 0]

    async def broadcast(self, msg: dict, *, exclude_seat: int | None = None) -> None:
        """Send message to all connections in this room.

        Silently removes dead connections.
        """
        dead: list[Connection] = []
        payload = json.dumps(msg, ensure_ascii=False)
        for c in self.connections:
            if exclude_seat is not None and c.seat_id == exclude_seat:
                continue
            try:
                await c.ws.send_text(payload)
            except Exception:
                dead.append(c)
        for d in dead:
            self.connections.remove(d)

class WebSocketService:
    """Manages WebSocket rooms keyed by meeting_id.

    Per WEBSOCKET_PROTOCOL §7: one room per meeting.
    Per §4: sends `connected` event on successful connection.
    """

    def __init__(self) -> None:
        self.rooms: dict[int, MeetingRoom] = {}

    # ── Room management ─────────────────────────────────────────────────────

    def get_or_create(self, meeting_id: int) -> MeetingRoom:
        if meeting_id not in self.rooms:
            self.rooms[meeting_id] = MeetingRoom(meeting_id)
        return self.rooms[meeting_id]

    def remove_room(self, meeting_id: int) -> None:
        self.rooms.pop(meeting_id, None)

    # ── Connection lifecycle ────────────────────────────────────────────────

    async def connect(self, ws: WebSocket, meeting_id: int, seat_id: int = 0) -> None:
        """Accept connection, add to room, send `connected` event.

        Per WEBSOCKET_PROTOCOL §4.
        """
        import time

        await ws.accept()
        room = self.get_or_create(meeting_id)
        conn = Connection(ws, seat_id)
        room.add(conn)

        # §4: server sends `connected` on successful connection
        await ws.send_text(json.dumps({
            "event": "connected",
            "meeting_id": meeting_id,
            "timestamp": int(time.time()),
            "payload": {},
        }, ensure_ascii=False))

    async def disconnect(self, ws: WebSocket, meeting_id: int) -> None:
        """Remove connection from its room.

        Per §4: disconnect sends no business event.
        """
        room = self.rooms.get(meeting_id)
        if room:
            room.remove(ws)
            if not room.connections:
                self.remove_room(meeting_id)

    # ── Broadcast ───────────────────────────────────────────────────────────

    async def broadcast(self, meeting_id: int, message: dict) -> None:
        """Broadcast to all connections in a meeting room.

        Per §5: message format = {event, meeting_id, timestamp, payload}.
        Called ONLY by WebSocketEventHandler.
        """
        room = self.rooms.get(meeting_id)
        if room is None:
            logger.warning("broadcast to unknown meeting_id=%d", meeting_id)
            return
        await room.broadcast(message)

    # ── WS endpoint handler ─────────────────────────────────────────────────

    async def handle(
        self, ws: WebSocket, meeting_id: int, seat_id: int,
    ) -> AsyncGenerator[dict, None]:
        """Coroutine: accepts WS connection, yields incoming client messages.

        Per §1: client→server business operations go through HTTP API.
        V1 WS only receives pings from client (no business messages).

        Yields parsed JSON dicts for any message the client sends.
        """
        await self.connect(ws, meeting_id, seat_id)

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                yield msg
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await self.disconnect(ws, meeting_id)


# Singleton
ws_service = WebSocketService()
