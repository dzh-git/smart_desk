#include <Arduino.h>
#include <ArduinoJson.h>
#include <FastLED.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <cstring>
#include <esp_task_wdt.h>

#include "DeviceConfig.h"
#include "SmartDeskLighting.h"

namespace {
constexpr char FIRMWARE_VERSION[] = "0.3.0";
constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 5000;
constexpr uint32_t WIFI_RETRY_MIN_MS = 1000;
constexpr uint32_t WIFI_RETRY_MAX_MS = 30000;
constexpr uint32_t WS_RETRY_MIN_MS = 1000;
constexpr uint32_t WS_RETRY_MAX_MS = 30000;
constexpr uint32_t WATCHDOG_TIMEOUT_SECONDS = 8;

WebSocketsClient webSocket;
CRGB leds[LED_COUNT];
SmartDeskLighting lighting(leds, LED_COUNT, MAX_LED_BRIGHTNESS);

String bootId;
String lastCommandId;
uint32_t outgoingSequence = 0;
uint32_t lastHeartbeatAt = 0;
uint32_t wifiRetryAt = 0;
uint32_t wsRetryAt = 0;
uint32_t wifiBackoffMs = WIFI_RETRY_MIN_MS;
uint32_t wsBackoffMs = WS_RETRY_MIN_MS;
bool protocolReady = false;
bool wsConnected = false;

void sendJson(const JsonDocument& document) {
  if (!wsConnected) {
    return;
  }
  String payload;
  serializeJson(document, payload);
  webSocket.sendTXT(payload);
}

void addEnvelope(JsonDocument& document, const char* type) {
  document["schema_version"] = PROTOCOL_VERSION;
  document["type"] = type;
  document["seat_id"] = SEAT_ID;
}

void sendHello() {
  JsonDocument message;
  addEnvelope(message, "hello");
  message["device_id"] = DEVICE_ID;
  message["firmware_version"] = FIRMWARE_VERSION;
  message["boot_id"] = bootId;
  JsonArray capabilities = message["capabilities"].to<JsonArray>();
  capabilities.add("ws2812b");
  sendJson(message);
}

void sendHeartbeat() {
  JsonDocument message;
  addEnvelope(message, "heartbeat");
  message["sequence"] = ++outgoingSequence;
  message["uptime_ms"] = millis();
  message["current_mode"] = lighting.currentModeName();
  message["wifi_rssi"] = WiFi.RSSI();
  sendJson(message);
}

void sendCommandAck(
    const String& commandId,
    bool success,
    const char* errorCode = nullptr) {
  JsonDocument message;
  addEnvelope(message, "command_ack");
  message["sequence"] = ++outgoingSequence;
  message["command_id"] = commandId;
  message["success"] = success;
  message["current_mode"] = lighting.currentModeName();
  if (errorCode != nullptr) {
    message["error_code"] = errorCode;
  }
  sendJson(message);
}

void applyLightingCommand(const JsonDocument& message) {
  const String commandId = message["command_id"] | "";
  const String mode = message["mode"] | "";
  if (commandId.length() < 3) {
    sendCommandAck("invalid-command", false, "COMMAND_ID_INVALID");
    return;
  }
  if (commandId == lastCommandId) {
    sendCommandAck(commandId, true);
    return;
  }
  const int requestedBrightness = message["brightness"] | 80;
  if (requestedBrightness < 0 || requestedBrightness > 255) {
    sendCommandAck(commandId, false, "BRIGHTNESS_INVALID");
    return;
  }
  if (!lighting.setMode(mode, millis())) {
    sendCommandAck(commandId, false, "MODE_INVALID");
    return;
  }
  lighting.setBrightness(static_cast<uint8_t>(requestedBrightness));
  lastCommandId = commandId;
  sendCommandAck(commandId, true);
}

void enterErrorMode(uint32_t nowMs) {
  if (strcmp(lighting.currentModeName(), "ERROR") != 0) {
    lighting.setMode("ERROR", nowMs);
  }
}

void handleServerMessage(uint8_t* payload, size_t length) {
  if (length > 4096) {
    return;
  }
  JsonDocument message;
  const DeserializationError error =
      deserializeJson(message, payload, length);
  if (
      error ||
      message["schema_version"].as<uint8_t>() != PROTOCOL_VERSION) {
    return;
  }
  const String type = message["type"] | "";
  if (type == "hello_ack") {
    protocolReady = true;
    wsBackoffMs = WS_RETRY_MIN_MS;
  } else if (type == "lighting" && protocolReady) {
    applyLightingCommand(message);
  }
}

void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      wsConnected = true;
      protocolReady = false;
      sendHello();
      break;
    case WStype_DISCONNECTED:
      wsConnected = false;
      protocolReady = false;
      enterErrorMode(millis());
      wsRetryAt = millis() + wsBackoffMs;
      wsBackoffMs = min(wsBackoffMs * 2, WS_RETRY_MAX_MS);
      break;
    case WStype_TEXT:
      handleServerMessage(payload, length);
      break;
    default:
      break;
  }
}

void startWebSocket() {
  const String path = "/ws/seat/" + String(SEAT_ID);
  const String authorization =
      "Authorization: Bearer " + String(DEVICE_TOKEN) + "\r\n";
  webSocket.disconnect();
  webSocket.setExtraHeaders(authorization.c_str());
  if (SERVER_USE_TLS) {
    webSocket.beginSSL(SERVER_HOST, SERVER_PORT, path.c_str());
  } else {
    webSocket.begin(SERVER_HOST, SERVER_PORT, path.c_str());
  }
  webSocket.onEvent(onWebSocketEvent);
  webSocket.enableHeartbeat(15000, 3000, 2);
}

void maintainNetwork(uint32_t now) {
  if (WiFi.status() != WL_CONNECTED) {
    wsConnected = false;
    protocolReady = false;
    enterErrorMode(now);
    if (static_cast<int32_t>(now - wifiRetryAt) >= 0) {
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      wifiRetryAt = now + wifiBackoffMs;
      wifiBackoffMs = min(wifiBackoffMs * 2, WIFI_RETRY_MAX_MS);
    }
    return;
  }
  wifiBackoffMs = WIFI_RETRY_MIN_MS;
  if (!wsConnected && static_cast<int32_t>(now - wsRetryAt) >= 0) {
    startWebSocket();
    wsRetryAt = now + wsBackoffMs;
  }
  webSocket.loop();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, LED_COUNT);
  FastLED.clear(true);
  lighting.begin(millis());

  bootId = String(static_cast<uint32_t>(ESP.getEfuseMac()), HEX) + "-" +
           String(esp_random(), HEX);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  esp_task_wdt_init(WATCHDOG_TIMEOUT_SECONDS, true);
  esp_task_wdt_add(nullptr);
}

void loop() {
  const uint32_t now = millis();
  maintainNetwork(now);
  lighting.render(now);
  if (
      protocolReady && now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatAt = now;
    sendHeartbeat();
  }
  esp_task_wdt_reset();
}
