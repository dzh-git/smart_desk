"""
Serial service — manages 10 USB serial connections to Arduino Nano.
"""
from __future__ import annotations
import asyncio
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    serial = None  # type: ignore
    HAS_SERIAL = False

@dataclass
class SeatConnection:
    seat_id: int
    port: serial.Serial | None = None
    last_heartbeat: float = 0.0
    connected: bool = False


class SerialService:
    """Manages 10 seat serial connections. Stub mode when no hardware."""

    BAUD = 115200
    HEARTBEAT_TIMEOUT = 5.0  # seconds
    SCAN_INTERVAL = 2.0

    def __init__(self, stub: bool = True):
        self.stub = stub
        self.seats: dict[int, SeatConnection] = {
            i: SeatConnection(seat_id=i) for i in range(1, 11)
        }
        self._on_message: Callable[[int, dict], None] | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def on_message(self, callback: Callable[[int, dict], None]):
        """Register callback: (seat_id, message_dict) -> None."""
        self._on_message = callback

    def start(self):
        if self.stub:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def send(self, seat_id: int, msg: dict):
        """Send JSON message to one seat's Arduino."""
        if self.stub:
            return
        conn = self.seats.get(seat_id)
        if conn and conn.port and conn.port.is_open:
            try:
                data = (json.dumps(msg, ensure_ascii=False) + "\n").encode()
                conn.port.write(data)
            except serial.SerialException:
                conn.connected = False

    def broadcast(self, msg: dict):
        """Send to all 10 seats."""
        for seat_id in range(1, 11):
            self.send(seat_id, msg)

    def set_led(self, seat_id: int, pattern: str, color: tuple[int, int, int] = (255, 255, 255), brightness: int = 80):
        """Set LED pattern for a seat. pattern: 'breathe'|'wave'|'solid'|'off'."""
        self.send(seat_id, {
            "type": "led",
            "pattern": pattern,
            "color": list(color),
            "brightness": min(brightness, 80),
        })

    def _loop(self):
        while self._running:
            self._scan_ports()
            self._read_all()
            self._check_heartbeats()
            time.sleep(self.SCAN_INTERVAL)

    def _scan_ports(self):
        if not HAS_SERIAL:
            return
        ports = serial.tools.list_ports.comports()
        for p in ports:
            for conn in self.seats.values():
                if conn.port and conn.port.port == p.device:
                    continue
            # New port found — try to identify
            try:
                s = serial.Serial(p.device, self.BAUD, timeout=1)
                time.sleep(0.5)
                line = s.readline().decode(errors="ignore").strip()
                if line:
                    data = json.loads(line)
                    if data.get("type") == "boot" and "seat_id" in data:
                        sid = data["seat_id"]
                        if sid in self.seats:
                            old = self.seats[sid]
                            if old.port:
                                old.port.close()
                            old.port = s
                            old.connected = True
                            old.last_heartbeat = time.time()
            except (serial.SerialException, json.JSONDecodeError, UnicodeDecodeError):
                pass

    def _read_all(self):
        for conn in self.seats.values():
            if not conn.port or not conn.port.is_open:
                continue
            try:
                while conn.port.in_waiting:
                    line = conn.port.readline().decode(errors="ignore").strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("type") == "pong":
                        conn.last_heartbeat = time.time()
                    elif self._on_message:
                        self._on_message(conn.seat_id, data)
            except (serial.SerialException, json.JSONDecodeError):
                conn.connected = False

    def _check_heartbeats(self):
        now = time.time()
        for conn in self.seats.values():
            if conn.connected and (now - conn.last_heartbeat) > self.HEARTBEAT_TIMEOUT:
                conn.connected = False
                from backend.services.background_tasks import get_logger
                get_logger().warning(f"Seat {conn.seat_id} serial disconnected (heartbeat timeout)")

    # ── Stub helpers for UI dev ──
    def stub_seat_occupied(self, seat_id: int):
        """Simulate TOF detecting someone sitting."""
        if self._on_message:
            self._on_message(seat_id, {"type": "seat_occupied", "seat_id": seat_id})

    def stub_seat_vacant(self, seat_id: int):
        """Simulate TOF detecting vacancy."""
        if self._on_message:
            self._on_message(seat_id, {"type": "seat_vacant", "seat_id": seat_id})


# Singleton
serial_svc = SerialService(stub=True)
