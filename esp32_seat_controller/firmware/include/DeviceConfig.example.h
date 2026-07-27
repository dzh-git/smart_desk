#pragma once

// Copy to DeviceConfig.h. DeviceConfig.h is intentionally ignored by Git.
constexpr char WIFI_SSID[] = "replace-with-wifi-ssid";
constexpr char WIFI_PASSWORD[] = "replace-with-wifi-password";
constexpr char SERVER_HOST[] = "192.168.1.10";
constexpr uint16_t SERVER_PORT = 8000;
constexpr bool SERVER_USE_TLS = false;

constexpr uint8_t SEAT_ID = 1;
constexpr char DEVICE_ID[] = "esp32-seat-01";
constexpr char DEVICE_TOKEN[] = "replace-with-provisioned-device-token";

constexpr uint8_t PIR_PIN = 27;
constexpr uint8_t LED_PIN = 13;
constexpr uint16_t LED_COUNT = 30;
constexpr uint16_t OCCUPIED_DISTANCE_MM = 900;
constexpr uint16_t DISTANCE_HYSTERESIS_MM = 120;
