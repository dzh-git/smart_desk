/*
 * Interactive Seat Lighting Controller
 *
 * Hardware connections:
 *   Arduino Nano
 *   SR505 PIR OUT  -> D8
 *   WS2812B DIN    -> D6
 *   Built-in LED   -> D13
 *
 * Lighting behaviors:
 *   Idle      - available seat indication with a slow low-brightness cyan breath.
 *   Entering  - PIR rising edge starts a 500 ms center-out cyan-to-green expansion.
 *   Occupied  - occupied seat indication with a solid green strip.
 *   Leaving   - PIR falling edge starts a 500 ms edge-in contraction back to idle.
 *
 * State machine:
 *   IDLE -> ENTERING -> OCCUPIED -> LEAVING -> IDLE
 *
 * All animations are non-blocking and are driven from millis(), allowing the
 * controller to remain responsive while transitions are rendering.
 *
 * Author: <author>
 * Version: <version>
 */

#include <FastLED.h>

// ---------------------------------------------------------------------------
// Hardware
// Defines the physical Arduino pins used by the sensor, LED strip, and status
// indicator so hardware changes are isolated from the application logic.
// ---------------------------------------------------------------------------
const uint8_t SENSOR_PIN = 8;
const uint8_t LED_DATA_PIN = 6;
const uint8_t STATUS_LED_PIN = LED_BUILTIN;

// ---------------------------------------------------------------------------
// LED configuration
// Captures strip-specific settings in one place. The global brightness limits
// current draw and keeps the low-level effects suitable for an indicator strip.
// ---------------------------------------------------------------------------
const uint16_t NUM_LEDS = 60;
const uint8_t MAX_LED_BRIGHTNESS = 80;
#define LED_COLOR_ORDER GRB

CRGB leds[NUM_LEDS];

// ---------------------------------------------------------------------------
// Colors
// Centralizes the application color palette. Rendering functions blend between
// these colors rather than duplicating literal RGB values.
// ---------------------------------------------------------------------------
const CRGB COLOR_IDLE = CRGB::Cyan;
const CRGB COLOR_OCCUPIED = CRGB::Green;
const CRGB COLOR_OFF = CRGB::Black;

// ---------------------------------------------------------------------------
// Animation timing
// Keeps all timing parameters visible and adjustable without touching the state
// machine or drawing code.
// ---------------------------------------------------------------------------
const unsigned long IDLE_BREATH_PERIOD_MS = 3000;
const unsigned long ENTERING_DURATION_MS = 500;
const unsigned long LEAVING_DURATION_MS = 500;

const uint8_t IDLE_BRIGHTNESS_MIN = 10;
const uint8_t IDLE_BRIGHTNESS_MAX = 35;

// ---------------------------------------------------------------------------
// State machine
// Represents the complete lighting lifecycle. The sensor only causes state
// transitions; visual behavior is selected exclusively by the current state.
// ---------------------------------------------------------------------------
enum LightState
{
    IDLE,
    ENTERING,
    OCCUPIED,
    LEAVING
};

// ---------------------------------------------------------------------------
// Variables
// Stores runtime state that changes as the sensor and animations progress.
// ---------------------------------------------------------------------------
LightState currentState = IDLE;

bool sensorState = LOW;
bool previousSensorState = LOW;
bool enterRequested = false;
bool leaveRequested = false;

unsigned long stateStartedAtMs = 0;
unsigned long nowMs = 0;

// ---------------------------------------------------------------------------
// Function declarations
// ---------------------------------------------------------------------------
void updateSensor();
void updateStateMachine();
void updateLighting();

void transitionTo(LightState nextState);
uint8_t animationProgress(unsigned long durationMs);

void renderIdle();
void renderEntering();
void renderOccupied();
void renderLeaving();

void drawCenterExpand(uint8_t progress, const CRGB &startColor, const CRGB &endColor);
void drawCenterContract(uint8_t progress, const CRGB &activeColor, const CRGB &idleColor);
CRGB blendColor(const CRGB &fromColor, const CRGB &toColor, uint8_t amount);
uint8_t idleBreathBrightness(unsigned long timeMs);
uint8_t centerDistance(uint16_t index);

void setup()
{
    pinMode(SENSOR_PIN, INPUT);
    pinMode(STATUS_LED_PIN, OUTPUT);

    FastLED.addLeds<WS2812B, LED_DATA_PIN, LED_COLOR_ORDER>(leds, NUM_LEDS);
    FastLED.setBrightness(MAX_LED_BRIGHTNESS);
    FastLED.clear(true);

    sensorState = digitalRead(SENSOR_PIN);
    previousSensorState = sensorState;

    transitionTo(sensorState == HIGH ? OCCUPIED : IDLE);
}

void loop()
{
    nowMs = millis();

    updateSensor();
    updateStateMachine();
    updateLighting();

    FastLED.show();
}

// ---------------------------------------------------------------------------
// Sensor handling
// Reads and stores the PIR state once per loop. Edge detection is performed by
// comparing the current reading with the previous loop's reading.
// ---------------------------------------------------------------------------
void updateSensor()
{
    previousSensorState = sensorState;
    sensorState = digitalRead(SENSOR_PIN);

    const bool risingEdge = (sensorState == HIGH && previousSensorState == LOW);
    const bool fallingEdge = (sensorState == LOW && previousSensorState == HIGH);

    if (risingEdge)
    {
        enterRequested = true;
        leaveRequested = false;
    }

    if (fallingEdge)
    {
        leaveRequested = true;
        enterRequested = false;
    }

    digitalWrite(STATUS_LED_PIN, sensorState == HIGH ? HIGH : LOW);
}

// ---------------------------------------------------------------------------
// State machine update
// Converts PIR edges and completed animations into state transitions. Rendering
// is intentionally kept out of this function so behavior remains state-driven.
// ---------------------------------------------------------------------------
void updateStateMachine()
{
    switch (currentState)
    {
        case IDLE:
            if (enterRequested)
            {
                enterRequested = false;
                transitionTo(ENTERING);
            }
            break;

        case ENTERING:
            if (nowMs - stateStartedAtMs >= ENTERING_DURATION_MS)
            {
                transitionTo(OCCUPIED);
            }
            break;

        case OCCUPIED:
            if (leaveRequested)
            {
                leaveRequested = false;
                transitionTo(LEAVING);
            }
            break;

        case LEAVING:
            if (nowMs - stateStartedAtMs >= LEAVING_DURATION_MS)
            {
                transitionTo(IDLE);
            }
            break;
    }
}

// ---------------------------------------------------------------------------
// Lighting dispatcher
// Selects exactly one renderer based on the active state. This keeps visual
// behavior predictable and prevents sensor code from directly drawing LEDs.
// ---------------------------------------------------------------------------
void updateLighting()
{
    switch (currentState)
    {
        case IDLE:
            renderIdle();
            break;

        case ENTERING:
            renderEntering();
            break;

        case OCCUPIED:
            renderOccupied();
            break;

        case LEAVING:
            renderLeaving();
            break;
    }
}

void transitionTo(LightState nextState)
{
    currentState = nextState;
    stateStartedAtMs = nowMs;
}

uint8_t animationProgress(unsigned long durationMs)
{
    if (durationMs == 0)
    {
        return 255;
    }

    const unsigned long elapsedMs = nowMs - stateStartedAtMs;

    if (elapsedMs >= durationMs)
    {
        return 255;
    }

    return map(elapsedMs, 0, durationMs, 0, 255);
}

/*
 * Purpose: Show that the seat is available.
 * Effect:  The entire strip breathes slowly in cyan at low brightness.
 * Duration: Continuous while the state remains IDLE.
 */
void renderIdle()
{
    const uint8_t brightness = idleBreathBrightness(nowMs);
    const CRGB idleColor = blendColor(COLOR_OFF, COLOR_IDLE, brightness);

    fill_solid(leds, NUM_LEDS, idleColor);
}

/*
 * Purpose: Acknowledge a person entering the sensor area.
 * Effect:  A smooth center-out expansion blends from cyan to green.
 * Duration: 500 ms.
 */
void renderEntering()
{
    const uint8_t progress = animationProgress(ENTERING_DURATION_MS);
    drawCenterExpand(progress, COLOR_IDLE, COLOR_OCCUPIED);
}

/*
 * Purpose: Show that the seat is occupied.
 * Effect:  The entire strip remains solid green with no animation.
 * Duration: Continuous while the PIR sensor remains HIGH.
 */
void renderOccupied()
{
    fill_solid(leds, NUM_LEDS, COLOR_OCCUPIED);
}

/*
 * Purpose: Acknowledge a person leaving the sensor area.
 * Effect:  Green contracts from both ends toward the center while the strip
 *          gradually returns to the idle cyan appearance.
 * Duration: 500 ms.
 */
void renderLeaving()
{
    const uint8_t progress = animationProgress(LEAVING_DURATION_MS);
    drawCenterContract(progress, COLOR_OCCUPIED, COLOR_IDLE);
}

// Draws a symmetrical center-out wipe. Pixels ahead of the wipe stay in the
// starting color; pixels inside the wipe smoothly blend toward the end color.
void drawCenterExpand(uint8_t progress, const CRGB &startColor, const CRGB &endColor)
{
    const uint8_t maxDistance = centerDistance(0);
    const uint16_t scaledReach = static_cast<uint16_t>(progress) * maxDistance;

    for (uint16_t index = 0; index < NUM_LEDS; index++)
    {
        const uint8_t distance = centerDistance(index);
        const uint8_t localProgress = (scaledReach >= static_cast<uint16_t>(distance) * 255)
            ? progress
            : 0;

        leds[index] = blendColor(startColor, endColor, localProgress);
    }
}

// Draws a symmetrical edge-in wipe. Pixels already reached by the wipe return
// toward idle cyan; pixels not yet reached remain green.
void drawCenterContract(uint8_t progress, const CRGB &activeColor, const CRGB &idleColor)
{
    const uint8_t maxDistance = centerDistance(0);
    const uint16_t scaledThreshold = static_cast<uint16_t>(255 - progress) * maxDistance;
    const CRGB returningColor = blendColor(activeColor, idleColor, progress);

    for (uint16_t index = 0; index < NUM_LEDS; index++)
    {
        const uint8_t distance = centerDistance(index);
        const bool returnedToIdle = (static_cast<uint16_t>(distance) * 255 >= scaledThreshold);

        leds[index] = returnedToIdle ? returningColor : activeColor;
    }
}

CRGB blendColor(const CRGB &fromColor, const CRGB &toColor, uint8_t amount)
{
    return blend(fromColor, toColor, amount);
}

uint8_t idleBreathBrightness(unsigned long timeMs)
{
    const uint16_t phase = ((timeMs % IDLE_BREATH_PERIOD_MS) * 255UL) / IDLE_BREATH_PERIOD_MS;
    const uint8_t wave = sin8(phase);

    return map(wave, 0, 255, IDLE_BRIGHTNESS_MIN, IDLE_BRIGHTNESS_MAX);
}

uint8_t centerDistance(uint16_t index)
{
    const uint16_t centerLeft = (NUM_LEDS - 1) / 2;
    const uint16_t centerRight = NUM_LEDS / 2;

    if (index <= centerLeft)
    {
        return centerLeft - index;
    }

    return index - centerRight;
}
