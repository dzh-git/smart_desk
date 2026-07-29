from __future__ import annotations

import json
from pathlib import Path

from backend.database import resolve_data_dir
from backend.hardware import load_integration_config
from backend.security.device_auth import (
    ESP32_DEVICE_TOKENS_ENV,
    ESP32_DEVICE_TOKENS_FILE_ENV,
    load_esp32_credentials,
)


def test_data_dir_uses_explicit_runtime_location(monkeypatch, tmp_path):
    monkeypatch.setenv("SMARTDESK_DATA_DIR", str(tmp_path))
    assert resolve_data_dir() == tmp_path.resolve()


def test_integration_config_prefers_explicit_path(monkeypatch, tmp_path):
    path = tmp_path / "integration.json"
    path.write_text(
        json.dumps({"deploy_mode": "esp32", "seats_total": 9}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SMARTDESK_CONFIG_PATH", str(path))
    assert load_integration_config()["deploy_mode"] == "esp32"


def test_esp32_credentials_load_from_protected_file(monkeypatch, tmp_path):
    path = tmp_path / "esp32-device-tokens.json"
    path.write_text(
        json.dumps(
            {
                "esp32-seat-01": {
                    "seatId": 1,
                    "token": "test-device-token-from-file-000001",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv(ESP32_DEVICE_TOKENS_ENV, raising=False)
    monkeypatch.setenv(ESP32_DEVICE_TOKENS_FILE_ENV, str(path))

    credentials = load_esp32_credentials()

    assert credentials["esp32-seat-01"].seat_id == 1
    assert credentials["esp32-seat-01"].token.endswith("000001")


def test_missing_esp32_credential_file_fails_closed(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv(ESP32_DEVICE_TOKENS_ENV, raising=False)
    monkeypatch.setenv(
        ESP32_DEVICE_TOKENS_FILE_ENV,
        str(tmp_path / "missing.json"),
    )
    assert load_esp32_credentials() == {}
