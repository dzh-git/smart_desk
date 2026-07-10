"""
Seat Edge Agent — runs on each seat's Windows terminal.

Bridges the local Arduino Nano (USB serial) to the central host (WebSocket):

  * connects to ``ws://<central>/ws/seat/{seat_id}``
  * downlink: lighting commands (SET_MODE / SET_BRIGHTNESS / OFF) -> Arduino
  * uplink:   Arduino ``EVENT PIR`` -> central (drives seat occupancy/lighting)
              periodic status -> central (online / current_mode)

It reuses ``backend.hardware.arduino_manager.ArduinoManager`` so the serial
protocol logic stays in one place (the repo is cloned to each terminal).

Run (from the new_coding_desk directory so ``backend`` is importable):

    python -m seat_agent

Config: seat_agent_config.json (see seat_agent_config.example.json).
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal

from backend.hardware.arduino_manager import ArduinoManager
from seat_agent.config import load_config

logger = logging.getLogger("seat_agent")


class SeatAgent:
    def __init__(self, cfg: dict) -> None:
        self.cfg = cfg
        self.seat_id: int = int(cfg["seat_id"])
        self.arduino = ArduinoManager(
            {
                "enabled": True,
                "port": cfg["serial_port"],
                "baudrate": int(cfg.get("baudrate", 115200)),
                "write_timeout_seconds": float(cfg.get("write_timeout_seconds", 1.0)),
                "heartbeat_interval_seconds": float(
                    cfg.get("heartbeat_interval_seconds", 5.0)
                ),
                "reconnect_interval_seconds": float(
                    cfg.get("reconnect_interval_seconds", 3.0)
                ),
            }
        )
        # Forward firmware PIR events up to the central host.
        self.arduino.pir_callback = self._on_pir
        self.ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = asyncio.Event()

    # ── Uplink (Arduino -> central) ─────────────────────────────────────────

    def _on_pir(self, occupied: bool) -> None:
        """Called from the ArduinoManager reader thread."""
        msg = {"type": "pir", "seat_id": self.seat_id, "occupied": bool(occupied)}
        self._schedule_send(msg)

    def _schedule_send(self, msg: dict) -> None:
        if self._loop is None or self.ws is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(msg), self._loop)
        except Exception:
            logger.exception("uplink schedule failed")

    async def _send(self, msg: dict) -> None:
        if self.ws is None:
            return
        try:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            logger.exception("ws send failed")

    # ── Main loop ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.arduino.start()
        base = self.cfg["central_ws_url"].rstrip("/")
        url = f"{base}/ws/seat/{self.seat_id}"
        reconnect = float(self.cfg.get("reconnect_interval_seconds", 3.0))

        logger.info(
            "SeatAgent seat=%d port=%s -> %s (config: %s)",
            self.seat_id, self.cfg["serial_port"], url, self.cfg.get("_source"),
        )

        while not self._stop.is_set():
            try:
                import websockets  # type: ignore

                logger.info("connecting %s", url)
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    self.ws = ws
                    await self._send(
                        {
                            "type": "status",
                            "seat_id": self.seat_id,
                            "connected": self.arduino.is_connected,
                            "current_mode": self.arduino.current_mode,
                        }
                    )
                    async for raw in ws:
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning("bad json from central: %r", raw)
                            continue
                        if msg.get("type") == "lighting":
                            self.arduino.send_command(msg.get("cmd"), msg.get("arg"))
                        else:
                            logger.debug("ignored central msg: %r", msg)
                self.ws = None
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("ws disconnected: %s; reconnect in %.1fs", exc, reconnect)
                self.ws = None
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=reconnect)
                except asyncio.TimeoutError:
                    pass

        self.arduino.stop()
        logger.info("SeatAgent seat=%d stopped", self.seat_id)

    def stop(self) -> None:
        self._stop.set()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    cfg = load_config()
    agent = SeatAgent(cfg)

    def _sig(*_a):
        agent.stop()

    try:
        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)
    except Exception:
        pass

    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        agent.stop()


if __name__ == "__main__":
    main()
