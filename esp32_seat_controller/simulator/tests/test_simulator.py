from __future__ import annotations

import asyncio
import json

from backend.hardware.esp32_protocol import decode_uplink
from esp32_seat_controller.simulator import Esp32SeatSimulator
from esp32_seat_controller.simulator.esp32_simulator import (
    parse_device_tokens,
)


def test_simulator_messages_match_server_contract():
    simulator = Esp32SeatSimulator(1)

    assert decode_uplink(
        __import__("json").dumps(simulator.hello_message()),
        1,
    )["type"] == "hello"
    assert decode_uplink(
        __import__("json").dumps(simulator.heartbeat_message()),
        1,
    )["type"] == "heartbeat"
    assert decode_uplink(
        __import__("json").dumps(simulator.occupancy_message(True)),
        1,
    )["occupied"] is True
    assert decode_uplink(
        __import__("json").dumps(simulator.sensor_error_message()),
        1,
    )["type"] == "sensor_error"


def test_lighting_is_idempotent_and_acknowledged():
    sent = []

    async def sender(message):
        sent.append(message)

    simulator = Esp32SeatSimulator(1, sender=sender)
    simulator.protocol_ready = True
    command = {
        "schema_version": 1,
        "type": "lighting",
        "command_id": "lighting-command-0001",
        "sequence": 1,
        "mode": "WELCOME",
        "brightness": 80,
    }
    asyncio.run(simulator.handle_server_message(command))
    asyncio.run(simulator.handle_server_message(command))

    assert simulator.current_mode == "WELCOME"
    assert len(simulator.received_commands) == 1
    assert len(sent) == 2
    assert all(item["command_id"] == command["command_id"] for item in sent)


def test_lost_ack_can_be_requested_without_losing_applied_state():
    sent = []

    async def sender(message):
        sent.append(message)

    simulator = Esp32SeatSimulator(1, sender=sender)
    simulator.protocol_ready = True
    simulator.drop_next_ack = True
    command = {
        "schema_version": 1,
        "type": "lighting",
        "command_id": "lighting-command-0002",
        "sequence": 2,
        "mode": "MEETING_ACTIVE",
        "brightness": 80,
    }
    asyncio.run(simulator.handle_server_message(command))
    assert simulator.current_mode == "MEETING_ACTIVE"
    assert sent == []
    asyncio.run(simulator.handle_server_message(command))
    assert len(sent) == 1


def test_duplicate_and_out_of_order_events_are_constructible():
    simulator = Esp32SeatSimulator(1)
    original = simulator.occupancy_message(
        True,
        event_id="repeat-event-0001",
    )
    duplicate = simulator.occupancy_message(
        True,
        event_id=original["event_id"],
        sequence=original["sequence"],
    )
    out_of_order = simulator.occupancy_message(
        False,
        sequence=original["sequence"] - 1,
    )

    assert duplicate["event_id"] == original["event_id"]
    assert duplicate["sequence"] == original["sequence"]
    assert out_of_order["sequence"] < original["sequence"]


def test_reboot_changes_boot_id_and_resets_sequence():
    simulator = Esp32SeatSimulator(1)
    first_boot = simulator.boot_id
    simulator.heartbeat_message()
    simulator.reboot()

    assert simulator.boot_id != first_boot
    assert simulator.sequence == 0
    assert simulator.current_mode == "BOOT"


def test_nine_seat_simulators_have_unique_bindings():
    simulators = [Esp32SeatSimulator(seat) for seat in range(1, 10)]
    assert {sim.seat_id for sim in simulators} == set(range(1, 10))
    assert len({sim.device_id for sim in simulators}) == 9


def test_multi_seat_device_tokens_require_complete_exact_bindings():
    raw = json.dumps(
        {
            f"esp32-seat-{seat:02d}": {
                "seatId": seat,
                "token": f"simulator-device-token-{seat:02d}-000001",
            }
            for seat in range(1, 4)
        }
    )
    tokens = parse_device_tokens(raw, 3)
    assert sorted(tokens) == [1, 2, 3]
    assert len(set(tokens.values())) == 3

    invalid = json.loads(raw)
    invalid["esp32-seat-02"]["seatId"] = 1
    try:
        parse_device_tokens(json.dumps(invalid), 3)
    except ValueError as error:
        assert "seat binding mismatch" in str(error)
    else:
        raise AssertionError("Cross-seat simulator credential was accepted")
