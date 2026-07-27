"""Black-box WebSocket framing tests for the direct ESP32 endpoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api import seat_ws
from backend.hardware.seat_gateway import SeatGateway


def make_client(monkeypatch):
    application = FastAPI()
    application.include_router(seat_ws.router)
    gateway = SeatGateway(None, list(range(1, 10)))
    transitions: list[tuple[int, bool]] = []

    async def fake_occupancy(seat_id: int, occupied: bool) -> None:
        transitions.append((seat_id, occupied))

    monkeypatch.setattr(seat_ws, "get_seat_gateway", lambda: gateway)
    monkeypatch.setattr(
        seat_ws,
        "_send_intended_mode",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        seat_ws,
        "_handle_occupancy",
        fake_occupancy,
    )
    return TestClient(application), gateway, transitions


def hello(**overrides):
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


def occupancy(**overrides):
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


def test_hello_occupancy_and_duplicate_are_acknowledged(monkeypatch):
    client, gateway, transitions = make_client(monkeypatch)
    with client.websocket_connect("/ws/seat/1") as websocket:
        websocket.send_json(hello())
        hello_ack = websocket.receive_json()
        assert hello_ack["type"] == "hello_ack"
        assert hello_ack["schema_version"] == 1

        websocket.send_json(occupancy())
        first_ack = websocket.receive_json()
        assert first_ack == {
            "schema_version": 1,
            "type": "event_ack",
            "event_id": "occupancy-0001",
            "accepted": True,
            "duplicate": False,
        }

        websocket.send_json(occupancy())
        duplicate_ack = websocket.receive_json()
        assert duplicate_ack["duplicate"] is True

    assert transitions == [(1, True)]
    assert gateway.is_connected(1) is False


def test_message_before_hello_is_rejected_and_closed(monkeypatch):
    client, _, transitions = make_client(monkeypatch)
    with client.websocket_connect("/ws/seat/1") as websocket:
        websocket.send_json(occupancy())
        error = websocket.receive_json()
        assert error["error_code"] == "HELLO_REQUIRED"
        try:
            websocket.receive_json()
        except WebSocketDisconnect as disconnect:
            assert disconnect.code == 1008
        else:
            raise AssertionError("WebSocket should close after HELLO_REQUIRED")
    assert transitions == []


def test_wrong_protocol_seat_is_rejected_and_closed(monkeypatch):
    client, _, _ = make_client(monkeypatch)
    with client.websocket_connect("/ws/seat/1") as websocket:
        websocket.send_json(hello(seat_id=2))
        error = websocket.receive_json()
        assert error["error_code"] == "SEAT_ID_MISMATCH"
        try:
            websocket.receive_json()
        except WebSocketDisconnect as disconnect:
            assert disconnect.code == 1008
        else:
            raise AssertionError("WebSocket should close after seat mismatch")
