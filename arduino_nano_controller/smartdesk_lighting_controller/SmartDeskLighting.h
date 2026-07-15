/*
 * SmartDesk Lighting Controller — module header.
 *
 * Encapsulates the Arduino Nano lighting firmware as a C++ class so the
 * sketch (.ino) stays tiny: it only creates the object, calls begin() once
 * in setup(), and update() every loop().
 *
 * Protocol contract: arduino_nano_controller/protocol.md
 *   Commands : PING | SET_MODE <mode> | SET_BRIGHTNESS <0-255> | OFF
 *   Events   : EVENT PIR 1 / EVENT PIR 0  (edge-triggered occupancy)
 *
 * Hardware:
 *   SR505 PIR OUT -> D8
 *   WS2812B DIN   -> D6
 *   Built-in LED  -> D13
 *   VL53L0X (I2C) -> A4=SDA / A5=SCL
 */

#pragma once

#include <Arduino.h>
#include <FastLED.h>
#include <Wire.h>
#include <VL53L0X.h>

// ---------------------------------------------------------------------------
// Hardware pins
// ---------------------------------------------------------------------------
const uint8_t SENSOR_PIN = 8;
const uint8_t LED_DATA_PIN = 6;
const uint8_t STATUS_LED_PIN = LED_BUILTIN;

// ---------------------------------------------------------------------------
// LED configuration
// ---------------------------------------------------------------------------
const uint16_t NUM_LEDS = 60;
const uint8_t MAX_LED_BRIGHTNESS = 80;   // power-safe hard ceiling
#define LED_COLOR_ORDER GRB

// ---------------------------------------------------------------------------
// VL53L0X laser ranging (averaging window)
// ---------------------------------------------------------------------------
const uint8_t TOF_SAMPLES = 8;            // mean of the last N readings

// ---------------------------------------------------------------------------
// Serial command buffer
// ---------------------------------------------------------------------------
const int SERIAL_BUF_SIZE = 64;

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------
const unsigned long IDLE_BREATH_PERIOD_MS = 3000;
const uint8_t IDLE_BRIGHTNESS_MIN = 10;
const uint8_t IDLE_BRIGHTNESS_MAX = 35;
const unsigned long BOOT_DURATION_MS = 800;
const unsigned long MEETING_ENDED_DURATION_MS = 1500;

// ---------------------------------------------------------------------------
// Lighting modes (mirror protocol.md §5 and backend LightingMode)
// ---------------------------------------------------------------------------
enum LightMode
{
    MODE_BOOT,
    MODE_IDLE,
    MODE_WELCOME,
    MODE_MEETING_ACTIVE,
    MODE_AGENDA_ACTIVE,
    MODE_VOTE_OPEN,
    MODE_VOTE_CLOSED,
    MODE_SERVICE_CALL,
    MODE_MEETING_ENDED,
    MODE_AI_SPEAKING,
    MODE_ERROR,
    MODE_OFF,
    MODE_UNKNOWN
};

// ---------------------------------------------------------------------------
// SmartDesk lighting controller
// ---------------------------------------------------------------------------
class SmartDeskLighting
{
public:
    SmartDeskLighting();

    // Hardware init — call once from setup().
    void begin();

    // One frame of work — call every loop().
    void update();

private:
    // --- hardware objects ---
    VL53L0X tof_;                 // laser range finder (I2C)
    CRGB leds_[NUM_LEDS];         // LED strip framebuffer

    // --- runtime state ---
    LightMode currentMode_ = MODE_BOOT;
    unsigned long modeStartedAtMs_ = 0;
    unsigned long nowMs_ = 0;
    uint8_t gBrightness_ = MAX_LED_BRIGHTNESS;
    unsigned long lastShowMs_ = 0;

    // PIR edge detection (independent of lighting)
    bool sensorState_ = LOW;
    bool previousSensorState_ = LOW;

    // VL53L0X ring buffer
    int tofBuf_[TOF_SAMPLES];
    uint8_t tofIdx_ = 0;

    // Serial command buffer
    char serialBuf_[SERIAL_BUF_SIZE];
    int serialIdx_ = 0;

    // --- serial command parsing ---
    void updateSerial();
    void handleCommand(char *cmd);
    LightMode modeFromString(const String &m);

    // --- PIR edge reporting (does NOT change lighting) ---
    void updatePIR();

    // --- lighting dispatch ---
    void updateLighting();
    void transitionTo(LightMode nextMode);

    // --- helpers ---
    uint8_t animationProgress(unsigned long durationMs);
    uint8_t idleBreathBrightness(unsigned long timeMs);
    uint8_t centerDistance(uint16_t index);
    CRGB blendColor(const CRGB &from, const CRGB &to, uint8_t amount);
    // Returns true only if the string is a plain decimal integer (digits 0-9,
    // no sign, no trailing junk). Used to reject non-numeric SET_BRIGHTNESS args.
    static bool isDecimalNumber(const String &str);

    // --- mode renderers ---
    void renderBoot();
    void renderIdle();
    void renderWelcome();
    void renderMeetingActive();
    void renderAgendaActive();
    void renderVoteOpen();
    void renderVoteClosed();
    void renderServiceCall();
    void renderMeetingEnded();
    void renderAiSpeaking();
    void renderError();
    void renderOff();
};
