from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIRMWARE = ROOT / "esp32_seat_controller" / "firmware"
MAIN_SOURCE = FIRMWARE / "src" / "main.cpp"
LIGHTING_HEADER = FIRMWARE / "include" / "SmartDeskLighting.h"
LIGHTING_SOURCE = FIRMWARE / "src" / "SmartDeskLighting.cpp"


def test_firmware_contains_required_resilience_paths():
    source = MAIN_SOURCE.read_text(encoding="utf-8")
    for marker in (
        "HEARTBEAT_INTERVAL_MS",
        "WIFI_RETRY_MAX_MS",
        "WS_RETRY_MAX_MS",
        "esp_task_wdt_reset",
        "sendCommandAck",
        "lastCommandId",
        "enterErrorMode",
    ):
        assert marker in source


def test_firmware_contains_all_non_blocking_lighting_modes():
    header = LIGHTING_HEADER.read_text(encoding="utf-8")
    source = LIGHTING_SOURCE.read_text(encoding="utf-8")
    main = MAIN_SOURCE.read_text(encoding="utf-8")
    modes = (
        "BOOT",
        "IDLE",
        "WELCOME",
        "MEETING_ACTIVE",
        "AGENDA_ACTIVE",
        "VOTE_OPEN",
        "VOTE_CLOSED",
        "SERVICE_CALL",
        "MEETING_ENDED",
        "AI_SPEAKING",
        "ERROR",
        "OFF",
    )
    renderers = (
        "renderBoot",
        "renderIdle",
        "renderWelcome",
        "renderMeetingActive",
        "renderAgendaActive",
        "renderVoteOpen",
        "renderVoteClosed",
        "renderServiceCall",
        "renderMeetingEnded",
        "renderAiSpeaking",
        "renderError",
        "renderOff",
    )
    for mode in modes:
        assert f'"{mode}"' in source
    for renderer in renderers:
        assert renderer in header
        assert renderer in source
    assert "delay(" not in header + source + main


def test_lighting_uses_dynamic_geometry_and_power_safe_brightness():
    source = LIGHTING_SOURCE.read_text(encoding="utf-8")
    assert "centerLeft = (ledCount_ - 1) / 2" in source
    assert "centerRight = ledCount_ / 2" in source
    assert "min(requestedBrightness, maxBrightness_)" in source
    assert "i <= 29" not in source
    assert "i - 30" not in source


def test_new_commands_restart_animation_but_duplicate_ids_do_not():
    main = MAIN_SOURCE.read_text(encoding="utf-8")
    lighting = LIGHTING_SOURCE.read_text(encoding="utf-8")
    duplicate_guard = main.index("if (commandId == lastCommandId)")
    set_mode = main.index("lighting.setMode(mode, millis())")
    assert duplicate_guard < set_mode
    assert "modeStartedAtMs_ = nowMs" in lighting


def test_wroom32e_lighting_defaults_and_firmware_version_are_explicit():
    main = MAIN_SOURCE.read_text(encoding="utf-8")
    example = (
        FIRMWARE / "include" / "DeviceConfig.example.h"
    ).read_text(encoding="utf-8")
    for setting in (
        "LED_PIN = 13",
        "LED_COUNT = 60",
        "MAX_LED_BRIGHTNESS = 80",
    ):
        assert setting in example
    assert 'FIRMWARE_VERSION[] = "0.3.0"' in main


def test_firmware_is_wifi_lighting_only():
    main = MAIN_SOURCE.read_text(encoding="utf-8")
    platformio = (FIRMWARE / "platformio.ini").read_text(encoding="utf-8")
    example = (
        FIRMWARE / "include" / "DeviceConfig.example.h"
    ).read_text(encoding="utf-8")

    assert 'capabilities.add("ws2812b")' in main
    assert 'capabilities.add("pir")' not in main
    assert 'capabilities.add("vl53l0x")' not in main
    for forbidden in (
        "Adafruit_VL53L0X",
        "Wire.h",
        "PIR_PIN",
        "sendOccupancy",
        "sendSensorError",
        'addEnvelope(message, "occupancy")',
        'addEnvelope(message, "sensor_error")',
        'message["sensor_ok"]',
    ):
        assert forbidden not in main
    assert "Adafruit_VL53L0X" not in platformio
    for removed_setting in (
        "PIR_PIN",
        "I2C_SDA_PIN",
        "I2C_SCL_PIN",
        "OCCUPIED_DISTANCE_MM",
        "DISTANCE_HYSTERESIS_MM",
    ):
        assert removed_setting not in example


def test_firmware_secrets_are_local_only():
    ignore = (FIRMWARE / ".gitignore").read_text(encoding="utf-8")
    example = (
        FIRMWARE / "include" / "DeviceConfig.example.h"
    ).read_text(encoding="utf-8")
    assert "include/DeviceConfig.h" in ignore
    assert 'replace-with-wifi-ssid' in example
    assert 'replace-with-wifi-password' in example
    assert "replace-with-provisioned-device-token" in example
