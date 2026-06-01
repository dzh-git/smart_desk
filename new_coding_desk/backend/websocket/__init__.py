"""
WebSocket layer — room/connection management, broadcast, EventBus integration.

Per WEBSOCKET_PROTOCOL:
    - Endpoint: /ws/{meeting_id}
    - Server→client broadcast only (V1)
    - Business operations go through HTTP API
    - Room model: meeting_id → room → connections

Per system_architecture §4.5:
    - WebSocket layer contains NO business logic.
"""
from backend.websocket.ws_service import WebSocketService, ws_service
from backend.websocket.event_handler import WebSocketEventHandler

__all__ = ["WebSocketService", "ws_service", "WebSocketEventHandler"]
