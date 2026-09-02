#include "SmartDeskLighting.h"

namespace {
const CRGB COLOR_OFF = CRGB::Black;
const CRGB COLOR_IDLE = CRGB::Cyan;
const CRGB COLOR_GREEN = CRGB::Green;
const CRGB COLOR_BLUE = CRGB::Blue;
const CRGB COLOR_WHITE = CRGB::White;
}  // namespace

SmartDeskLighting::SmartDeskLighting(
    CRGB* leds,
    uint16_t ledCount,
    uint8_t maxBrightness)
    : leds_(leds),
      ledCount_(ledCount),
      maxBrightness_(maxBrightness),
      effectiveBrightness_(maxBrightness) {}

void SmartDeskLighting::begin(uint32_t nowMs) {
  currentMode_ = LightMode::BOOT;
  modeStartedAtMs_ = nowMs;
  lastShowAtMs_ = nowMs - LED_FRAME_MS;
  FastLED.setBrightness(effectiveBrightness_);
}

bool SmartDeskLighting::setMode(const String& mode, uint32_t nowMs) {
  const LightMode nextMode = modeFromName(mode);
  if (nextMode == LightMode::UNKNOWN) {
    return false;
  }
  currentMode_ = nextMode;
  modeStartedAtMs_ = nowMs;
  return true;
}

void SmartDeskLighting::setBrightness(uint8_t requestedBrightness) {
  effectiveBrightness_ = min(requestedBrightness, maxBrightness_);
  FastLED.setBrightness(effectiveBrightness_);
}

void SmartDeskLighting::render(uint32_t nowMs) {
  if (nowMs - lastShowAtMs_ < LED_FRAME_MS) {
    return;
  }
  lastShowAtMs_ = nowMs;

  switch (currentMode_) {
    case LightMode::BOOT:
      renderBoot(nowMs);
      break;
    case LightMode::IDLE:
      renderIdle(nowMs);
      break;
    case LightMode::WELCOME:
      renderWelcome(nowMs);
      break;
    case LightMode::MEETING_ACTIVE:
      renderMeetingActive(nowMs);
      break;
    case LightMode::AGENDA_ACTIVE:
      renderAgendaActive(nowMs);
      break;
    case LightMode::VOTE_OPEN:
      renderVoteOpen(nowMs);
      break;
    case LightMode::VOTE_CLOSED:
      renderVoteClosed();
      break;
    case LightMode::SERVICE_CALL:
      renderServiceCall(nowMs);
      break;
    case LightMode::MEETING_ENDED:
      renderMeetingEnded(nowMs);
      break;
    case LightMode::AI_SPEAKING:
      renderAiSpeaking(nowMs);
      break;
    case LightMode::ERROR:
      renderError(nowMs);
      break;
    case LightMode::OFF:
    case LightMode::UNKNOWN:
      renderOff();
      break;
  }
  FastLED.show();
}

const char* SmartDeskLighting::currentModeName() const {
  return modeName(currentMode_);
}

uint8_t SmartDeskLighting::effectiveBrightness() const {
  return effectiveBrightness_;
}

SmartDeskLighting::LightMode SmartDeskLighting::modeFromName(
    const String& mode) {
  if (mode == "BOOT") return LightMode::BOOT;
  if (mode == "IDLE") return LightMode::IDLE;
  if (mode == "WELCOME") return LightMode::WELCOME;
  if (mode == "MEETING_ACTIVE") return LightMode::MEETING_ACTIVE;
  if (mode == "AGENDA_ACTIVE") return LightMode::AGENDA_ACTIVE;
  if (mode == "VOTE_OPEN") return LightMode::VOTE_OPEN;
  if (mode == "VOTE_CLOSED") return LightMode::VOTE_CLOSED;
  if (mode == "SERVICE_CALL") return LightMode::SERVICE_CALL;
  if (mode == "MEETING_ENDED") return LightMode::MEETING_ENDED;
  if (mode == "AI_SPEAKING") return LightMode::AI_SPEAKING;
  if (mode == "ERROR") return LightMode::ERROR;
  if (mode == "OFF") return LightMode::OFF;
  return LightMode::UNKNOWN;
}

const char* SmartDeskLighting::modeName(LightMode mode) {
  switch (mode) {
    case LightMode::BOOT:
      return "BOOT";
    case LightMode::IDLE:
      return "IDLE";
    case LightMode::WELCOME:
      return "WELCOME";
    case LightMode::MEETING_ACTIVE:
      return "MEETING_ACTIVE";
    case LightMode::AGENDA_ACTIVE:
      return "AGENDA_ACTIVE";
    case LightMode::VOTE_OPEN:
      return "VOTE_OPEN";
    case LightMode::VOTE_CLOSED:
      return "VOTE_CLOSED";
    case LightMode::SERVICE_CALL:
      return "SERVICE_CALL";
    case LightMode::MEETING_ENDED:
      return "MEETING_ENDED";
    case LightMode::AI_SPEAKING:
      return "AI_SPEAKING";
    case LightMode::ERROR:
      return "ERROR";
    case LightMode::OFF:
      return "OFF";
    case LightMode::UNKNOWN:
      return "UNKNOWN";
  }
  return "UNKNOWN";
}

uint8_t SmartDeskLighting::animationProgress(
    uint32_t nowMs,
    uint32_t durationMs) const {
  if (durationMs == 0) {
    return 255;
  }
  const uint32_t elapsedMs = nowMs - modeStartedAtMs_;
  if (elapsedMs >= durationMs) {
    return 255;
  }
  return static_cast<uint8_t>((elapsedMs * 255UL) / durationMs);
}

uint8_t SmartDeskLighting::idleBreathBrightness(uint32_t nowMs) const {
  const uint8_t phase = static_cast<uint8_t>(
      ((nowMs % IDLE_BREATH_PERIOD_MS) * 255UL) /
      IDLE_BREATH_PERIOD_MS);
  const uint8_t wave = sin8(phase);
  return map(
      wave,
      0,
      255,
      IDLE_BRIGHTNESS_MIN,
      IDLE_BRIGHTNESS_MAX);
}

uint16_t SmartDeskLighting::centerDistance(uint16_t index) const {
  const uint16_t centerLeft = (ledCount_ - 1) / 2;
  const uint16_t centerRight = ledCount_ / 2;
  if (index <= centerLeft) {
    return centerLeft - index;
  }
  return index - centerRight;
}

uint16_t SmartDeskLighting::maximumCenterDistance() const {
  return centerDistance(0);
}

void SmartDeskLighting::renderBoot(uint32_t nowMs) {
  if (nowMs - modeStartedAtMs_ >= BOOT_DURATION_MS) {
    renderIdle(nowMs);
    return;
  }
  fill_solid(leds_, ledCount_, COLOR_WHITE);
}

void SmartDeskLighting::renderIdle(uint32_t nowMs) {
  const uint8_t amount = idleBreathBrightness(nowMs);
  fill_solid(leds_, ledCount_, blend(COLOR_OFF, COLOR_IDLE, amount));
}

void SmartDeskLighting::renderWelcome(uint32_t nowMs) {
  const uint32_t elapsedMs = nowMs - modeStartedAtMs_;
  if (elapsedMs >= WELCOME_DURATION_MS) {
    renderIdle(nowMs);
    return;
  }

  const uint16_t maxRadius = maximumCenterDistance() + 1;
  const uint16_t radius = elapsedMs < WELCOME_EXPAND_MS
      ? 1 + (elapsedMs * (maxRadius - 1)) / WELCOME_EXPAND_MS
      : maxRadius;
  const uint8_t breath = sin8(static_cast<uint8_t>(
      (elapsedMs * 255UL) / WELCOME_DURATION_MS));
  const uint8_t amount = static_cast<uint8_t>(
      90 + (static_cast<uint16_t>(breath) * 165U) / 255U);
  const CRGB base(0, 255, 140);

  for (uint16_t i = 0; i < ledCount_; ++i) {
    leds_[i] = centerDistance(i) < radius
        ? blend(COLOR_OFF, base, amount)
        : COLOR_OFF;
  }
}

void SmartDeskLighting::renderMeetingActive(uint32_t nowMs) {
  const uint8_t amount = idleBreathBrightness(nowMs);
  fill_solid(leds_, ledCount_, blend(COLOR_BLUE, COLOR_WHITE, amount));
}

void SmartDeskLighting::renderAgendaActive(uint32_t nowMs) {
  const uint8_t breath = map(sin8((nowMs / 20) & 0xFF), 0, 255, 140, 230);
  const uint16_t maxDistance = maximumCenterDistance();
  for (uint16_t i = 0; i < ledCount_; ++i) {
    const uint8_t focus = maxDistance == 0
        ? 255
        : map(centerDistance(i), 0, maxDistance, 255, 90);
    const uint8_t value =
        static_cast<uint16_t>(breath) * focus / 255U;
    leds_[i] = CRGB(value, value, value);
  }
}

void SmartDeskLighting::renderVoteOpen(uint32_t nowMs) {
  const uint8_t value = map(sin8((nowMs / 6) & 0xFF), 0, 255, 40, 200);
  fill_solid(
      leds_,
      ledCount_,
      CRGB(value, static_cast<uint8_t>(value * 0.78F), 0));
}

void SmartDeskLighting::renderVoteClosed() {
  fill_solid(leds_, ledCount_, COLOR_GREEN);
}

void SmartDeskLighting::renderServiceCall(uint32_t nowMs) {
  const uint8_t value = ((nowMs / 250) % 2 == 0) ? 255 : 30;
  fill_solid(leds_, ledCount_, CRGB(value, value / 3, 0));
}

void SmartDeskLighting::renderMeetingEnded(uint32_t nowMs) {
  if (nowMs - modeStartedAtMs_ >= MEETING_ENDED_DURATION_MS) {
    renderIdle(nowMs);
    return;
  }
  const uint8_t progress = animationProgress(
      nowMs,
      MEETING_ENDED_DURATION_MS);
  const uint16_t maxDistance = maximumCenterDistance();
  for (uint16_t i = 0; i < ledCount_; ++i) {
    const bool on = static_cast<uint32_t>(centerDistance(i)) * 255U <=
        static_cast<uint32_t>(255 - progress) * maxDistance;
    leds_[i] = on ? COLOR_GREEN : COLOR_OFF;
  }
}

void SmartDeskLighting::renderAiSpeaking(uint32_t nowMs) {
  const uint16_t envelope =
      26 + (static_cast<uint16_t>(sin8(nowMs / 11)) * 204U) / 255U;
  const uint8_t waveTime = static_cast<uint8_t>(nowMs / 10);
  const CRGB base(140, 50, 230);

  for (uint16_t i = 0; i < ledCount_; ++i) {
    const uint8_t wave = sin8(
        static_cast<uint8_t>(i * 24U + waveTime));
    const uint16_t wavePart =
        26 + (static_cast<uint16_t>(wave) * 204U) / 255U;
    const uint16_t amount = envelope * wavePart / 255U;
    leds_[i] = CRGB(
        (base.r * amount) >> 8,
        (base.g * amount) >> 8,
        (base.b * amount) >> 8);
  }
}

void SmartDeskLighting::renderError(uint32_t nowMs) {
  const uint8_t value = ((nowMs / 600) % 2 == 0) ? 200 : 0;
  fill_solid(leds_, ledCount_, CRGB(value, 0, 0));
}

void SmartDeskLighting::renderOff() {
  fill_solid(leds_, ledCount_, COLOR_OFF);
}
