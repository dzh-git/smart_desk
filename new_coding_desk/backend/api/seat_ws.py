"""
Seat Edge Agent WebSocket — /ws/seat/{seat_id}

Distributed-mode only (deploy_mode=distributed). Each seat's Windows terminal
runs a ``seat_agent`` that opens this WebSocket and keeps it alive for the
whole session. Two directions:

* Downlink (central -> agent): lighting commands, e.g.
      {"type":"lighting","cmd":"SET_MODE","arg":"meeting"}
  pushed by SeatGateway.send() whenever LightingManager decides a mode change.

* Uplink (agent -> central):
      {"type":"pir","seat_id":N,"occupied":true}     -> drives the seat state
                                                         machine (SeatService),
                                                         which publishes
                                                         SeatOccupiedEvent ->
                                                         LightingManager WELCOME.
      {"type":"status","seat_id":N,"connected":true, "current_mode":"IDLE"}
      {"type":"sync","seat_id":N}                    -> central replies with the
                                                         seat's current intended
                                                         mode.

On connect the central immediately pushes the seat's current intended mode so a
reconnecting agent resyncs its Arduino.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.database import SessionLocal
from backend.events import event_bus
from backend.exceptions import NotFoundError, ValidationError
from backend.hardware import get_seat_gateway, get_lighting_manager, seat_ids
from backend.hardware.seat_gateway import SeatGateway
from backend.services.meeting_service import MeetingService
from backend.services.seat_service import SeatService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["seat-agent"])


def _active_meeting_id(db) -> int | None:
    meeting = MeetingService(db, event_bus).get_active_meeting()
    return meeting.id if meeting else None


@router.websocket("/ws/seat/{seat_id}")
async def seat_agent_ws(ws: WebSocket, seat_id: int):
    """Bidirectional channel with one seat's Edge Agent."""
    gateway = get_seat_gateway()
    if not isinstance(gateway, SeatGateway):
        await ws.accept()
        await ws.close(code=1008, reason="central mode: seat agent WS disabled")
        return

    if seat_id not in seat_ids:
        await ws.accept()
        await ws.close(code=1008, reason=f"unknown seat_id {seat_id}")
        return

    await ws.accept()
    gateway.register(seat_id, ws)
    logger.info("[seat_ws] seat %d agent connected", seat_id)

    # Resync: push the seat's current intended mode immediately.
    lm = get_lighting_manager()
    mode = lm.seat_mode.get(seat_id, "IDLE") if lm else "IDLE"
    try:
        await ws.send_json({"type": "lighting", "cmd": "SET_MODE", "arg": mode})
    except Exception:
        logger.exception("[seat_ws] initial sync send failed seat=%d", seat_id)

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[seat_ws] bad json from seat %d: %r", seat_id, raw)
                continue

            mtype = msg.get("type")
            if mtype == "pir":
                await _handle_pir(seat_id, bool(msg.get("occupied", False)))
            elif mtype == "status":
                gateway.set_status(
                    seat_id,
                    bool(msg.get("connected", True)),
                    msg.get("current_mode"),
                    last_error=msg.get("last_error"),
                    last_ack_at=msg.get("last_ack_at"),
                    command_pending=msg.get("command_pending"),
                )
            elif mtype == "sync":
                lm2 = get_lighting_manager()
                mode2 = lm2.seat_mode.get(seat_id, "IDLE") if lm2 else "IDLE"
                await ws.send_json(
                    {"type": "lighting", "cmd": "SET_MODE", "arg": mode2}
                )
            else:
                logger.debug("[seat_ws] ignored msg type %r from seat %d", mtype, seat_id)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("[seat_ws] seat %d handler error", seat_id)
    finally:
        gateway.unregister(seat_id)
        gateway.set_status(seat_id, False)
        logger.info("[seat_ws] seat %d agent gone", seat_id)


async def _handle_pir(seat_id: int, occupied: bool) -> None:
    """Occupancy from hardware -> seat state machine -> EventBus -> lighting.

    Mirrors the dev endpoint: updates DB seat state and publishes
    SeatOccupiedEvent / SeatVacantEvent, which LightingManager subscribes to.
    """
    db = SessionLocal()
    try:
        mid = _active_meeting_id(db)
        svc = SeatService(db, event_bus)
        try:
            if occupied:
                svc.seat_occupied(seat_id, meeting_id=mid)
            else:
                svc.seat_vacant(seat_id, meeting_id=mid)
        except (NotFoundError, ValidationError) as exc:
            logger.warning("[seat_ws] seat %d occupancy rejected: %s", seat_id, exc)
    except Exception:
        logger.exception("[seat_ws] occupancy handling failed seat=%d", seat_id)
    finally:
        db.close()
