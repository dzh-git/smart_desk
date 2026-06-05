"""
WebSocket service — manages per-meeting connections.
"""
from __future__ import annotations
import json
from collections.abc import AsyncGenerator
from fastapi import WebSocket, WebSocketDisconnect


class Connection:
    def __init__(self, ws: WebSocket, seat_id: int = 0):
        self.ws = ws
        self.seat_id = seat_id


class MeetingRoom:
    def __init__(self, meeting_id: int):
        self.meeting_id = meeting_id
        self.connections: list[Connection] = []

    def add(self, conn: Connection):
        self.connections.append(conn)

    def remove(self, ws: WebSocket):
        self.connections = [c for c in self.connections if c.ws is not ws]

    @property
    def seat_ids(self) -> list[int]:
        return [c.seat_id for c in self.connections if c.seat_id > 0]

    async def broadcast(self, msg: dict, exclude_seat: int | None = None):
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

    async def send_to_seat(self, seat_id: int, msg: dict):
        payload = json.dumps(msg, ensure_ascii=False)
        for c in self.connections:
            if c.seat_id == seat_id:
                try:
                    await c.ws.send_text(payload)
                except Exception:
                    self.connections.remove(c)
                return


class WSService:
    """Manages WebSocket rooms per meeting."""

    def __init__(self):
        self.rooms: dict[int, MeetingRoom] = {}

    def get_or_create(self, meeting_id: int) -> MeetingRoom:
        if meeting_id not in self.rooms:
            self.rooms[meeting_id] = MeetingRoom(meeting_id)
        return self.rooms[meeting_id]

    def remove_room(self, meeting_id: int):
        self.rooms.pop(meeting_id, None)

    async def handle(self, ws: WebSocket, meeting_id: int, seat_id: int) -> AsyncGenerator[dict, None]:
        """Coroutine: accept connection, yield messages, cleanup on disconnect."""
        await ws.accept()
        room = self.get_or_create(meeting_id)
        conn = Connection(ws, seat_id)
        room.add(conn)

        # Notify others a seat joined
        await room.broadcast({
            "type": "seat_joined",
            "payload": {"seat_id": seat_id},
        }, exclude_seat=seat_id)

        try:
            while True:
                raw = await ws.receive_text()
                msg = json.loads(raw)
                msg["seat_id"] = seat_id
                yield msg
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            from backend.services.background_tasks import get_logger
            get_logger().info(f"WebSocket disconnected: meeting_id={meeting_id}, seat_id={seat_id}")
            room.remove(ws)
            await room.broadcast({
                "type": "seat_left",
                "payload": {"seat_id": seat_id},
            })


# Singleton
ws_svc = WSService()
