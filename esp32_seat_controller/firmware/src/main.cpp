#include <Arduino.h>
#include <ArduinoJson.h>
#include <Adafruit_VL53L0X.h>
#include <FastLED.h>
#include <WebSocketsClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_task_wdt.h>

#include "DeviceConfig.h"

namespace {
constexpr char FIRMWARE_VERSION[] = "0.1.0";
constexpr uint8_t PROTOCOL_VERSION = 1;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 5000;
constexpr uint32_t SENSOR_INTERVAL_MS = 100;
constexpr uint32_t OCCUPANCY_DEBOUNCE_MS = 1200;
constexpr uint32_t SENSOR_ERROR_REPORT_MS = 30000;
constexpr uint32_t LED_FRAME_MS = 20;
constexpr uint32_t WIFI_RETRY_MIN_MS = 1000;
constexpr uint32_t WIFI_RETRY_MAX_MS = 30000;
constexpr uint32_t WS_RETRY_MIN_MS = 1000;
constexpr uint32_t WS_RETRY_MAX_MS = 30000;
constexpr uint32_t WATCHDOG_TIMEOUT_SECONDS = 8;

WebSocketsClient webSocket;
Adafruit_VL53L0X distanceSensor;
CRGB leds[LED_COUNT];

String bootId;
String currentMode = "BOOT";
String lastCommandId;
uint8_t brightness = 80;
uint32_t outgoingSequence = 0;
uint32_t lastHeartbeatAt = 0;
uint32_t lastSensorAt = 0;
uint32_t lastSensorErrorAt = 0;
uint32_t lastLedFrameAt = 0;
uint32_t wifiRetryAt = 0;
uint32_t wsRetryAt = 0;
uint32_t wifiBackoffMs = WIFI_RETRY_MIN_MS;
uint32_t wsBackoffMs = WS_RETRY_MIN_MS;
uint32_t occupancyCandidateAt = 0;
uint16_t distanceMm = 8190;
bool distanceSensorReady = false;
bool protocolReady = false;
bool wsConnected = false;
bool pirDetected = false;
bool occupied = false;
bool occupancyCandidate = false;

String eventId(const char* prefix) {
  return String(prefix) + "-" + bootId + "-" + String(outgoingSequence + 1);
}

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
  capabilities.add("pir");
  capabilities.add("vl53l0x");
  capabilities.add("ws2812b");
  sendJson(message);
}

void sendHeartbeat() {
  JsonDocument message;
  addEnvelope(message, "heartbeat");
  message["sequence"] = ++outgoingSequence;
  message["uptime_ms"] = millis();
  message["current_mode"] = currentMode;
  message["wifi_rssi"] = WiFi.RSSI();
  message["sensor_ok"] = distanceSensorReady;
  sendJson(message);
}

void sendOccupancy(bool nextOccupied) {
  JsonDocument message;
  const String id = eventId("occupancy");
  addEnvelope(message, "occupancy");
  message["sequence"] = ++outgoingSequence;
  message["event_id"] = id;
  message["occupied"] = nextOccupied;
  message["pir"] = pirDetected;
  message["distance_mm"] = distanceMm;
  message["sensor_ok"] = distanceSensorReady;
  sendJson(message);
}

void sendSensorError(const char* code) {
  JsonDocument message;
  const String id = eventId("sensor");
  addEnvelope(message, "sensor_error");
  message["sequence"] = ++outgoingSequence;
  message["event_id"] = id;
  message["component"] = "vl53l0x";
  message["error_code"] = code;
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
  message["current_mode"] = currentMode;
  if (errorCode != nullptr) {
    message["error_code"] = errorCode;
  }
  sendJson(message);
}

bool supportedMode(const String& mode) {
  static const char* modes[] = {
      "BOOT",          "IDLE",          "WELCOME",      "MEETING_ACTIVE",
      "AGENDA_ACTIVE", "VOTE_OPEN",     "VOTE_CLOSED",  "SERVICE_CALL",
      "MEETING_ENDED", "AI_SPEAKING",   "ERROR",        "OFF"};
  for (const char* candidate : modes) {
    if (mode == candidate) {
      return true;
    }
  }
  return false;
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
  if (!supportedMode(mode)) {
    sendCommandAck(commandId, false, "MODE_INVALID");
    return;
  }
  const int requestedBrightness = message["brightness"] | 80;
  if (requestedBrightness < 0 || requestedBrightness > 255) {
    sendCommandAck(commandId, false, "BRIGHTNESS_INVALID");
    return;
  }
  currentMode = mode;
  brightness = static_cast<uint8_t>(requestedBrightness);
  lastCommandId = commandId;
  sendCommandAck(commandId, true);
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
      currentMode = "ERROR";  // Safe, visible offline state.
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
    currentMode = "ERROR";
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

void sampleSensors(uint32_t now) {
  if (now - lastSensorAt < SENSOR_INTERVAL_MS) {
    return;
  }
  lastSensorAt = now;
  pirDetected = digitalRead(PIR_PIN) == HIGH;
  if (distanceSensorReady) {
    VL53L0X_RangingMeasurementData_t measurement;
    distanceSensor.rangingTest(&measurement, false);
    if (measurement.RangeStatus == 4) {
      distanceMm = 8190;
    } else {
      distanceMm = measurement.RangeMilliMeter;
    }
  } else if (now - lastSensorErrorAt >= SENSOR_ERROR_REPORT_MS) {
    lastSensorErrorAt = now;
    sendSensorError("SENSOR_UNAVAILABLE");
  }

  bool nextCandidate = occupied;
  if (!occupied) {
    nextCandidate =
        pirDetected &&
        (!distanceSensorReady || distanceMm <= OCCUPIED_DISTANCE_MM);
  } else {
    nextCandidate =
        pirDetected ||
        (distanceSensorReady &&
         distanceMm <= OCCUPIED_DISTANCE_MM + DISTANCE_HYSTERESIS_MM);
  }
  if (nextCandidate != occupancyCandidate) {
    occupancyCandidate = nextCandidate;
    occupancyCandidateAt = now;
  }
  if (
      occupancyCandidate != occupied &&
      now - occupancyCandidateAt >= OCCUPANCY_DEBOUNCE_MS) {
    occupied = occupancyCandidate;
    sendOccupancy(occupied);
  }
}

CRGB modeColor() {
  if (currentMode == "OFF") return CRGB::Black;
  if (currentMode == "ERROR") return CRGB::Red;
  if (currentMode == "WELCOME") return CRGB::Cyan;
  if (currentMode == "SERVICE_CALL") return CRGB::Orange;
  if (currentMode == "VOTE_OPEN") return CRGB::Blue;
  if (currentMode == "VOTE_CLOSED") return CRGB::Purple;
  if (currentMode == "AI_SPEAKING") return CRGB::Green;
  if (currentMode == "MEETING_ENDED") return CRGB::Gold;
  if (currentMode == "MEETING_ACTIVE" || currentMode == "AGENDA_ACTIVE") {
    return CRGB::White;
  }
  return CRGB(16, 16, 24);
}

void renderLighting(uint32_t now) {
  if (now - lastLedFrameAt < LED_FRAME_MS) {
    return;
  }
  lastLedFrameAt = now;
  FastLED.setBrightness(brightness);
  CRGB color = modeColor();
  if (
      currentMode == "WELCOME" || currentMode == "SERVICE_CALL" ||
      currentMode == "AI_SPEAKING") {
    const uint8_t wave = sin8(static_cast<uint8_t>(now / 8));
    color.nscale8_video(wave);
  }
  fill_solid(leds, LED_COUNT, color);
  FastLED.show();
}
}  // namespace

void setup() {
  Serial.begin(115200);
  pinMode(PIR_PIN, INPUT);
  Wire.begin();
  FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, LED_COUNT);
  FastLED.clear(true);

  distanceSensorReady = distanceSensor.begin();
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
  sampleSensors(now);
  renderLighting(now);
  if (
      protocolReady && now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatAt = now;
    sendHeartbeat();
  }
  esp_task_wdt_reset();
}
