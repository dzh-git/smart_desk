"""
ArduinoManager — serial bridge to the SmartDesk lighting controller.

Reads the ``arduino`` section of config/smartdesk.integration.json. It is
designed to be NON-FATAL: any serial/hardware failure is logged and triggers
automatic reconnect, so the backend keeps running with the Arduino offline.

Threading model
---------------
A single daemon *reader* thread owns the serial port. It:
  * sends periodic ``PING`` heartbeats,
  * parses responses/events (``PONG`` / ``OK`` / ``ERR`` / ``EVENT``),
  * detects disconnect (read error or missed heartbeats) and reconnects.

``send_command()`` is lock-guarded and fire-and-forget, so EventBus handler
threads (and thus API request threads) never block on the serial line.

Protocol reference: arduino_nano_controller/protocol.md
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import serial  # type: ignore
    _SERIAL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SERIAL_AVAILABLE = False
    logger.warning("pyserial not installed; ArduinoManager will be disabled.")


class ArduinoManager:
    """Owns the serial connection to the lighting controller (Arduino Nano)."""

    def __init__(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self.enabled: bool = bool(config.get("enabled", False))
        self.port: Optional[str] = config.get("port")
        self.baudrate: int = int(config.get("baudrate", 115200))
        self.write_timeout: float = float(config.get("write_timeout_seconds", 1.0))
        self.heartbeat_interval: float = float(config.get("heartbeat_interval_seconds", 5.0))
        self.reconnect_interval: float = float(config.get("reconnect_interval_seconds", 3.0))

        self.ser = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._connected = False
        self.last_pong = 0.0
        # Last mode confirmed by an ``OK SET_MODE ...`` response.  Keep this
        # separate from LightingManager's intended mode so the UI never claims
        # that an offline controller changed successfully.
        self.current_mode = "UNKNOWN"
        self.last_command: Optional[str] = None
        self.last_ack_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.command_pending = False
        self.pir_callback: Optional[Callable[[bool], None]] = None
        self.connection_callback: Optional[Callable[[bool], None]] = None
        self.mode_callback: Optional[Callable[[str], None]] = None

        if self.enabled and not _SERIAL_AVAILABLE:
            self.enabled = False
            self.last_error = "pyserial not installed"
            logger.warning("Arduino enabled in config but pyserial is missing; disabling.")

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        """Spawn the reader thread. No-op (safe) when disabled or already running."""
        if not self.enabled:
            logger.info("[Arduino] disabled by config; skipping serial connection.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="arduino-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the reader thread to stop and close the port."""
        self._stop.set()
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:  # pragma: no cover
            pass
        self._connected = False
        self.command_pending = False
        self._notify_connection(False)

    def send_command(self, command: str, arg: Optional[str] = None) -> bool:
        """Send a line to the Arduino. Fire-and-forget; returns True if written.

        Does not wait for a response. Safe to call from any thread. Returns
        False without raising when offline or disabled.
        """
        line = command if arg is None else f"{command} {arg}"
        if not self.enabled or not self.ser or not self._connected:
            self.last_error = f"not connected: {line}"
            return False
        try:
            with self._lock:
                self.ser.write((line + "\n").encode("utf-8"))
            self.last_command = line
            self.command_pending = True
            self.last_error = None
            return True
        except Exception:
            logger.exception("[Arduino] send_command failed: %s", line)
            self.last_error = f"send failed: {line}"
            self.command_pending = False
            self._connected = False
            return False

    # ── Internal: connection lifecycle ───────────────────────────────────────

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect()
                self._connected = True
                self.last_pong = time.time()
                logger.info("[Arduino] connected on %s", self.port)
                # Sync firmware state on (re)connect.
                self._send_raw("SET_MODE IDLE")
                self._notify_connection(True)
                self._read_loop()
            except Exception as exc:  # pragma: no cover - hardware dependent
                logger.warning("[Arduino] connection lost: %s", exc)
                self.last_error = str(exc)
            self._connected = False
            self.current_mode = "UNKNOWN"
            self.command_pending = False
            self._notify_connection(False)
            if self._stop.is_set():
                break
            time.sleep(self.reconnect_interval)

    def _connect(self) -> None:
        self.ser = serial.Serial(  # type: ignore[union-attr]
            port=self.port,
            baudrate=self.baudrate,
            write_timeout=self.write_timeout,
            timeout=0.2,
        )
        # Arduino Nano resets when the port opens; let the bootloader/setup settle.
        time.sleep(2.0)

    def _send_raw(self, line: str) -> None:
        try:
            with self._lock:
                self.ser.write((line + "\n").encode("utf-8"))  # type: ignore[union-attr]
        except Exception:
            logger.exception("[Arduino] _send_raw failed: %s", line)

    def _read_loop(self) -> None:
        buffer = ""
        last_heartbeat = time.time()
        while not self._stop.is_set() and self.ser and self.ser.is_open:
            now = time.time()
            if now - last_heartbeat >= self.heartbeat_interval:
                last_heartbeat = now
                self._send_raw("PING")
                if now - self.last_pong > self.heartbeat_interval * 3:
                    raise IOError("Arduino heartbeat lost (no PONG received)")

            try:
                chunk = self.ser.read(128)  # type: ignore[union-attr]
            except Exception as exc:  # pragma: no cover
                raise IOError(f"serial read failed: {exc}")

            if chunk:
                buffer += chunk.decode("utf-8", "replace")
                while "\n" in buffer:
                    raw, buffer = buffer.split("\n", 1)
                    line = raw.strip()
                    if line:
                        self._handle_line(line)
            else:
                time.sleep(0.01)

    # ── Internal: response/event handling ────────────────────────────────────

    def _handle_line(self, line: str) -> None:
        if line == "PONG":
            self.last_pong = time.time()
        elif line.startswith("OK "):
            echoed = line[3:].strip()
            self.last_ack_at = time.time()
            self.last_error = None
            if echoed == self.last_command:
                self.command_pending = False
            if echoed.startswith("SET_MODE "):
                mode = echoed.split(None, 1)[1].strip().upper()
                self.current_mode = mode
                if self.mode_callback is not None:
                    try:
                        self.mode_callback(mode)
                    except Exception:
                        logger.exception("[Arduino] mode_callback failed")
            elif echoed == "OFF":
                self.current_mode = "OFF"
                if self.mode_callback is not None:
                    try:
                        self.mode_callback("OFF")
                    except Exception:
                        logger.exception("[Arduino] mode_callback failed")
        elif line.startswith("ERR "):
            logger.warning("[Arduino] error response: %s", line)
            self.command_pending = False
            self.last_error = line
        elif line.startswith("EVENT "):
            self._handle_event(line)
        else:
            logger.debug("[Arduino] unexpected line: %s", line)

    def _handle_event(self, line: str) -> None:
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "PIR":
            try:
                occupied = int(parts[2]) != 0
            except ValueError:
                return
            if self.pir_callback is not None:
                try:
                    self.pir_callback(occupied)
                except Exception:
                    logger.exception("[Arduino] pir_callback failed")

    def _notify_connection(self, connected: bool) -> None:
        if self.connection_callback is None:
            return
        try:
            self.connection_callback(connected)
        except Exception:
            logger.exception("[Arduino] connection_callback failed")
