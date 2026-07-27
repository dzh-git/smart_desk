"""Async ESP32 protocol simulator for development and integration tests."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

Sender = Callable[[dict[str, Any]], Awaitable[None]]


class Esp32SeatSimulator:
    """One deterministic ESP32 seat controller without hardware dependencies."""

    def __init__(
        self,
        seat_id: int,
        *,
        server_url: str = "ws://127.0.0.1:8000",
        firmware_version: str = "0.1.0",
        device_token: str | None = None,
        sender: Sender | None = None,
    ) -> None:
        if not 1 <= seat_id <= 9:
            raise ValueError("seat_id must be between 1 and 9")
        self.seat_id = seat_id
        self.device_id = f"esp32-seat-{seat_id:02d}"
        self.server_url = server_url.rstrip("/")
        self.firmware_version = firmware_version
        self.device_token = device_token
        self.boot_id = f"simboot-{uuid.uuid4().hex}"
        self.sequence = 0
        self.current_mode = "BOOT"
        self.connected = False
        self.protocol_ready = False
        self.sensor_ok = True
        self.pir = False
        self.distance_mm = 2000
        self.drop_next_ack = False
        self.last_command_id: str | None = None
        self.received_commands: list[dict[str, Any]] = []
        self.sent_messages: list[dict[str, Any]] = []
        self._sender = sender
        self._ws = None
        self._heartbeat_task: asyncio.Task | None = None

    def _envelope(self, message_type: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "type": message_type,
            "seat_id": self.seat_id,
        }

    def hello_message(self) -> dict[str, Any]:
        return {
            **self._envelope("hello"),
            "device_id": self.device_id,
            "firmware_version": self.firmware_version,
            "boot_id": self.boot_id,
            "capabilities": ["pir", "vl53l0x", "ws2812b"],
        }

    def heartbeat_message(self) -> dict[str, Any]:
        self.sequence += 1
        return {
            **self._envelope("heartbeat"),
            "sequence": self.sequence,
            "uptime_ms": self.sequence * 1000,
            "current_mode": self.current_mode,
            "wifi_rssi": -45,
            "sensor_ok": self.sensor_ok,
        }

    def occupancy_message(
        self,
        occupied: bool,
        *,
        event_id: str | None = None,
        sequence: int | None = None,
    ) -> dict[str, Any]:
        if sequence is None:
            self.sequence += 1
            actual_sequence = self.sequence
        else:
            actual_sequence = sequence
        self.pir = occupied
        self.distance_mm = 72 if occupied else 2000
        return {
            **self._envelope("occupancy"),
            "sequence": actual_sequence,
            "event_id": event_id or f"sim-event-{uuid.uuid4().hex}",
            "occupied": occupied,
            "pir": self.pir,
            "distance_mm": self.distance_mm,
            "sensor_ok": self.sensor_ok,
        }

    def sensor_error_message(
        self,
        *,
        error_code: str = "SENSOR_UNAVAILABLE",
    ) -> dict[str, Any]:
        self.sequence += 1
        self.sensor_ok = False
        return {
            **self._envelope("sensor_error"),
            "sequence": self.sequence,
            "event_id": f"sim-sensor-{uuid.uuid4().hex}",
            "component": "vl53l0x",
            "error_code": error_code,
        }

    def command_ack_message(
        self,
        command_id: str,
        *,
        success: bool = True,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        self.sequence += 1
        message = {
            **self._envelope("command_ack"),
            "sequence": self.sequence,
            "command_id": command_id,
            "success": success,
            "current_mode": self.current_mode,
        }
        if error_code:
            message["error_code"] = error_code
        return message

    async def emit(self, message: dict[str, Any]) -> None:
        self.sent_messages.append(message)
        if self._sender is not None:
            await self._sender(message)
        elif self._ws is not None:
            await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def handle_server_message(self, message: dict[str, Any]) -> None:
        if message.get("schema_version") != 1:
            return
        message_type = message.get("type")
        if message_type == "hello_ack":
            self.protocol_ready = True
            return
        if message_type != "lighting" or not self.protocol_ready:
            return

        command_id = str(message.get("command_id", ""))
        duplicate = command_id == self.last_command_id
        if not duplicate:
            self.current_mode = str(message["mode"])
            self.last_command_id = command_id
            self.received_commands.append(message)
        if self.drop_next_ack:
            self.drop_next_ack = False
            return
        await self.emit(self.command_ack_message(command_id))

    async def _heartbeat_loop(self) -> None:
        while self.connected:
            await self.emit(self.heartbeat_message())
            await asyncio.sleep(5)

    async def connect(self) -> None:
        import websockets

        headers = None
        if self.device_token:
            headers = {
                "Authorization": f"Bearer {self.device_token}",
            }
        url = f"{self.server_url}/ws/seat/{self.seat_id}"
        self._ws = await websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=15,
            ping_timeout=5,
            max_size=4096,
        )
        self.connected = True
        await self.emit(self.hello_message())
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop()
        )

    async def receive_loop(self) -> None:
        if self._ws is None:
            raise RuntimeError("simulator is not connected")
        async for raw in self._ws:
            await self.handle_server_message(json.loads(raw))

    async def disconnect(self) -> None:
        self.connected = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            await asyncio.gather(
                self._heartbeat_task,
                return_exceptions=True,
            )
            self._heartbeat_task = None
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        self.protocol_ready = False

    def reboot(self) -> None:
        self.boot_id = f"simboot-{uuid.uuid4().hex}"
        self.sequence = 0
        self.current_mode = "BOOT"
        self.last_command_id = None
        self.protocol_ready = False


async def run_scenario(
    *,
    server_url: str,
    seats: int,
    dwell_seconds: float,
    device_tokens: dict[int, str] | None = None,
) -> None:
    simulators = [
        Esp32SeatSimulator(
            seat,
            server_url=server_url,
            device_token=(device_tokens or {}).get(seat),
        )
        for seat in range(1, seats + 1)
    ]
    try:
        await asyncio.gather(*(sim.connect() for sim in simulators))
        receivers = [
            asyncio.create_task(sim.receive_loop())
            for sim in simulators
        ]
        await asyncio.sleep(0.2)
        await asyncio.gather(
            *(sim.emit(sim.occupancy_message(True)) for sim in simulators)
        )
        await asyncio.sleep(dwell_seconds)
        await asyncio.gather(
            *(sim.emit(sim.occupancy_message(False)) for sim in simulators)
        )
        await asyncio.sleep(0.2)
        for task in receivers:
            task.cancel()
        await asyncio.gather(*receivers, return_exceptions=True)
    finally:
        await asyncio.gather(
            *(sim.disconnect() for sim in simulators),
            return_exceptions=True,
        )


def parse_device_tokens(raw: str, seats: int) -> dict[int, str]:
    """Validate the same per-device credential map used by the backend."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("device token JSON is invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("device token JSON must be an object")
    tokens: dict[int, str] = {}
    for seat_id in range(1, seats + 1):
        device_id = f"esp32-seat-{seat_id:02d}"
        credential = payload.get(device_id)
        if not isinstance(credential, dict):
            raise ValueError(f"missing credential for {device_id}")
        if credential.get("seatId") != seat_id:
            raise ValueError(f"seat binding mismatch for {device_id}")
        token = credential.get("token")
        if not isinstance(token, str) or len(token) < 24:
            raise ValueError(f"invalid token for {device_id}")
        tokens[seat_id] = token
    return tokens


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server-url",
        default="ws://127.0.0.1:8000",
    )
    parser.add_argument("--seats", type=int, default=1, choices=range(1, 10))
    parser.add_argument("--dwell-seconds", type=float, default=1.0)
    parser.add_argument(
        "--device-tokens-json",
        default=os.environ.get(
            "SMARTDESK_ESP32_DEVICE_TOKENS_JSON",
            "",
        ),
        help=(
            "Per-device credential JSON; defaults to "
            "SMARTDESK_ESP32_DEVICE_TOKENS_JSON"
        ),
    )
    parser.add_argument(
        "--allow-unauthenticated-test",
        action="store_true",
        help="Only for the legacy distributed test bench.",
    )
    args = parser.parse_args()
    if args.device_tokens_json:
        try:
            device_tokens = parse_device_tokens(
                args.device_tokens_json,
                args.seats,
            )
        except ValueError as error:
            parser.error(str(error))
    elif args.allow_unauthenticated_test:
        device_tokens = None
    else:
        parser.error(
            "device credentials are required; set "
            "SMARTDESK_ESP32_DEVICE_TOKENS_JSON"
        )
    asyncio.run(
        run_scenario(
            server_url=args.server_url,
            seats=args.seats,
            dwell_seconds=args.dwell_seconds,
            device_tokens=device_tokens,
        )
    )


if __name__ == "__main__":
    main()
