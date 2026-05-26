from __future__ import annotations
from fastapi import WebSocket
import json


import asyncio
import threading


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list] = {}  # meeting_id → [ws, ...]
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, meeting_id: str, ws):
        await ws.accept()
        self._connections.setdefault(meeting_id, []).append(ws)

    def disconnect(self, meeting_id: str, ws):
        socks = self._connections.get(meeting_id)
        if socks:
            socks.remove(ws)

    async def broadcast(self, meeting_id: str, msg_type: str, data: dict):
        socks = self._connections.get(meeting_id, [])
        payload = json.dumps({"type": msg_type, "data": data}, ensure_ascii=False)
        stale = []
        for ws in socks:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(meeting_id, ws)

    def broadcast_sync(self, meeting_id: str, msg_type: str, data: dict):
        """Sync wrapper — runs broadcast in a daemon thread with its own event loop."""
        def _run():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.broadcast(meeting_id, msg_type, data))
            finally:
                loop.close()
        t = threading.Thread(target=_run, daemon=True)
        t.start()


manager = ConnectionManager()
