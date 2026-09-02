#pragma once

#include <Arduino.h>
#include <FastLED.h>

class SmartDeskLighting {
 public:
  SmartDeskLighting(
      CRGB* leds,
      uint16_t ledCount,
      uint8_t maxBrightness);

  void begin(uint32_t nowMs);
  bool setMode(const String& mode, uint32_t nowMs);
  void setBrightness(uint8_t requestedBrightness);
  void render(uint32_t nowMs);

  const char* currentModeName() const;
  uint8_t effectiveBrightness() const;

 private:
  enum class LightMode : uint8_t {
    BOOT,
    IDLE,
    WELCOME,
    MEETING_ACTIVE,
    AGENDA_ACTIVE,
    VOTE_OPEN,
    VOTE_CLOSED,
    SERVICE_CALL,
    MEETING_ENDED,
    AI_SPEAKING,
    ERROR,
    OFF,
    UNKNOWN,
  };

  static constexpr uint32_t LED_FRAME_MS = 20;
  static constexpr uint32_t IDLE_BREATH_PERIOD_MS = 3000;
  static constexpr uint8_t IDLE_BRIGHTNESS_MIN = 10;
  static constexpr uint8_t IDLE_BRIGHTNESS_MAX = 35;
  static constexpr uint32_t BOOT_DURATION_MS = 800;
  static constexpr uint32_t WELCOME_DURATION_MS = 5000;
  static constexpr uint32_t WELCOME_EXPAND_MS = 2000;
  static constexpr uint32_t MEETING_ENDED_DURATION_MS = 1500;

  CRGB* leds_;
  uint16_t ledCount_;
  uint8_t maxBrightness_;
  uint8_t effectiveBrightness_;
  LightMode currentMode_ = LightMode::BOOT;
  uint32_t modeStartedAtMs_ = 0;
  uint32_t lastShowAtMs_ = 0;

  static LightMode modeFromName(const String& mode);
  static const char* modeName(LightMode mode);

  uint8_t animationProgress(uint32_t nowMs, uint32_t durationMs) const;
  uint8_t idleBreathBrightness(uint32_t nowMs) const;
  uint16_t centerDistance(uint16_t index) const;
  uint16_t maximumCenterDistance() const;

  void renderBoot(uint32_t nowMs);
  void renderIdle(uint32_t nowMs);
  void renderWelcome(uint32_t nowMs);
  void renderMeetingActive(uint32_t nowMs);
  void renderAgendaActive(uint32_t nowMs);
  void renderVoteOpen(uint32_t nowMs);
  void renderVoteClosed();
  void renderServiceCall(uint32_t nowMs);
  void renderMeetingEnded(uint32_t nowMs);
  void renderAiSpeaking(uint32_t nowMs);
  void renderError(uint32_t nowMs);
  void renderOff();
};
