from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "provision_esp32.ps1"

DEVICE_CONFIG = """#pragma once
constexpr char WIFI_SSID[] = "SmartDesk-Test";
constexpr char WIFI_PASSWORD[] = "not-a-real-password";
constexpr char SERVER_HOST[] = "192.168.137.1";
constexpr uint16_t SERVER_PORT = 8000;
constexpr bool SERVER_USE_TLS = false;
constexpr uint8_t SEAT_ID = 1;
constexpr char DEVICE_ID[] = "esp32-seat-01";
constexpr char DEVICE_TOKEN[] = "old-device-token-0000000000000001";
constexpr uint8_t LED_PIN = 13;
constexpr uint16_t LED_COUNT = 60;
constexpr uint8_t MAX_LED_BRIGHTNESS = 80;
"""


def _pwsh() -> str:
    executable = shutil.which("pwsh.exe") or shutil.which("pwsh")
    if executable is None:
        pytest.skip("PowerShell 7 is required for the ESP32 provisioning test")
    return executable


def _run_script(
    config_path: Path,
    credential_path: Path,
    *extra_args: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _pwsh(),
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(SCRIPT),
            "-SeatId",
            "2",
            "-DeviceConfigPath",
            str(config_path),
            "-CredentialStorePath",
            str(credential_path),
            "-SkipRestart",
            "-SkipFlash",
            *extra_args,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_single_seat_parameter_rebinds_config_and_preserves_other_devices(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "DeviceConfig.h"
    config_path.write_text(DEVICE_CONFIG, encoding="utf-8")
    credential_path = tmp_path / "credentials.json"
    credential_path.write_text(
        json.dumps(
            {
                "esp32-seat-01": {
                    "seatId": 1,
                    "token": "test-old-device-token-0000000000000001",
                },
                "esp32-seat-03": {
                    "seatId": 3,
                    "token": "test-seat-three-token-00000000000000003",
                },
            }
        ),
        encoding="utf-8",
    )

    result = _run_script(config_path, credential_path)

    assert result.returncode == 0, result.stdout + result.stderr
    config = config_path.read_text(encoding="utf-8")
    assert "constexpr uint8_t SEAT_ID = 2;" in config
    assert 'constexpr char DEVICE_ID[] = "esp32-seat-02";' in config
    token_match = re.search(r'DEVICE_TOKEN\[\] = "([a-f0-9]{64})";', config)
    assert token_match is not None
    generated_token = token_match.group(1)

    credentials = json.loads(credential_path.read_text(encoding="utf-8"))
    assert "esp32-seat-01" not in credentials
    assert credentials["esp32-seat-02"] == {
        "seatId": 2,
        "token": generated_token,
    }
    assert credentials["esp32-seat-03"]["seatId"] == 3
    output = result.stdout + result.stderr
    assert generated_token not in output
    assert "test-old-device-token-0000000000000001" not in output


def test_conflicting_target_seat_fails_without_partial_changes(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "DeviceConfig.h"
    config_path.write_text(DEVICE_CONFIG, encoding="utf-8")
    credential_path = tmp_path / "credentials.json"
    original_credentials = json.dumps(
        {
            "esp32-seat-01": {
                "seatId": 1,
                "token": "test-old-device-token-0000000000000001",
            },
            "existing-seat-two-device": {
                "seatId": 2,
                "token": "test-existing-seat-two-token-00000000002",
            },
        }
    )
    credential_path.write_text(original_credentials, encoding="utf-8")

    result = _run_script(config_path, credential_path)

    assert result.returncode != 0
    assert "Seat 2" in result.stdout + result.stderr
    assert config_path.read_text(encoding="utf-8") == DEVICE_CONFIG
    assert credential_path.read_text(encoding="utf-8") == original_credentials


def test_what_if_reports_plan_without_writing_credentials_or_config(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "DeviceConfig.h"
    config_path.write_text(DEVICE_CONFIG, encoding="utf-8")
    credential_path = tmp_path / "credentials.json"
    original_credentials = json.dumps(
        {
            "esp32-seat-01": {
                "seatId": 1,
                "token": "test-old-device-token-0000000000000001",
            }
        }
    )
    credential_path.write_text(original_credentials, encoding="utf-8")

    result = _run_script(config_path, credential_path, "-WhatIf")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "esp32-seat-01 -> esp32-seat-02" in result.stdout
    assert config_path.read_text(encoding="utf-8") == DEVICE_CONFIG
    assert credential_path.read_text(encoding="utf-8") == original_credentials
