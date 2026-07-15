// SmartDesk Lighting Controller — implementation.
// See SmartDeskLighting.h for the protocol/hardware contract.

#include <Arduino.h>
#include "SmartDeskLighting.h"

// Colors used only by the renderers (file-local).
namespace
{
    const CRGB COLOR_OFF    = CRGB::Black;
    const CRGB COLOR_IDLE   = CRGB::Cyan;
    const CRGB COLOR_GREEN  = CRGB::Green;
    const CRGB COLOR_CYAN   = CRGB::Cyan;
    const CRGB COLOR_BLUE   = CRGB::Blue;
    const CRGB COLOR_PURPLE = CRGB::Purple;
    const CRGB COLOR_WHITE  = CRGB::White;
}

// ---------------------------------------------------------------------------
// Construction / lifecycle
// ---------------------------------------------------------------------------
SmartDeskLighting::SmartDeskLighting() = default;

void SmartDeskLighting::begin()
{
    pinMode(SENSOR_PIN, INPUT);
    pinMode(STATUS_LED_PIN, OUTPUT);

    FastLED.addLeds<WS2812B, LED_DATA_PIN, LED_COLOR_ORDER>(leds_, NUM_LEDS);
    FastLED.setBrightness(gBrightness_);
    FastLED.clear(true);

    Wire.begin();
    tof_.init();
    tof_.setTimeout(500);
    tof_.startContinuous();
    delay(100);   // let the first ranging complete
    for (uint8_t i = 0; i < TOF_SAMPLES; i++) tofBuf_[i] = 9999;  // prefill 'far'

    Serial.begin(115200);
    while (!Serial)
    {
        ; // wait for serial port (needed on some boards)
    }
    Serial.println("SMARTDESK FW V2");

    sensorState_ = digitalRead(SENSOR_PIN);
    previousSensorState_ = sensorState_;

    currentMode_ = MODE_BOOT;
    modeStartedAtMs_ = millis();
}

void SmartDeskLighting::update()
{
    static const unsigned long SHOW_INTERVAL_MS = 33;  // ~30 fps cap

    nowMs_ = millis();

    updateSerial();   // drain received bytes while IRQs are enabled
    updatePIR();
    updateLighting();

    if (nowMs_ - lastShowMs_ >= SHOW_INTERVAL_MS)
    {
        updateSerial();   // final drain right before IRQs get disabled
        FastLED.show();
        lastShowMs_ = nowMs_;
    }
}

// ---------------------------------------------------------------------------
// Serial command parsing
// ---------------------------------------------------------------------------
void SmartDeskLighting::updateSerial()
{
    while (Serial.available() > 0)
    {
        char c = (char)Serial.read();
        if (c == '\n' || c == '\r')
        {
            if (serialIdx_ > 0)
            {
                serialBuf_[serialIdx_] = '\0';
                handleCommand(serialBuf_);
                serialIdx_ = 0;
            }
        }
        else if (serialIdx_ < SERIAL_BUF_SIZE - 1)
        {
            serialBuf_[serialIdx_++] = c;
        }
    }
}

void SmartDeskLighting::handleCommand(char *cmd)
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
        // String::toInt() returns 0 for non-numeric input, so we must validate
        // the characters ourselves BEFORE trusting the parsed value. Otherwise
        // "abc" would be accepted as brightness 0.
        if (!isDecimalNumber(arg))
        {
            Serial.println("ERR BAD_ARG");
            return;
        }
        long val = arg.toInt();
        if (val < 0 || val > 255)
        {
            Serial.println("ERR BAD_ARG");
        }
        else
        {
            // Protocol is 0-255; clamp to the power-safe hardware ceiling.
            gBrightness_ = min((int)val, (int)MAX_LED_BRIGHTNESS);
            FastLED.setBrightness(gBrightness_);
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

LightMode SmartDeskLighting::modeFromString(const String &m)
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
void SmartDeskLighting::updatePIR()
{
    // VL53L0X runs in continuous mode; a single read returns the latest
    // measurement. To average 5-10 samples without blocking, push one reading
    // per ~33 ms frame into a ring buffer and use the mean of the last N.
    const int raw = tof_.readRangeContinuousMillimeters();
    const bool tofOk = !tof_.timeoutOccurred();
    if (tofOk)
    {
        tofBuf_[tofIdx_] = raw;
        tofIdx_ = (tofIdx_ + 1) % TOF_SAMPLES;
    }
    long sum = 0;
    for (uint8_t i = 0; i < TOF_SAMPLES; i++) sum += tofBuf_[i];
    const int distMm = (int)(sum / TOF_SAMPLES);

    previousSensorState_ = sensorState_;
    sensorState_ = digitalRead(SENSOR_PIN);

    // Occupancy = PIR motion AND close proximity (<100 mm). A passer-by
    // (PIR high but far away) no longer triggers the welcome animation.
    static bool seatedPrev = false;
    const bool seatedNow = (sensorState_ == HIGH) && (distMm < 100) && tofOk;
    const bool risingEdge  = seatedNow && !seatedPrev;
    const bool fallingEdge = !seatedNow && seatedPrev;
    if (risingEdge)  Serial.println("EVENT PIR 1");
    if (fallingEdge) Serial.println("EVENT PIR 0");
    seatedPrev = seatedNow;

    digitalWrite(STATUS_LED_PIN, sensorState_ == HIGH ? HIGH : LOW);
}

// ---------------------------------------------------------------------------
// Lighting dispatch
// ---------------------------------------------------------------------------
void SmartDeskLighting::updateLighting()
{
    switch (currentMode_)
    {
        case MODE_BOOT:           renderBoot();           break;
        case MODE_IDLE:           renderIdle();           break;
        case MODE_WELCOME:        renderWelcome();        break;
        case MODE_MEETING_ACTIVE: renderMeetingActive();  break;
        case MODE_AGENDA_ACTIVE:  renderAgendaActive();   break;
        case MODE_VOTE_OPEN:      renderVoteOpen();       break;
        case MODE_VOTE_CLOSED:    renderVoteClosed();     break;
        case MODE_SERVICE_CALL:   renderServiceCall();    break;
        case MODE_MEETING_ENDED:  renderMeetingEnded();   break;
        case MODE_AI_SPEAKING:    renderAiSpeaking();     break;
        case MODE_ERROR:          renderError();          break;
        case MODE_OFF:            renderOff();            break;
        case MODE_UNKNOWN:        renderOff();            break;
    }
}

void SmartDeskLighting::transitionTo(LightMode nextMode)
{
    currentMode_ = nextMode;
    modeStartedAtMs_ = nowMs_;
}

uint8_t SmartDeskLighting::animationProgress(unsigned long durationMs)
{
    if (durationMs == 0)
    {
        return 255;
    }
    const unsigned long elapsedMs = nowMs_ - modeStartedAtMs_;
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
void SmartDeskLighting::renderBoot()
{
    if (nowMs_ - modeStartedAtMs_ >= BOOT_DURATION_MS)
    {
        transitionTo(MODE_IDLE);
        return;
    }
    fill_solid(leds_, NUM_LEDS, COLOR_WHITE);
}

// IDLE: slow low-brightness cyan breath.
void SmartDeskLighting::renderIdle()
{
    const uint8_t brightness = idleBreathBrightness(nowMs_);
    const CRGB idleColor = blendColor(COLOR_OFF, COLOR_IDLE, brightness);
    fill_solid(leds_, NUM_LEDS, idleColor);
}

// WELCOME: center-out energy fill, one slow breath, then auto-IDLE (~5 s).
void SmartDeskLighting::renderWelcome()
{
    const unsigned long t = nowMs_ - modeStartedAtMs_;
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

    // One slow breath across the whole 5 s keeps the color visibly shifting.
    const uint8_t breath = sin8((uint8_t)((uint32_t)t * 255 / TOTAL_MS));
    const uint8_t brightness = (uint8_t)(90 + (uint16_t)breath * 165 / 255);  // 90..255

    const CRGB base = CRGB(0, 255, 140);    // cyan-green "energy"
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        // distance to the nearest of the two center LEDs (29, 30)
        const uint16_t d = (i <= 29) ? (29 - i) : (i - 30);
        leds_[i] = (d < radius) ? blend(COLOR_OFF, base, brightness) : COLOR_OFF;
    }
}

// MEETING_ACTIVE: blue<->white slow breath.
void SmartDeskLighting::renderMeetingActive()
{
    const uint8_t brightness = idleBreathBrightness(nowMs_);
    const CRGB c = blendColor(COLOR_BLUE, COLOR_WHITE, brightness);
    fill_solid(leds_, NUM_LEDS, c);
}

// AGENDA_ACTIVE: soft white, brighter in the center (focus).
void SmartDeskLighting::renderAgendaActive()
{
    const uint8_t breath = map(sin8((nowMs_ / 20) & 0xFF), 0, 255, 140, 230);
    const uint8_t maxDist = centerDistance(0);
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        const uint8_t d = centerDistance(i);
        const uint8_t k = map(d, 0, maxDist, 255, 90);
        const uint8_t v = (uint16_t)breath * k / 255;
        leds_[i] = CRGB(v, v, v);
    }
}

// VOTE_OPEN: yellow pulse.
void SmartDeskLighting::renderVoteOpen()
{
    const uint8_t b = map(sin8((nowMs_ / 6) & 0xFF), 0, 255, 40, 200);
    fill_solid(leds_, NUM_LEDS, CRGB(b, (uint8_t)(b * 0.78), 0));
}

// VOTE_CLOSED: calm solid green.
void SmartDeskLighting::renderVoteClosed()
{
    fill_solid(leds_, NUM_LEDS, COLOR_GREEN);
}

// SERVICE_CALL: fast orange-red blink.
void SmartDeskLighting::renderServiceCall()
{
    const uint8_t on = ((nowMs_ / 250) % 2 == 0) ? 255 : 30;
    fill_solid(leds_, NUM_LEDS, CRGB(on, (uint8_t)(on / 3), 0));
}

// MEETING_ENDED: green contracts to center, then auto-enter IDLE.
void SmartDeskLighting::renderMeetingEnded()
{
    if (nowMs_ - modeStartedAtMs_ >= MEETING_ENDED_DURATION_MS)
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
        leds_[i] = on ? COLOR_GREEN : COLOR_OFF;
    }
}

// AI_SPEAKING: neural-network breathing wave travelling along the strip.
void SmartDeskLighting::renderAiSpeaking()
{
    // Global breathing envelope ~0.10 .. 0.90 (period ~2.8 s).
    const uint8_t envPhase = (uint8_t)(nowMs_ / 11);
    const uint16_t env = 26 + ((uint16_t)sin8(envPhase) * 204 / 255);  // 26..230

    // Travelling wave along the strip: each LED = sin(x + t).
    const uint8_t waveTime = (uint8_t)(nowMs_ / 10);   // march speed
    const uint8_t SPATIAL = 24;                        // phase units per LED (~10.7 LEDs/wave)

    const CRGB base = CRGB(140, 50, 230);             // violet-blue (tech)
    for (uint16_t i = 0; i < NUM_LEDS; i++)
    {
        const uint8_t wave = sin8((uint8_t)((uint16_t)i * SPATIAL + waveTime));
        const uint16_t wavePart = 26 + ((uint16_t)wave * 204 / 255);  // 26..230
        const uint16_t bi = (uint16_t)env * wavePart / 255;           // 0..230
        leds_[i] = CRGB((base.r * bi) >> 8, (base.g * bi) >> 8, (base.b * bi) >> 8);
    }
}

// ERROR: slow red blink.
void SmartDeskLighting::renderError()
{
    const uint8_t on = ((nowMs_ / 600) % 2 == 0) ? 200 : 0;
    fill_solid(leds_, NUM_LEDS, CRGB(on, 0, 0));
}

// OFF: strip dark.
void SmartDeskLighting::renderOff()
{
    fill_solid(leds_, NUM_LEDS, COLOR_OFF);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
CRGB SmartDeskLighting::blendColor(const CRGB &fromColor, const CRGB &toColor, uint8_t amount)
{
    return blend(fromColor, toColor, amount);
}

bool SmartDeskLighting::isDecimalNumber(const String &str)
{
    if (str.length() == 0)
    {
        return false;
    }
    for (unsigned int i = 0; i < str.length(); i++)
    {
        const char c = str.charAt(i);
        if (c < '0' || c > '9')
        {
            return false;
        }
    }
    return true;
}

uint8_t SmartDeskLighting::idleBreathBrightness(unsigned long timeMs)
{
    const uint16_t phase = ((timeMs % IDLE_BREATH_PERIOD_MS) * 255UL) / IDLE_BREATH_PERIOD_MS;
    const uint8_t wave = sin8(phase);
    return map(wave, 0, 255, IDLE_BRIGHTNESS_MIN, IDLE_BRIGHTNESS_MAX);
}

uint8_t SmartDeskLighting::centerDistance(uint16_t index)
{
    const uint16_t centerLeft = (NUM_LEDS - 1) / 2;
    const uint16_t centerRight = NUM_LEDS / 2;

    if (index <= centerLeft)
    {
        return centerLeft - index;
    }
    return index - centerRight;
}
