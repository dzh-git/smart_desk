"""ESP32 protocol validation, ordering, ACK, and compatibility tests."""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import Future

import pytest

from backend.api import seat_ws
from backend.hardware.esp32_protocol import (
    COMMAND_ACK_TIMEOUT_SECONDS,
    MAX_MESSAGE_BYTES,
    ProtocolViolation,
    decode_uplink,
)
from backend.hardware.seat_gateway import SeatGateway


def hello(**overrides) -> dict:
    message = {
        "schema_version": 1,
        "type": "hello",
        "seat_id": 1,
        "device_id": "esp32-seat-01",
        "firmware_version": "0.1.0",
        "boot_id": "boot-0001",
        "capabilities": ["pir", "vl53l0x", "ws2812b"],
    }
    message.update(overrides)
    return message


def occupancy(**overrides) -> dict:
    message = {
        "schema_version": 1,
        "type": "occupancy",
        "seat_id": 1,
        "sequence": 1,
        "event_id": "occupancy-0001",
        "occupied": True,
        "pir": True,
        "distance_mm": 72,
        "sensor_ok": True,
    }
    message.update(overrides)
    return message


class FakeWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


def immediate_schedule(coroutine, _loop):
    asyncio.run(coroutine)
    future = Future()
    future.set_result(None)
    return future


def test_valid_hello_and_occupancy_decode():
    assert decode_uplink(json.dumps(hello()), 1)["device_id"] == "esp32-seat-01"
    assert decode_uplink(json.dumps(occupancy()), 1)["distance_mm"] == 72


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (hello(schema_version=2), "UNSUPPORTED_SCHEMA_VERSION"),
        (hello(seat_id=2), "SEAT_ID_MISMATCH"),
        (occupancy(distance_mm=9000), "FIELD_INVALID"),
        (occupancy(occupied="yes"), "FIELD_INVALID"),
        ({"schema_version": 1, "type": "unknown", "seat_id": 1}, "TYPE_UNSUPPORTED"),
    ],
)
def test_invalid_protocol_messages_are_rejected(message, code):
    with pytest.raises(ProtocolViolation) as captured:
        decode_uplink(json.dumps(message), 1)
    assert captured.value.code == code


def test_message_size_limit_is_enforced():
    raw = json.dumps(hello()) + (" " * MAX_MESSAGE_BYTES)
    with pytest.raises(ProtocolViolation) as captured:
        decode_uplink(raw, 1)
    assert captured.value.code == "MESSAGE_TOO_LARGE"
    assert captured.value.fatal is True


def test_duplicate_and_out_of_order_occupancy_are_distinguished():
    gateway = SeatGateway(None, [1])
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0001",
    )
    assert (
        gateway.accept_occupancy_event(
            1,
            event_id="occupancy-0001",
            sequence=10,
        )
        == "accepted"
    )
    assert (
        gateway.accept_occupancy_event(
            1,
            event_id="occupancy-0001",
            sequence=10,
        )
        == "duplicate"
    )
    assert (
        gateway.accept_occupancy_event(
            1,
            event_id="occupancy-0002",
            sequence=9,
        )
        == "out_of_order"
    )


def test_new_boot_resets_sequence_but_keeps_event_id_cache():
    gateway = SeatGateway(None, [1])
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0001",
    )
    assert gateway.accept_occupancy_event(
        1,
        event_id="occupancy-0001",
        sequence=50,
    ) == "accepted"
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0002",
    )
    assert gateway.accept_occupancy_event(
        1,
        event_id="occupancy-0002",
        sequence=1,
    ) == "accepted"
    assert gateway.accept_occupancy_event(
        1,
        event_id="occupancy-0001",
        sequence=2,
    ) == "duplicate"


def test_lighting_command_ack_and_duplicate_ack(monkeypatch):
    monkeypatch.setattr(
        "backend.hardware.seat_gateway.asyncio.run_coroutine_threadsafe",
        immediate_schedule,
    )
    websocket = FakeWebSocket()
    gateway = SeatGateway(object(), [1])
    gateway.register(1, websocket)
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0001",
    )

    assert gateway.send(1, "SET_MODE", "WELCOME") is True
    command = websocket.messages[-1]
    assert command["schema_version"] == 1
    assert command["type"] == "lighting"
    assert command["mode"] == "WELCOME"
    assert gateway.diagnostics(1)["command_pending"] is True

    result = gateway.acknowledge_command(
        1,
        command_id=command["command_id"],
        success=True,
        current_mode="WELCOME",
    )
    assert result == "applied"
    assert gateway.reported_mode(1) == "WELCOME"
    assert gateway.diagnostics(1)["command_pending"] is False
    assert gateway.acknowledge_command(
        1,
        command_id=command["command_id"],
        success=True,
        current_mode="WELCOME",
    ) == "duplicate"


def test_lost_ack_retries_same_command_id_then_times_out(monkeypatch):
    monkeypatch.setattr(
        "backend.hardware.seat_gateway.asyncio.run_coroutine_threadsafe",
        immediate_schedule,
    )
    websocket = FakeWebSocket()
    gateway = SeatGateway(object(), [1])
    gateway.register(1, websocket)
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0001",
    )
    assert gateway.send(1, "SET_MODE", "MEETING_ACTIVE") is True
    first = websocket.messages[-1]
    now = gateway._pending_command[1]["sent_at"]

    assert gateway.retry_due_command(
        1,
        now=now + COMMAND_ACK_TIMEOUT_SECONDS,
    ) == "retried"
    assert websocket.messages[-1]["command_id"] == first["command_id"]
    assert gateway.retry_due_command(
        1,
        now=now + COMMAND_ACK_TIMEOUT_SECONDS * 2,
    ) == "retried"
    assert gateway.retry_due_command(
        1,
        now=now + COMMAND_ACK_TIMEOUT_SECONDS * 3,
    ) == "failed"
    assert gateway.diagnostics(1)["last_error"] == "COMMAND_ACK_TIMEOUT"


def test_legacy_windows_agent_command_shape_is_preserved(monkeypatch):
    monkeypatch.setattr(
        "backend.hardware.seat_gateway.asyncio.run_coroutine_threadsafe",
        immediate_schedule,
    )
    websocket = FakeWebSocket()
    gateway = SeatGateway(object(), [1])
    gateway.register(1, websocket)
    gateway.configure_legacy_session(1)

    assert gateway.send(1, "SET_MODE", "IDLE") is True
    assert websocket.messages == [
        {"type": "lighting", "cmd": "SET_MODE", "arg": "IDLE"}
    ]


def test_heartbeat_timeout_only_applies_to_esp32():
    gateway = SeatGateway(None, [1])
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0001",
    )
    last = gateway.diagnostics(1)["last_heartbeat_at"]
    assert gateway.heartbeat_expired(1, now=last + 60) is True
    gateway.configure_legacy_session(1)
    assert gateway.heartbeat_expired(1, now=last + 60) is False


def test_lighting_only_firmware_clears_legacy_sensor_diagnostics():
    gateway = SeatGateway(None, [1])
    gateway.record_occupancy_evidence(
        1,
        pir=True,
        distance_mm=72,
        sensor_ok=True,
    )

    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.3.0",
        boot_id="boot-0002",
        capabilities=["ws2812b"],
    )

    diagnostics = gateway.diagnostics(1)
    assert diagnostics["pir"] is None
    assert diagnostics["distance_mm"] is None
    assert diagnostics["sensor_ok"] is None


def test_endpoint_handler_acknowledges_duplicate_without_second_transition(
    monkeypatch,
):
    websocket = FakeWebSocket()
    gateway = SeatGateway(None, [1])
    gateway.configure_esp32_session(
        1,
        device_id="esp32-seat-01",
        firmware_version="0.1.0",
        boot_id="boot-0001",
    )
    transitions: list[tuple[int, bool]] = []

    async def fake_transition(seat_id: int, occupied: bool) -> None:
        transitions.append((seat_id, occupied))

    monkeypatch.setattr(seat_ws, "_handle_occupancy", fake_transition)
    message = occupancy()
    asyncio.run(
        seat_ws._handle_esp32_message(
            websocket,
            gateway,
            1,
            message,
        )
    )
    asyncio.run(
        seat_ws._handle_esp32_message(
            websocket,
            gateway,
            1,
            message,
        )
    )

    assert transitions == [(1, True)]
    assert websocket.messages[-1]["duplicate"] is True
