from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIRMWARE = ROOT / "esp32_seat_controller" / "firmware"


def test_firmware_contains_required_resilience_paths():
    source = (FIRMWARE / "src" / "main.cpp").read_text(encoding="utf-8")
    for marker in (
        "HEARTBEAT_INTERVAL_MS",
        "WIFI_RETRY_MAX_MS",
        "WS_RETRY_MAX_MS",
        "esp_task_wdt_reset",
        "sendOccupancy",
        "sendCommandAck",
        "sendSensorError",
        "lastCommandId",
        'currentMode = "ERROR"',
    ):
        assert marker in source
    assert "delay(" not in source


def test_firmware_secrets_are_local_only():
    ignore = (FIRMWARE / ".gitignore").read_text(encoding="utf-8")
    example = (
        FIRMWARE / "include" / "DeviceConfig.example.h"
    ).read_text(encoding="utf-8")
    assert "include/DeviceConfig.h" in ignore
    assert "replace-with-provisioned-device-token" in example
    assert not (FIRMWARE / "include" / "DeviceConfig.h").exists()
