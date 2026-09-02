"""Nine-seat software simulation with real services and protocol state.

Physical sensors, lamps, USB power, Wi-Fi and thermal behaviour are outside
this test and remain HARDWARE_REQUIRED.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.api import hardware as hardware_api
from backend.api import seat_ws
from backend.events import event_bus
from backend.exceptions import ValidationError
from backend.hardware import set_lighting_manager, set_seat_gateway
from backend.hardware.esp32_protocol import decode_uplink
from backend.hardware.lighting_manager import LightingManager
from backend.hardware.seat_gateway import SeatGateway
from backend.main import app
from backend.models.service_call import ServiceCall
from backend.models.tablet_device import TabletDevice
from backend.models.vote_record import VoteRecord
from backend.services.tablet_device_service import TabletDeviceService
from esp32_seat_controller.simulator import Esp32SeatSimulator
from tests.conftest import TEST_ENGINE, TestSessionLocal


SEATS = tuple(range(1, 10))


class SimulatorTransport:
    def __init__(self, simulator: Esp32SeatSimulator) -> None:
        self.simulator = simulator
        self.downlink: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.downlink.append(message)
        await self.simulator.handle_server_message(message)


class AckCapture:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.messages.append(message)


def _immediate_schedule(coroutine, _loop):
    asyncio.run(coroutine)


def _tablet_token(seat_id: int) -> str:
    return f"fixture-tablet-seat-{seat_id:02d}-token-000001"


def _build_hardware(monkeypatch):
    gateway = SeatGateway(object(), list(SEATS))
    simulators: dict[int, Esp32SeatSimulator] = {}
    transports: dict[int, SimulatorTransport] = {}

    for seat_id in SEATS:
        simulator = Esp32SeatSimulator(seat_id)

        async def uplink(message: dict, current_seat=seat_id) -> None:
            decode_uplink(json.dumps(message), current_seat)
            if message["type"] == "command_ack":
                if gateway.accept_sequence(
                    current_seat,
                    message["sequence"],
                ):
                    gateway.acknowledge_command(
                        current_seat,
                        command_id=message["command_id"],
                        success=message["success"],
                        current_mode=message["current_mode"],
                        error_code=message.get("error_code"),
                    )

        simulator._sender = uplink
        simulator.protocol_ready = True
        transport = SimulatorTransport(simulator)
        gateway.register(seat_id, transport)
        gateway.configure_esp32_session(
            seat_id,
            device_id=simulator.device_id,
            firmware_version=simulator.firmware_version,
            boot_id=simulator.boot_id,
        )
        simulators[seat_id] = simulator
        transports[seat_id] = transport

    manager = LightingManager(gateway)
    monkeypatch.setattr(manager, "_schedule", lambda *_args: None)
    manager.register()
    set_seat_gateway(gateway)
    set_lighting_manager(manager)
    monkeypatch.setattr(hardware_api, "deploy_mode", "esp32")
    monkeypatch.setattr(hardware_api, "seat_ids", list(SEATS))
    return gateway, manager, simulators, transports


def _provision_and_heartbeat_tablets() -> None:
    db = TestSessionLocal()
    try:
        service = TabletDeviceService(db)
        for seat_id in SEATS:
            service.provision(
                device_id=f"tablet-seat-{seat_id:02d}",
                seat_id=seat_id,
                token=_tablet_token(seat_id),
            )
            service.record_heartbeat(
                device_id=f"tablet-seat-{seat_id:02d}",
                seat_id=seat_id,
                token=_tablet_token(seat_id),
                app_version="0.8.0",
                camera_status="READY",
                face_model_status="CALIBRATION_PENDING",
                registered_templates_count=0,
                microphone_status="READY",
                meeting_websocket_status="CONNECTED",
                diagnostic_status="READY",
                last_error=None,
            )
        with pytest.raises(ValidationError) as error:
            service.authenticate(
                device_id="tablet-seat-01",
                seat_id=2,
                token=_tablet_token(1),
            )
        assert error.value.error_code == "DEVICE_SEAT_MISMATCH"
    finally:
        db.close()


def _occupy_one(
    seat_id: int,
    simulator: Esp32SeatSimulator,
) -> list[dict]:
    capture = AckCapture()
    asyncio.run(
        seat_ws._handle_esp32_message(
            capture,
            seat_ws.get_seat_gateway(),
            seat_id,
            simulator.occupancy_message(True),
        )
    )
    return capture.messages


def test_nine_seat_burst_restart_and_recovery(monkeypatch):
    monkeypatch.setattr(
        "backend.hardware.seat_gateway.asyncio.run_coroutine_threadsafe",
        _immediate_schedule,
    )
    _provision_and_heartbeat_tablets()
    gateway, manager, simulators, transports = _build_hardware(monkeypatch)
    seat_clients = [TestClient(app) for _ in SEATS]
    admin = TestClient(app)

    try:
        meeting_response = admin.post(
            "/api/meetings",
            json={"title": "Nine-seat unattended simulation"},
        )
        assert meeting_response.status_code == 201
        meeting_id = meeting_response.json()["data"]["id"]
        attendee_ids: list[int] = []
        for seat_id in SEATS:
            attendee = admin.post(
                f"/api/meetings/{meeting_id}/attendees",
                json={
                    "name": f"Simulation attendee {seat_id}",
                    "title": "Fixture",
                },
            )
            assert attendee.status_code == 200
            attendee_ids.append(attendee.json()["data"]["id"])

        assert admin.post(
            f"/api/meetings/{meeting_id}/start"
        ).status_code == 200
        for seat_id in SEATS:
            assert simulators[seat_id].current_mode == "MEETING_ACTIVE"
            assert gateway.diagnostics(seat_id)["command_pending"] is False
            assert transports[seat_id].downlink[-1]["type"] == "lighting"

        with ThreadPoolExecutor(max_workers=9) as executor:
            occupancy_acks = list(
                executor.map(
                    lambda seat: _occupy_one(seat, simulators[seat]),
                    SEATS,
                )
            )
        assert all(messages[-1]["accepted"] for messages in occupancy_acks)
        seats = admin.get("/api/seats").json()["data"]
        assert sum(item["status"] == "occupied_unchecked" for item in seats) == 9

        vote = admin.post(
            "/api/votes",
            json={
                "meeting_id": meeting_id,
                "title": "Nine-seat burst vote",
                "options": ["Yes", "No"],
            },
        )
        assert vote.status_code == 201
        vote_id = vote.json()["data"]["id"]

        def submit_vote(index: int):
            return seat_clients[index].post(
                f"/api/votes/{vote_id}/submit",
                json={
                    "attendee_id": attendee_ids[index],
                    "option": "Yes" if index % 2 == 0 else "No",
                },
            )

        def request_service(index: int):
            return seat_clients[index].post(
                f"/api/service-calls?meeting_id={meeting_id}",
                json={
                    "seat_id": index + 1,
                    "service_type": ("tea", "water", "coffee")[index % 3],
                },
            )

        with ThreadPoolExecutor(max_workers=9) as executor:
            vote_responses = list(executor.map(submit_vote, range(9)))
        with ThreadPoolExecutor(max_workers=9) as executor:
            service_responses = list(executor.map(request_service, range(9)))
        assert all(response.status_code == 200 for response in vote_responses)
        assert all(response.status_code == 201 for response in service_responses)

        gateway.unregister(5)
        assert gateway.is_connected(5) is False
        simulators[5].reboot()
        simulators[5].protocol_ready = True
        gateway.register(5, transports[5])
        gateway.configure_esp32_session(
            5,
            device_id=simulators[5].device_id,
            firmware_version=simulators[5].firmware_version,
            boot_id=simulators[5].boot_id,
        )
        manager._render(5, force=True)
        assert gateway.is_connected(5) is True
        assert gateway.diagnostics(5)["command_pending"] is False

        # Dispose/reopen database connections to exercise persisted restart state.
        TEST_ENGINE.dispose()
        db = TestSessionLocal()
        try:
            assert db.query(TabletDevice).count() == 9
            assert db.query(VoteRecord).count() == 9
            assert db.query(ServiceCall).count() == 9
        finally:
            db.close()

        for seat_id in SEATS:
            gateway.unregister(seat_id)
            assert gateway.is_connected(seat_id) is False
            gateway.register(seat_id, transports[seat_id])
            gateway.configure_esp32_session(
                seat_id,
                device_id=simulators[seat_id].device_id,
                firmware_version=simulators[seat_id].firmware_version,
                boot_id=simulators[seat_id].boot_id,
            )
            gateway.record_heartbeat(
                seat_id,
                mode=simulators[seat_id].current_mode,
                sensor_ok=True,
            )
        assert all(gateway.is_connected(seat_id) for seat_id in SEATS)

        soak_seconds = float(
            os.environ.get("SMARTDESK_NINE_SEAT_SOAK_SECONDS", "0.1")
        )
        deadline = time.monotonic() + max(0.0, soak_seconds)
        while time.monotonic() < deadline:
            for seat_id in SEATS:
                gateway.record_heartbeat(
                    seat_id,
                    mode=simulators[seat_id].current_mode,
                    sensor_ok=True,
                )
                assert gateway.diagnostics(seat_id)["last_error"] is None
            time.sleep(min(1.0, max(0.01, soak_seconds)))
    finally:
        manager.unregister()
        for client in seat_clients:
            client.close()
        admin.close()
        event_bus._subscribers.clear()
