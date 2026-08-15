"""
Seat hardware WebSocket — /ws/seat/{seat_id}

Network-hardware modes accept both the legacy Windows Seat Agent and the
versioned ESP32 direct protocol. ESP32 is the production path; legacy messages
remain available for the Windows/Arduino test bench.

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

import asyncio
import json
import logging
import os
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.database import SessionLocal
from backend.events import event_bus
from backend.exceptions import NotFoundError, ValidationError
from backend.hardware import (
    deploy_mode,
    get_seat_gateway,
    get_lighting_manager,
    seat_ids,
)
from backend.hardware.esp32_protocol import (
    ProtocolViolation,
    decode_uplink,
    event_ack_message,
    hello_ack_message,
    protocol_error_message,
)
from backend.hardware.seat_gateway import SeatGateway
from backend.services.meeting_service import MeetingService
from backend.services.seat_service import SeatService
from backend.security.device_auth import (
    DeviceAuthenticationError,
    authenticate_esp32_device,
)
from backend.security.version_compat import (
    meets_minimum_version,
    parse_semantic_version,
)
from backend.security.structured_log import log_security_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["seat-agent"])


def _active_meeting_id(db) -> int | None:
    meeting = MeetingService(db, event_bus).get_active_meeting()
    return meeting.id if meeting else None


@router.websocket("/ws/seat/{seat_id}")
async def seat_agent_ws(ws: WebSocket, seat_id: int):
    """Bidirectional channel with one ESP32 or legacy Windows Seat Agent."""
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
    authorization = ws.headers.get("authorization")
    esp32_ready = False
    legacy_ready = False
    registered = False

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.receive_text(),
                    timeout=1.0,
                )
            except asyncio.TimeoutError:
                gateway.retry_due_command(seat_id)
                if gateway.heartbeat_expired(seat_id):
                    gateway.mark_heartbeat_timeout(seat_id)
                    await ws.close(
                        code=1011,
                        reason="ESP32 heartbeat timeout",
                    )
                    break
                continue

            legacy = _decode_legacy_message(raw)
            if legacy is not None:
                if deploy_mode == "esp32":
                    await _send_protocol_error(
                        ws,
                        ProtocolViolation(
                            "LEGACY_PROTOCOL_DISABLED",
                            (
                                "legacy Windows Seat Agent protocol is "
                                "disabled in esp32 mode"
                            ),
                            fatal=True,
                        ),
                    )
                    break
                if esp32_ready:
                    await _send_protocol_error(
                        ws,
                        ProtocolViolation(
                            "PROTOCOL_MIXED",
                            "legacy messages cannot follow ESP32 hello",
                            fatal=True,
                        ),
                    )
                    break
                if not legacy_ready:
                    gateway.register(seat_id, ws)
                    registered = True
                    gateway.configure_legacy_session(seat_id)
                    legacy_ready = True
                    logger.info(
                        "[seat_ws] seat %d legacy transport authenticated",
                        seat_id,
                    )
                    _send_intended_mode(gateway, seat_id)
                await _handle_legacy_message(
                    gateway,
                    seat_id,
                    legacy,
                )
                continue

            try:
                msg = decode_uplink(raw, seat_id)
                message_type = msg["type"]
                if message_type == "hello":
                    if legacy_ready:
                        raise ProtocolViolation(
                            "PROTOCOL_MIXED",
                            "ESP32 hello cannot follow legacy messages",
                            fatal=True,
                        )
                    if deploy_mode == "esp32":
                        try:
                            authenticate_esp32_device(
                                device_id=msg["device_id"],
                                seat_id=seat_id,
                                authorization=authorization,
                            )
                        except DeviceAuthenticationError as error:
                            log_security_event(
                                logger,
                                event="esp32_authentication",
                                level=logging.WARNING,
                                seat_id=seat_id,
                                device_id=msg["device_id"],
                                result=error.code,
                            )
                            raise ProtocolViolation(
                                error.code,
                                "ESP32 device authentication failed",
                                fatal=True,
                            ) from error
                        minimum_firmware = os.environ.get(
                            "SMARTDESK_ESP32_MIN_FIRMWARE_VERSION",
                            "0.1.0",
                        )
                        if parse_semantic_version(
                            msg["firmware_version"]
                        ) is None:
                            raise ProtocolViolation(
                                "FIRMWARE_VERSION_INVALID",
                                (
                                    "ESP32 firmware_version must use "
                                    "semantic versioning"
                                ),
                                fatal=True,
                            )
                        if not meets_minimum_version(
                            msg["firmware_version"],
                            minimum_firmware,
                        ):
                            raise ProtocolViolation(
                                "FIRMWARE_VERSION_UNSUPPORTED",
                                (
                                    "ESP32 firmware is older than the "
                                    "minimum supported version"
                                ),
                                fatal=True,
                            )
                    gateway.register(seat_id, ws)
                    registered = True
                    gateway.configure_esp32_session(
                        seat_id,
                        device_id=msg["device_id"],
                        firmware_version=msg["firmware_version"],
                        boot_id=msg["boot_id"],
                        capabilities=msg["capabilities"],
                    )
                    esp32_ready = True
                    log_security_event(
                        logger,
                        event="esp32_authentication",
                        seat_id=seat_id,
                        device_id=msg["device_id"],
                        firmware_version=msg["firmware_version"],
                        result="accepted",
                    )
                    await ws.send_json(
                        hello_ack_message(str(uuid.uuid4()))
                    )
                    _send_intended_mode(gateway, seat_id)
                    continue
                if not esp32_ready:
                    raise ProtocolViolation(
                        "HELLO_REQUIRED",
                        "hello must be the first ESP32 message",
                        fatal=True,
                    )
                await _handle_esp32_message(
                    ws,
                    gateway,
                    seat_id,
                    msg,
                )
            except ProtocolViolation as error:
                await _send_protocol_error(ws, error)
                if error.fatal:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("[seat_ws] seat %d handler error", seat_id)
    finally:
        if registered:
            gateway.unregister(seat_id)
            logger.info("[seat_ws] seat %d agent gone", seat_id)


def _decode_legacy_message(raw: str) -> dict | None:
    """Return a legacy message, or None when it belongs to protocol v1."""
    if len(raw.encode("utf-8")) > 4096:
        return None
    try:
        message = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if (
        isinstance(message, dict)
        and "schema_version" not in message
        and message.get("type") in {"pir", "status", "sync"}
    ):
        return message
    return None


def _send_intended_mode(gateway: SeatGateway, seat_id: int) -> None:
    manager = get_lighting_manager()
    mode = (
        manager.seat_mode.get(seat_id, "IDLE")
        if manager is not None
        else "IDLE"
    )
    gateway.send(seat_id, "SET_MODE", mode)


async def _send_protocol_error(
    ws: WebSocket,
    error: ProtocolViolation,
) -> None:
    await ws.send_json(protocol_error_message(error))
    if error.fatal:
        await ws.close(code=1008, reason=error.code)


async def _handle_legacy_message(
    gateway: SeatGateway,
    seat_id: int,
    message: dict,
) -> None:
    message_type = message.get("type")
    if message_type == "pir":
        await _handle_occupancy(
            seat_id,
            bool(message.get("occupied", False)),
        )
    elif message_type == "status":
        gateway.set_status(
            seat_id,
            bool(message.get("connected", True)),
            message.get("current_mode"),
            last_error=message.get("last_error"),
            last_ack_at=message.get("last_ack_at"),
            command_pending=message.get("command_pending"),
        )
    elif message_type == "sync":
        _send_intended_mode(gateway, seat_id)


async def _handle_esp32_message(
    ws: WebSocket,
    gateway: SeatGateway,
    seat_id: int,
    message: dict,
) -> None:
    message_type = message["type"]
    sequence = message["sequence"]
    if message_type == "occupancy":
        disposition = gateway.accept_occupancy_event(
            seat_id,
            event_id=message["event_id"],
            sequence=sequence,
        )
        if disposition == "duplicate":
            await ws.send_json(
                event_ack_message(
                    message["event_id"],
                    accepted=True,
                    duplicate=True,
                )
            )
            return
        if disposition == "out_of_order":
            await ws.send_json(
                event_ack_message(
                    message["event_id"],
                    accepted=False,
                    error_code="SEQUENCE_OUT_OF_ORDER",
                )
            )
            return
        gateway.record_occupancy_evidence(
            seat_id,
            pir=message["pir"],
            distance_mm=message.get("distance_mm"),
            sensor_ok=message.get("sensor_ok"),
        )
        await _handle_occupancy(seat_id, message["occupied"])
        await ws.send_json(
            event_ack_message(message["event_id"], accepted=True)
        )
        return

    if message_type == "command_ack":
        if not gateway.accept_sequence(seat_id, sequence):
            if gateway.is_duplicate_command_ack(
                seat_id,
                message["command_id"],
            ):
                return
            raise ProtocolViolation(
                "SEQUENCE_OUT_OF_ORDER",
                "command_ack sequence is not newer",
            )
        gateway.acknowledge_command(
            seat_id,
            command_id=message["command_id"],
            success=message["success"],
            current_mode=message["current_mode"],
            error_code=message.get("error_code"),
        )
        return

    if message_type == "sensor_error":
        disposition = gateway.accept_event(
            seat_id,
            event_id=message["event_id"],
            sequence=sequence,
        )
        if disposition == "duplicate":
            await ws.send_json(
                event_ack_message(
                    message["event_id"],
                    accepted=True,
                    duplicate=True,
                )
            )
            return
        if disposition == "out_of_order":
            await ws.send_json(
                event_ack_message(
                    message["event_id"],
                    accepted=False,
                    error_code="SEQUENCE_OUT_OF_ORDER",
                )
            )
            return
        gateway.record_sensor_error(
            seat_id,
            component=message["component"],
            error_code=message["error_code"],
        )
        await ws.send_json(
            event_ack_message(message["event_id"], accepted=True)
        )
        return

    if not gateway.accept_sequence(seat_id, sequence):
        raise ProtocolViolation(
            "SEQUENCE_OUT_OF_ORDER",
            "message sequence is not newer",
        )
    if message_type == "heartbeat":
        gateway.record_heartbeat(
            seat_id,
            mode=message["current_mode"],
            sensor_ok=message.get("sensor_ok"),
        )
    elif message_type == "sync":
        _send_intended_mode(gateway, seat_id)


async def _handle_occupancy(seat_id: int, occupied: bool) -> None:
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
