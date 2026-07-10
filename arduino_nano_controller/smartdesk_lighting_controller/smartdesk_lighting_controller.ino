/*
 * SmartDesk Lighting Controller (Arduino Nano)
 *
 * Replaces the autonomous PIR demo with a host-driven lighting executor.
 * The Nano no longer decides business lighting from the PIR; it only:
 *   - parses text commands from the serial port (host = Python backend),
 *   - renders the requested mode (non-blocking, millis()-driven),
 *   - reports PIR occupancy edges to the host as `EVENT PIR 1/0`.
 *
 * Protocol: arduino_nano_controller/protocol.md
 *   115200 baud, 8N1, '\n' line terminator.
 *   Commands : PING | SET_MODE <mode> | SET_BRIGHTNESS <0-255> | OFF
 *   Responses: PONG | OK <echo> | ERR UNKNOWN_COMMAND|UNKNOWN_MODE|BAD_ARG
 *   Events   : EVENT PIR 1 / EVENT PIR 0   (edge-triggered)
 *
 * Hardware:
 *   SR505 PIR OUT -> D8
 *   WS2812B DIN   -> D6
 *   Built-in LED  -> D13
 *
 * All animations are non-blocking and driven from millis() so the controller
 * stays responsive to serial input at all times.
 */

#include <FastLED.h>

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

CRGB leds[NUM_LEDS];

// ---------------------------------------------------------------------------
// Colors
// ---------------------------------------------------------------------------
const CRGB COLOR_OFF = CRGB::Black;
const CRGB COLOR_IDLE = CRGB::Cyan;
const CRGB COLOR_GREEN = CRGB::Green;
const CRGB COLOR_CYAN = CRGB::Cyan;
const CRGB COLOR_BLUE = CRGB::Blue;
const CRGB COLOR_PURPLE = CRGB::Purple;
const CRGB COLOR_WHITE = CRGB::White;

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
// Runtime state
// ---------------------------------------------------------------------------
LightMode currentMode = MODE_BOOT;
unsigned long modeStartedAtMs = 0;
unsigned long nowMs = 0;
uint8_t gBrightness = MAX_LED_BRIGHTNESS;

// PIR edge detection (independent of lighting)
bool sensorState = LOW;
bool previousSensorState = LOW;

// Serial command buffer
const int SERIAL_BUF_SIZE = 64;
char serialBuf[SERIAL_BUF_SIZE];
int serialIdx = 0;

// ---------------------------------------------------------------------------
// Function declarations
// ---------------------------------------------------------------------------
void updateSerial();
void handleCommand(char *cmd);
LightMode modeFromString(const String &m);

void updatePIR();
void updateLighting();
void transitionTo(LightMode nextMode);

uint8_t animationProgress(unsigned long durationMs);
uint8_t idleBreathBrightness(unsigned long timeMs);
uint8_t centerDistance(uint16_t index);
CRGB blendColor(const CRGB &from, const CRGB &to, uint8_t amount);

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

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup()
{
    pinMode(SENSOR_PIN, INPUT);
    pinMode(STATUS_LED_PIN, OUTPUT);

    FastLED.addLeds<WS2812B, LED_DATA_PIN, LED_COLOR_ORDER>(leds, NUM_LEDS);
    FastLED.setBrightness(gBrightness);
    FastLED.clear(true);

    Serial.begin(115200);
    while (!Serial)
    {
        ; // wait for serial port (needed on some boards)
    }
    Serial.println("SMARTDESK FW V2");

    sensorState = digitalRead(SENSOR_PIN);
    previousSensorState = sensorState;

    currentMode = MODE_BOOT;
    modeStartedAtMs = millis();
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------
// FIX (root cause confirmed via EXPERIMENT 1): FastLED.show() disables AVR
// interrupts for ~2 ms while clocking out 60 WS2812 bits. Any UART bytes that
// arrive during that window overflow the 1-2 byte hardware FIFO and are lost
// (this caused the random "SET_MODE" truncation). Fix:
//   (a) cap the LED refresh rate (~30 fps) so IRQs are enabled ~97% of the
//       time instead of being disabled every single frame,
//   (b) drain the serial port one more time immediately before FastLED.show(),
//       so bytes already in the buffer are processed before IRQs are disabled.
void loop()
{
    static const unsigned long SHOW_INTERVAL_MS = 33;  // ~30 fps cap
    static unsigned long lastShowMs = 0;

    nowMs = millis();

    updateSerial();   // drain received bytes while IRQs are enabled
    updatePIR();
    updateLighting();

    if (nowMs - lastShowMs >= SHOW_INTERVAL_MS)
    {
        updateSerial();   // final drain right before IRQs get disabled
        FastLED.show();
        lastShowMs = nowMs;
    }
}

// ---------------------------------------------------------------------------
// Serial command parsing
// ---------------------------------------------------------------------------
void updateSerial()
{
    while (Serial.available() > 0)
    {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r')
        {
            if (serialIdx > 0)
            {
                serialBuf[serialIdx] = '\0';
                handleCommand(serialBuf);
                serialIdx = 0;
            }
        }
        else if (serialIdx < SERIAL_BUF_SIZE - 1)
        {
            serialBuf[serialIdx++] = c;
        }
    }
}

void handleCommand(char *cmd)
{
    String s = String(cmd);
    s.trim();

    if (s.equalsIgnoreCase("PING"))
    {
        Serial.println("PONG");
        return;
    }

    if (s.startsWith("SET_MODE "))
    {
        String mode = s.substring(9);
        mode.trim();
        LightMode m = modeFromString(mode);
        if (m == MODE_UNKNOWN)
        {
            Serial.println("ERR UNKNOWN_MODE");
        }
        else
        {
            transitionTo(m);
            Serial.print("OK SET_MODE ");
            Serial.println(mode);
        }
        return;
    }

    if (s.startsWith("SET_BRIGHTNESS "))
    {
        String arg = s.substring(15);
        arg.trim();
        long val = arg.toInt();
        if (arg.length() == 0 || val < 0 || val > 255)
        {
            Serial.println("ERR BAD_ARG");
        }
        else
        {
            // Protocol is 0-255; clamp to the power-safe hardware ceiling.
            gBrightness = min((int)val, (int)MAX_LED_BRIGHTNESS);
            FastLED.setBrightness(gBrightness);
            Serial.print("OK SET_BRIGHTNESS ");
            Serial.println(val); // echo the original requested value
        }
        return;
    }

    if (s.equalsIgnoreCase("OFF"))
    {
        transitionTo(MODE_OFF);
        Serial.println("OK OFF");
        return;
    }

    Serial.println("ERR UNKNOWN_COMMAND");
}

LightMode modeFromString(const String &m)
{
    if (m.equalsIgnoreCase("BOOT")) return MODE_BOOT;
    if (m.equalsIgnoreCase("IDLE")) return MODE_IDLE;
    if (m.equalsIgnoreCase("WELCOME")) return MODE_WELCOME;
    if (m.equalsIgnoreCase("MEETING_ACTIVE")) return MODE_MEETING_ACTIVE;
    if (m.equalsIgnoreCase("AGENDA_ACTIVE")) return MODE_AGENDA_ACTIVE;
    if (m.equalsIgnoreCase("VOTE_OPEN")) return MODE_VOTE_OPEN;
    if (m.equalsIgnoreCase("VOTE_CLOSED")) return MODE_VOTE_CLOSED;
    if (m.equalsIgnoreCase("SERVICE_CALL")) return MODE_SERVICE_CALL;
    if (m.equalsIgnoreCase("MEETING_ENDED")) return MODE_MEETING_ENDED;
    if (m.equalsIgnoreCase("AI_SPEAKING")) return MODE_AI_SPEAKING;
    if (m.equalsIgnoreCase("ERROR")) return MODE_ERROR;
    if (m.equalsIgnoreCase("OFF")) return MODE_OFF;
    return MODE_UNKNOWN;
}

// ---------------------------------------------------------------------------
// PIR edge reporting (does NOT change lighting)
// ---------------------------------------------------------------------------
void updatePIR()
{
    previousSensorState = sensorState;
    sensorState = digitalRead(SENSOR_PIN);

    const bool risingEdge = (sensorState == HIGH && previousSensorState == LOW);
    const bool fallingEdge = (sensorState == LOW && previousSensorState == HIGH);

    if (risingEdge)
    {
        Serial.println("EVENT PIR 1");
    }
    if (fallingEdge)
    {
        Serial.println("EVENT PIR 0");
    }

    digitalWrite(STATUS_LED_PIN, sensorState == HIGH ? HIGH : LOW);
}

// ---------------------------------------------------------------------------
// Lighting dispatch
// ---------------------------------------------------------------------------
void updateLighting()
{
    switch (currentMode)
    {
        case MODE_BOOT: renderBoot(); break;
        case MODE_IDLE: renderIdle(); break;
        case MODE_WELCOME: renderWelcome(); break;
        case MODE_MEETING_ACTIVE: renderMeetingActive(); break;
        case MODE_AGENDA_ACTIVE: renderAgendaActive(); break;
        case MODE_VOTE_OPEN: renderVoteOpen(); break;
        case MODE_VOTE_CLOSED: renderVoteClosed(); break;
        case MODE_SERVICE_CALL: renderServiceCall(); break;
        case MODE_MEETING_ENDED: renderMeetingEnded(); break;
        case MODE_AI_SPEAKING: renderAiSpeaking(); break;
        case MODE_ERROR: renderError(); break;
        case MODE_OFF: renderOff(); break;
        case MODE_UNKNOWN: renderOff(); break;
    }
}

void transitionTo(LightMode nextMode)
{
    currentMode = nextMode;
    modeStartedAtMs = nowMs;
}

uint8_t animationProgress(unsigned long durationMs)
{
    if (durationMs == 0)
    {
        return 255;
    }
    const unsigned long elapsedMs = nowMs - modeStartedAtMs;
    if (elapsedMs >= durationMs)
    {
        return 255;
    }
    return map(elapsedMs, 0, durationMs, 0, 255);
}

// ---------------------------------------------------------------------------
// Mode renderers
// ---------------------------------------------------------------------------

// BOOT: brief white flash, then auto-enter IDLE.
void renderBoot()
{
    if (nowMs - modeStartedAtMs >= BOOT_DURATION_MS)
    {
        transitionTo(MODE_IDLE);
        return;
    }
    fill_solid(leds, NUM_LEDS, COLOR_WHITE);
}

// IDLE: slow low-brightness cyan breath.
void renderIdle()
{
    const uint8_t brightness = idleBreathBrightness(nowMs);
    const CRGB idleColor = blendColor(COLOR_OFF, COLOR_IDLE, brightness);
    fill_solid(leds, NUM_LEDS, idleColor);
}

// WELCOME: energy lights up from the center outward, holds, then auto-IDLE.
// Symmetrical fill grows from the two center LEDs (U-shaped seat = "center"),
// brightness surges once (a single breath of energy), holds 1 s, returns IDLE.
//  ~600 ms expand (within the 500-700 ms spec) + 1000 ms hold.
// WELCOME: energy lights up from the center outward, then a slow 5 s breath
// of color, then auto-IDLE. Total animation ≈ 5 s (per request) so the color
// keeps visibly changing throughout, not just the initial fill.
//  U-shaped seat = symmetric from the two center LEDs (29, 30).
void renderWelcome()
{
    const unsigned long t = nowMs - modeStartedAtMs;
    const unsigned long TOTAL_MS = 5000;    // full animation duration
    const unsigned long EXPAND_MS = 2000;    // center fill-out phase

    if (t >= TOTAL_MS)
    {
        transitionTo(MODE_IDLE);
        return;
    }

    // Radius fills from center over EXPAND_MS, then stays full.
    const uint16_t radius = (t < EXPAND_MS)
        ? (uint16_t)map((uint8_t)map(t, 0, EXPAND_MS, 0, 255), 0, 255, 1, 30)
        : 30;

    // One slow breath across the whole 5 s: brightness rises and falls so the
    // cyan-green color keeps visibly shifting until the mode auto-reverts.
    const uint8_t breath = sin8((uint8_t)((uint32_t)t * 255 / TOTAL_MS));
    const uint8_t brightness = (uint8_t)(90 + (uint16_t)breath * 165 / 255);  // 90..255

    const CRGB base = CRGB(0, 255, 140);    // cyan-green "energy"
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        // distance to the nearest of the two center LEDs (29, 30)
        const uint16_t d = (i <= 29) ? (29 - i) : (i - 30);
        leds[i] = (d < radius) ? blend(COLOR_OFF, base, brightness) : COLOR_OFF;
    }
}

// MEETING_ACTIVE: blue↔white slow breath.
void renderMeetingActive()
{
    const uint8_t brightness = idleBreathBrightness(nowMs);
    const CRGB c = blendColor(COLOR_BLUE, COLOR_WHITE, brightness);
    fill_solid(leds, NUM_LEDS, c);
}

// AGENDA_ACTIVE: soft white, brighter in the center (focus).
void renderAgendaActive()
{
    const uint8_t breath = map(sin8((nowMs / 20) & 0xFF), 0, 255, 140, 230);
    const uint8_t maxDist = centerDistance(0);
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        const uint8_t d = centerDistance(i);
        const uint8_t k = map(d, 0, maxDist, 255, 90);
        const uint8_t v = (uint16_t)breath * k / 255;
        leds[i] = CRGB(v, v, v);
    }
}

// VOTE_OPEN: yellow pulse.
void renderVoteOpen()
{
    const uint8_t b = map(sin8((nowMs / 6) & 0xFF), 0, 255, 40, 200);
    fill_solid(leds, NUM_LEDS, CRGB(b, (uint8_t)(b * 0.78), 0));
}

// VOTE_CLOSED: calm solid green.
void renderVoteClosed()
{
    fill_solid(leds, NUM_LEDS, COLOR_GREEN);
}

// SERVICE_CALL: fast orange-red blink.
void renderServiceCall()
{
    const uint8_t on = ((nowMs / 250) % 2 == 0) ? 255 : 30;
    fill_solid(leds, NUM_LEDS, CRGB(on, (uint8_t)(on / 3), 0));
}

// MEETING_ENDED: green contracts to center, then auto-enter IDLE.
void renderMeetingEnded()
{
    if (nowMs - modeStartedAtMs >= MEETING_ENDED_DURATION_MS)
    {
        transitionTo(MODE_IDLE);
        return;
    }
    const uint8_t progress = animationProgress(MEETING_ENDED_DURATION_MS);
    const uint8_t maxDist = centerDistance(0);
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        const uint8_t d = centerDistance(i);
        const bool on = ((uint16_t)d * 255) <= ((255 - progress) * maxDist);
        leds[i] = on ? COLOR_GREEN : COLOR_OFF;
    }
}

// AI_SPEAKING: neural-network breathing wave.
// A global brightness envelope breathes 0.10 .. 0.90 (the whole strip pulses
// 10%->30%->60%->90%->...), while each LED carries sin(x + t) so a wave
// travels along the strip like a signal propagating through a network.
// Fast 8-bit sin8() keeps this cheap on the AVR.
void renderAiSpeaking()
{
    // Global breathing envelope ~0.10 .. 0.90 (period ~2.8 s).
    const uint8_t envPhase = (uint8_t)(nowMs / 11);
    const uint16_t env = 26 + ((uint16_t)sin8(envPhase) * 204 / 255);  // 26..230

    // Traveling wave along the strip: each LED = sin(x + t).
    const uint8_t waveTime = (uint8_t)(nowMs / 10);   // march speed
    const uint8_t SPATIAL = 24;                        // phase units per LED (~10.7 LEDs/wave)

    const CRGB base = CRGB(140, 50, 230);             // violet-blue (tech)
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        const uint8_t wave = sin8((uint8_t)((uint16_t)i * SPATIAL + waveTime));
        const uint16_t wavePart = 26 + ((uint16_t)wave * 204 / 255);  // 26..230
        const uint16_t bi = (uint16_t)env * wavePart / 255;           // 0..230
        leds[i] = CRGB((base.r * bi) >> 8, (base.g * bi) >> 8, (base.b * bi) >> 8);
    }
}

// ERROR: slow red blink.
void renderError()
{
    const uint8_t on = ((nowMs / 600) % 2 == 0) ? 200 : 0;
    fill_solid(leds, NUM_LEDS, CRGB(on, 0, 0));
}

// OFF: strip dark.
void renderOff()
{
    fill_solid(leds, NUM_LEDS, COLOR_OFF);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
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
