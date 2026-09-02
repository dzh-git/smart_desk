"""Twenty-round software-only seat 1 integration closure.

The test uses the real REST routes, SeatService, event bus, WebSocket broadcast
adapter, LightingManager, ESP32 simulator, command ACK path, and durable
identity idempotency table. Camera and hardware evidence are replay fixtures,
not claims of physical validation.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.api import hardware as hardware_api
from backend.api import seat_ws
from backend.api import seats as seats_api
from backend.events import event_bus
from backend.hardware import set_lighting_manager, set_seat_gateway
from backend.hardware.esp32_protocol import decode_uplink
from backend.hardware.lighting_manager import LightingManager
from backend.hardware.seat_gateway import SeatGateway
from backend.main import app
from backend.models.identity_checkin_event import IdentityCheckInEvent
from backend.models.seat_state import SeatState
from backend.services.tablet_device_service import TabletDeviceService
from backend.websocket.event_handler import WebSocketEventHandler
from backend.websocket.ws_service import Connection, ws_service
from esp32_seat_controller.simulator import Esp32SeatSimulator
from tests.conftest import TestSessionLocal

ROUND_COUNT = 20
DEVICE_TOKEN = "seat1-integration-device-token-0001"
FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "android_identity_verified.json"
)
client = TestClient(app)


class CaptureWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self._lock = threading.Lock()

    async def send_text(self, payload: str) -> None:
        with self._lock:
            self.messages.append(json.loads(payload))

    def event_count(self, event_name: str) -> int:
        with self._lock:
            return sum(
                item.get("event") == event_name
                for item in self.messages
            )


class SimulatorTransport:
    def __init__(self, simulator: Esp32SeatSimulator) -> None:
        self.simulator = simulator
        self.downlink: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.downlink.append(message)
        await self.simulator.handle_server_message(message)


class AckWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


def _start_broadcast_loop():
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()

    thread = threading.Thread(
        target=run,
        name="seat1-integration-broadcast",
        daemon=True,
    )
    thread.start()
    assert ready.wait(timeout=2)
    return loop, thread


def _stop_broadcast_loop(
    loop: asyncio.AbstractEventLoop,
    thread: threading.Thread,
) -> None:
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    assert not thread.is_alive()
    loop.close()


def _wait_for_event(
    capture: CaptureWebSocket,
    event_name: str,
    expected_count: int,
) -> None:
    deadline = time.time() + 2
    while time.time() < deadline:
        if capture.event_count(event_name) >= expected_count:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"timed out waiting for {event_name} #{expected_count}"
    )


def _immediate_schedule(coroutine, _loop):
    asyncio.run(coroutine)
    future = Future()
    future.set_result(None)
    return future


def _create_hardware(monkeypatch, simulator):
    holder: dict[str, SeatGateway] = {}

    async def uplink(message: dict) -> None:
        decode_uplink(json.dumps(message), 1)
        gateway = holder["gateway"]
        if message["type"] == "command_ack":
            if gateway.accept_sequence(1, message["sequence"]):
                gateway.acknowledge_command(
                    1,
                    command_id=message["command_id"],
                    success=message["success"],
                    current_mode=message["current_mode"],
                    error_code=message.get("error_code"),
                )

    simulator._sender = uplink
    simulator.protocol_ready = True
    transport = SimulatorTransport(simulator)
    gateway = SeatGateway(object(), [1])
    holder["gateway"] = gateway
    gateway.register(1, transport)
    gateway.configure_esp32_session(
        1,
        device_id=simulator.device_id,
        firmware_version=simulator.firmware_version,
        boot_id=simulator.boot_id,
    )
    manager = LightingManager(gateway)
    monkeypatch.setattr(manager, "_schedule", lambda *_args: None)
    manager.register()
    set_seat_gateway(gateway)
    set_lighting_manager(manager)
    monkeypatch.setattr(hardware_api, "deploy_mode", "esp32")
    monkeypatch.setattr(hardware_api, "seat_ids", [1])
    return gateway, manager, transport


def _provision_tablet() -> None:
    db = TestSessionLocal()
    try:
        TabletDeviceService(db).provision(
            device_id="tablet-seat-01",
            seat_id=1,
            token=DEVICE_TOKEN,
        )
    finally:
        db.close()


def _replay_identity(
    *,
    person_code: str,
    event_id: str,
) -> tuple[dict, dict]:
    envelope = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    envelope["eventId"] = event_id
    envelope["data"]["personId"] = person_code
    payload = {
        "eventId": envelope["eventId"],
        "eventTimestamp": int(time.time() * 1000),
        "personCode": envelope["data"]["personId"],
        "deviceId": "tablet-seat-01",
        "deviceSeatId": 1,
        "status": envelope["data"]["status"],
        "similarity": envelope["data"]["similarity"],
        "thresholdStatus": envelope["data"]["thresholdStatus"],
        "verificationLevel": envelope["data"]["verificationLevel"],
        "modelVersion": envelope["data"]["modelVersion"],
    }
    return payload, {
        "X-SmartDesk-Device-Token": DEVICE_TOKEN,
    }


def test_seat1_twenty_round_full_software_closure(monkeypatch):
    seats_api.identity_rate_limiter.clear()
    monkeypatch.setattr(
        "backend.hardware.seat_gateway.asyncio.run_coroutine_threadsafe",
        _immediate_schedule,
    )
    _provision_tablet()
    simulator = Esp32SeatSimulator(1)
    gateway, manager, transport = _create_hardware(
        monkeypatch,
        simulator,
    )

    broadcast_loop, broadcast_thread = _start_broadcast_loop()
    old_main_loop = WebSocketEventHandler._main_loop
    WebSocketEventHandler._main_loop = broadcast_loop
    broadcast_handler = WebSocketEventHandler()
    broadcast_events = {
        "meeting_started",
        "seat_occupied",
        "check_in",
        "meeting_ended",
    }
    for event_name in broadcast_events:
        event_bus.subscribe(event_name, broadcast_handler)

    try:
        for round_index in range(1, ROUND_COUNT + 1):
            if round_index == 11:
                manager.unregister()
                gateway.unregister(1)
                gateway, manager, transport = _create_hardware(
                    monkeypatch,
                    simulator,
                )

            person_code = f"seat1-person-{round_index:02d}"
            person = client.post(
                "/api/people",
                json={
                    "id": person_code,
                    "name": f"Seat One Person {round_index}",
                },
            )
            assert person.status_code == 201

            meeting_response = client.post(
                "/api/meetings",
                json={"title": f"Seat 1 Integration {round_index}"},
            )
            assert meeting_response.status_code == 201
            meeting_id = meeting_response.json()["data"]["id"]

            attendee_response = client.post(
                f"/api/meetings/{meeting_id}/attendees",
                json={
                    "name": f"Seat One Person {round_index}",
                    "title": "Integration Fixture",
                    "personId": person_code,
                },
            )
            assert attendee_response.status_code == 200
            attendee_id = attendee_response.json()["data"]["id"]

            assignment_response = client.put(
                f"/api/meetings/{meeting_id}/seat-assignments/1",
                json={"attendeeId": attendee_id},
            )
            assert assignment_response.status_code == 200

            admin_ws = CaptureWebSocket()
            seat_ws_capture = CaptureWebSocket()
            room = ws_service.get_or_create(meeting_id)
            room.add(Connection(admin_ws, seat_id=0))
            room.add(Connection(seat_ws_capture, seat_id=1))

            start = client.post(f"/api/meetings/{meeting_id}/start")
            assert start.status_code == 200
            _wait_for_event(admin_ws, "meeting_started", 1)
            assert simulator.current_mode == "MEETING_ACTIVE"
            assert gateway.diagnostics(1)["command_pending"] is False

            occupancy_message = simulator.occupancy_message(True)
            occupancy_ack = AckWebSocket()
            asyncio.run(
                seat_ws._handle_esp32_message(
                    occupancy_ack,
                    gateway,
                    1,
                    occupancy_message,
                )
            )
            assert occupancy_ack.messages[-1]["accepted"] is True
            _wait_for_event(admin_ws, "seat_occupied", 1)
            _wait_for_event(seat_ws_capture, "seat_occupied", 1)

            duplicate_ack = AckWebSocket()
            asyncio.run(
                seat_ws._handle_esp32_message(
                    duplicate_ack,
                    gateway,
                    1,
                    occupancy_message,
                )
            )
            assert duplicate_ack.messages[-1]["duplicate"] is True
            assert admin_ws.event_count("seat_occupied") == 1

            out_of_order = simulator.occupancy_message(
                False,
                sequence=occupancy_message["sequence"] - 1,
            )
            out_of_order_ack = AckWebSocket()
            asyncio.run(
                seat_ws._handle_esp32_message(
                    out_of_order_ack,
                    gateway,
                    1,
                    out_of_order,
                )
            )
            assert out_of_order_ack.messages[-1]["accepted"] is False
            assert (
                out_of_order_ack.messages[-1]["error_code"]
                == "SEQUENCE_OUT_OF_ORDER"
            )

            identity_event_id = f"identity-{uuid4().hex}"
            identity_payload, identity_headers = _replay_identity(
                person_code=person_code,
                event_id=identity_event_id,
            )
            checkin = client.post(
                "/api/seats/1/identity-checkin",
                json=identity_payload,
                headers=identity_headers,
            )
            assert checkin.status_code == 200
            assert checkin.json()["data"] == {
                "seat_id": 1,
                "status": "checked_in",
                "attendee_id": attendee_id,
                "updated_at": checkin.json()["data"]["updated_at"],
            }
            _wait_for_event(admin_ws, "check_in", 1)
            _wait_for_event(seat_ws_capture, "check_in", 1)

            retry = client.post(
                "/api/seats/1/identity-checkin",
                json=identity_payload,
                headers=identity_headers,
            )
            assert retry.status_code == 200
            time.sleep(0.02)
            assert admin_ws.event_count("check_in") == 1

            seats = client.get("/api/seats").json()["data"]
            assert seats[0]["status"] == "checked_in"
            assert seats[0]["attendee_id"] == attendee_id
            attendees = client.get(
                f"/api/meetings/{meeting_id}/attendees"
            ).json()["data"]
            assert attendees[0]["checked_in"] is True
            assert attendees[0]["seat_id"] == 1

            hardware = client.get("/api/hardware/status").json()["data"]
            seat_hardware = hardware["seats"][0]
            assert seat_hardware["device_type"] == "esp32"
            assert seat_hardware["device_id"] == "esp32-seat-01"
            assert seat_hardware["current_mode"] == "MEETING_ACTIVE"
            assert seat_hardware["command_pending"] is False
            assert transport.downlink[-1]["type"] == "lighting"

            if round_index % 4 == 0:
                gateway.unregister(1)
                assert gateway.is_connected(1) is False
                gateway.register(1, transport)
                gateway.configure_esp32_session(
                    1,
                    device_id=simulator.device_id,
                    firmware_version=simulator.firmware_version,
                    boot_id=simulator.boot_id,
                )
                manager._render(1, force=True)
                assert gateway.is_connected(1) is True
                assert gateway.diagnostics(1)["command_pending"] is False

            end = client.post(f"/api/meetings/{meeting_id}/end")
            assert end.status_code == 200
            _wait_for_event(admin_ws, "meeting_ended", 1)
            db = TestSessionLocal()
            try:
                seat = db.get(SeatState, 1)
                assert seat is not None
                assert seat.status == "vacant"
                assert seat.attendee_id is None
            finally:
                db.close()
            ws_service.remove_room(meeting_id)

        db = TestSessionLocal()
        try:
            assert db.query(IdentityCheckInEvent).count() == ROUND_COUNT
        finally:
            db.close()
    finally:
        seats_api.identity_rate_limiter.clear()
        manager.unregister()
        for event_name in broadcast_events:
            event_bus.unsubscribe(event_name, broadcast_handler)
        WebSocketEventHandler._main_loop = old_main_loop
        ws_service.rooms.clear()
        _stop_broadcast_loop(broadcast_loop, broadcast_thread)
