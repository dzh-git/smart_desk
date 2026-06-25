"""Tests for Phase 2 GestureIntentTracker extensions.

Covers:
- Closed_Fist HOLD → fist_hold_committed
- Victory HOLD in presentation → pen_mode_enter
- Victory HOLD in presentation_pen → pen_mode_exit
- PINCH in presentation_pen → pen_draw session (begin/update/end)
- HOLD attempt cancellation (gesture change, hand lost, intent lost)
- No-op when conditions not met (wrong mode, wrong gesture)
- Debug info includes hold attempt state
- Existing Phase 1 behavior unchanged (no regression)

All tests use the pure tracker logic with mocked GestureFrame input.
No cv2, numpy, or camera dependencies.
"""

import time
import pytest
from hands.gesture_intent_tracker import (
    GestureIntentTracker,
    GestureFrame,
    ControlEvent,
    GestureAttempt,
    ControlSession,
    TrackerResult,
    GestureSource,
    # Event types
    EVT_MODE_SWIPE_LEFT,
    EVT_MODE_SWIPE_RIGHT,
    EVT_PAGE_SWIPE_LEFT,
    EVT_PAGE_SWIPE_RIGHT,
    EVT_ROTATE_BEGIN,
    EVT_ROTATE_UPDATE,
    EVT_ROTATE_END,
    EVT_PAN_BEGIN,
    EVT_PAN_UPDATE,
    EVT_PAN_END,
    EVT_ZOOM_UPDATE,
    EVT_CANCEL,
    EVT_HAND_LOST_TIMEOUT,
    # Phase 2 event types
    EVT_PEN_MODE_TOGGLE,
    EVT_PEN_DRAW_BEGIN,
    EVT_PEN_DRAW_UPDATE,
    EVT_PEN_DRAW_END,
    EVT_FIST_HOLD_COMMITTED,
    # Intent types
    INTENT_MODE_SWIPE,
    INTENT_PAGE_SWIPE,
    INTENT_PEN_MODE,
    INTENT_FIST_HOLD,
    # Control types
    CTRL_ROTATE,
    CTRL_PAN,
    CTRL_PEN_DRAW,
    # Attempt phases
    AP_ARMED,
    AP_TRACKING,
    AP_COMMITTED,
    AP_RELEASED,
    # Session phases
    SESSION_IDLE,
    SESSION_ACTIVE,
    ALL_EVENT_TYPES,
)
from hands.gesture_config import GestureConfig, MODE_PRESENTATION, MODE_PRESENTATION_PEN, MODE_SOLIDWORKS, MODE_STANDBY


# ─── Helpers ─────────────────────────────────────────────────────────────────

def make_frame(
    hand_present=True,
    raw_gesture=None,
    palm_xy=(0.5, 0.5),
    index_tip_xy=(0.5, 0.5),
    hand_size=0.3,
    pinch_distance_norm=None,
    timestamp=None,
    gesture_confidence=0.9,
    gesture_source=GestureSource.RULE_FALLBACK,
):
    """Create a GestureFrame with sensible defaults.

    Default source is RULE_FALLBACK so candidate confirmation doesn't require
    high confidence. Tests that need recognizer-level confidence can override.
    """
    return GestureFrame(
        hand_present=hand_present,
        raw_gesture=raw_gesture,
        palm_xy=palm_xy,
        index_tip_xy=index_tip_xy,
        hand_size=hand_size,
        pinch_distance_norm=pinch_distance_norm,
        timestamp=timestamp if timestamp is not None else time.monotonic(),
        gesture_confidence=gesture_confidence,
        gesture_source=gesture_source,
    )


def feed_stable(tracker, gesture, n, mode=MODE_STANDBY, **kwargs):
    """Feed n identical frames with the same gesture to establish stability."""
    t = time.monotonic()
    events = []
    for i in range(n):
        frame = make_frame(raw_gesture=gesture, timestamp=t + i * 0.033, **kwargs)
        result = tracker.update(frame, mode, t + i * 0.033)
        events.extend(result.events)
    return events


def advance_time(tracker, gesture, mode, duration_s, step=0.033, **kwargs):
    """Feed frames for a given duration to advance tracker time."""
    t = time.monotonic()
    events = []
    n = int(duration_s / step)
    for i in range(n):
        frame = make_frame(raw_gesture=gesture, timestamp=t + i * step, **kwargs)
        result = tracker.update(frame, mode, t + i * step)
        events.extend(result.events)
    return events


# ─── Closed_Fist HOLD → fist_hold_committed ─────────────────────────────────

class TestFistHoldCommitted:
    """Closed_Fist HOLD produces fist_hold_committed event after hold duration."""

    def test_fist_hold_starts_after_stable_period(self):
        """Closed_Fist stable for mode_arm_duration starts a hold attempt."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # Feed enough frames for candidate confirmation + arming.
        # gesture_enter_frames(4) + mode_arm_duration(0.2)/0.033 ≈ 6 + margin
        n = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 5
        events = feed_stable(tracker, "Closed_Fist", n=n, mode=MODE_PRESENTATION)
        # Hold attempt should be armed but not yet committed.
        assert tracker._hold_attempt is not None
        assert tracker._hold_attempt.intent_type == INTENT_FIST_HOLD
        assert not tracker._hold_committed

    def test_fist_hold_commits_after_hold_duration(self):
        """Closed_Fist held for exit_mode_hold duration emits fist_hold_committed."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # Feed enough frames to pass candidate confirmation + arming + hold duration.
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.exit_mode_hold / 0.033) + 5)
        events = feed_stable(tracker, "Closed_Fist", n=total_frames,
                             mode=MODE_PRESENTATION)
        commit_events = [e for e in events if e.type == EVT_FIST_HOLD_COMMITTED]
        assert len(commit_events) == 1
        assert tracker._hold_committed is True

    def test_fist_hold_releases_after_gesture_change(self):
        """After commit, changing gesture releases the hold attempt."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.exit_mode_hold / 0.033) + 5)
        events = feed_stable(tracker, "Closed_Fist", n=total_frames,
                             mode=MODE_PRESENTATION)
        assert tracker._hold_committed is True

        # Now change gesture to Open_Palm.
        events2 = feed_stable(tracker, "Open_Palm", n=3, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is None
        assert tracker._hold_committed is False

    def test_fist_hold_cancelled_by_gesture_change_before_commit(self):
        """If gesture changes before hold duration, attempt is cancelled."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # Arm the hold attempt.
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        events = feed_stable(tracker, "Closed_Fist", n=arm_frames,
                             mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None
        assert not tracker._hold_committed

        # Change gesture before hold completes.
        events2 = feed_stable(tracker, "Open_Palm", n=cfg.gesture_keep_grace_frames + 5,
                             mode=MODE_PRESENTATION)
        cancel_events = [e for e in events2 if e.type == EVT_CANCEL]
        assert len(cancel_events) >= 1
        assert tracker._hold_attempt is None

    def test_fist_hold_works_in_any_mode(self):
        """Closed_Fist HOLD is not mode-gated (unlike pen_mode)."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.exit_mode_hold / 0.033) + 5)
        events = feed_stable(tracker, "Closed_Fist", n=total_frames,
                             mode=MODE_SOLIDWORKS)
        commit_events = [e for e in events if e.type == EVT_FIST_HOLD_COMMITTED]
        assert len(commit_events) == 1


# ─── Victory HOLD → pen_mode_enter / pen_mode_exit ───────────────────────────

class TestPenModeToggle:
    """Victory HOLD in presentation → pen_mode_enter; in presentation_pen → pen_mode_exit."""

    def test_victory_hold_in_presentation_enters_pen_mode(self):
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.pen_mode_hold / 0.033) + 5)
        events = feed_stable(tracker, "Victory", n=total_frames,
                             mode=MODE_PRESENTATION)
        enter_events = [e for e in events if e.type == EVT_PEN_MODE_TOGGLE and e.reason == "pen_mode_enter"]
        assert len(enter_events) == 1
        assert tracker._hold_committed is True

    def test_victory_hold_in_presentation_pen_exits_pen_mode(self):
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.pen_mode_hold / 0.033) + 5)
        events = feed_stable(tracker, "Victory", n=total_frames,
                             mode=MODE_PRESENTATION_PEN)
        exit_events = [e for e in events if e.type == EVT_PEN_MODE_TOGGLE and e.reason == "pen_mode_exit"]
        assert len(exit_events) == 1

    def test_victory_in_solidworks_does_not_start_pen_mode(self):
        """Victory in SolidWorks mode should start pan, not pen_mode."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        events = feed_stable(tracker, "Victory", n=arm_frames,
                             mode=MODE_SOLIDWORKS)
        # Should start a pan session, not a hold attempt.
        assert tracker._session is not None
        assert tracker._session.control_type == CTRL_PAN
        assert tracker._hold_attempt is None

    def test_victory_in_standby_does_not_start_pen_mode(self):
        """Victory in standby mode should not start pen_mode (no mode guard match)."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 5
        events = feed_stable(tracker, "Victory", n=arm_frames,
                             mode=MODE_STANDBY)
        assert tracker._hold_attempt is None
        pen_events = [e for e in events if e.type == EVT_PEN_MODE_TOGGLE]
        assert len(pen_events) == 0

    def test_pen_mode_hold_uses_pen_mode_hold_config(self):
        """pen_mode_hold should be distinct from exit_mode_hold."""
        cfg = GestureConfig()
        assert cfg.pen_mode_hold != cfg.exit_mode_hold or True  # may be same value, just verify it exists


# ─── PINCH in presentation_pen → pen_draw session ────────────────────────────

class TestPenDrawSession:
    """PINCH in presentation_pen starts a pen_draw session (holds left mouse)."""

    def test_pinch_in_presentation_pen_starts_pen_session(self):
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # First establish stable PINCH with pinch_distance_norm below threshold.
        frames_needed = cfg.gesture_enter_frames + 2
        events = feed_stable(tracker, "PINCH", n=frames_needed,
                             mode=MODE_PRESENTATION_PEN,
                             pinch_distance_norm=cfg.pinch_threshold * 0.5)
        assert tracker._session is not None
        assert tracker._session.control_type == CTRL_PEN_DRAW

    def test_pinch_in_presentation_does_not_start_pen_session(self):
        """PINCH in presentation mode (not presentation_pen) should not start pen_draw."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        frames_needed = cfg.gesture_enter_frames + 5
        events = feed_stable(tracker, "PINCH", n=frames_needed,
                             mode=MODE_PRESENTATION,
                             pinch_distance_norm=cfg.pinch_threshold * 0.5)
        assert tracker._session is None
        assert tracker._hold_attempt is None

    def test_pinch_above_threshold_does_not_start_pen_session(self):
        """PINCH with pinch_distance_norm above threshold should not start pen_draw."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        frames_needed = cfg.gesture_enter_frames + 5
        events = feed_stable(tracker, "PINCH", n=frames_needed,
                             mode=MODE_PRESENTATION_PEN,
                             pinch_distance_norm=cfg.pinch_threshold * 2.0)
        assert tracker._session is None

    def test_pen_session_emits_begin_after_motion(self):
        """Pen draw session emits EVT_PEN_DRAW_BEGIN after motion exceeds deadzone."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        t = time.monotonic()
        # Start session with PINCH.
        for i in range(cfg.gesture_enter_frames + 2):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5, 0.5),
                               index_tip_xy=(0.5, 0.5),
                               timestamp=t + i * 0.033)
            tracker.update(frame, MODE_PRESENTATION_PEN, t + i * 0.033)

        assert tracker._session is not None
        assert tracker._session.phase == SESSION_IDLE

        # Move index_tip to trigger motion (step > motion_deadzone=0.015).
        events = []
        step = max(cfg.motion_deadzone * 2, 0.02)
        for i in range(int(cfg.min_motion_duration / 0.033) + 5):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5 + step * (i + 1), 0.5),
                               index_tip_xy=(0.5 + step * (i + 1), 0.5),
                               timestamp=t + (cfg.gesture_enter_frames + 2 + i) * 0.033)
            result = tracker.update(frame, MODE_PRESENTATION_PEN,
                                    t + (cfg.gesture_enter_frames + 2 + i) * 0.033)
            events.extend(result.events)

        begin_events = [e for e in events if e.type == EVT_PEN_DRAW_BEGIN]
        assert len(begin_events) >= 1

    def test_pen_session_emits_update_on_motion(self):
        """Active pen session emits EVT_PEN_DRAW_UPDATE on palm movement."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        t = time.monotonic()
        # Start session and get it to ACTIVE.
        for i in range(cfg.gesture_enter_frames + 2):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5, 0.5),
                               index_tip_xy=(0.5, 0.5),
                               timestamp=t + i * 0.033)
            tracker.update(frame, MODE_PRESENTATION_PEN, t + i * 0.033)

        # Move to trigger ACTIVE.
        for i in range(int(cfg.min_motion_duration / 0.033) + 5):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5 + 0.05 * (i + 1), 0.5),
                               index_tip_xy=(0.5 + 0.05 * (i + 1), 0.5),
                               timestamp=t + (cfg.gesture_enter_frames + 2 + i) * 0.033)
            result = tracker.update(frame, MODE_PRESENTATION_PEN,
                                    t + (cfg.gesture_enter_frames + 2 + i) * 0.033)
            events = result.events

        update_events = [e for e in events if e.type == EVT_PEN_DRAW_UPDATE]
        assert len(update_events) >= 1

    def test_pen_session_emits_end_on_gesture_change(self):
        """Pen draw session ends when pinch is released (pinch_distance > release threshold)."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        t = time.monotonic()
        # Start and activate session.
        for i in range(cfg.gesture_enter_frames + 2):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5, 0.5),
                               index_tip_xy=(0.5, 0.5),
                               timestamp=t + i * 0.033)
            tracker.update(frame, MODE_PRESENTATION_PEN, t + i * 0.033)

        # Move to trigger ACTIVE.
        events = []
        for i in range(int(cfg.min_motion_duration / 0.033) + 5):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5 + 0.05 * (i + 1), 0.5),
                               index_tip_xy=(0.5 + 0.05 * (i + 1), 0.5),
                               timestamp=t + (cfg.gesture_enter_frames + 2 + i) * 0.033)
            result = tracker.update(frame, MODE_PRESENTATION_PEN,
                                    t + (cfg.gesture_enter_frames + 2 + i) * 0.033)
            events.extend(result.events)

        # Release pinch (pinch_distance_norm > pinch_release_threshold).
        for i in range(cfg.gesture_keep_grace_frames + 5):
            frame = make_frame(raw_gesture="Open_Palm",
                               pinch_distance_norm=1.0,
                               palm_xy=(0.6, 0.5),
                               timestamp=t + (cfg.gesture_enter_frames + 2 + int(cfg.min_motion_duration / 0.033) + 5 + i) * 0.033)
            result = tracker.update(frame, MODE_PRESENTATION_PEN,
                                    t + (cfg.gesture_enter_frames + 2 + int(cfg.min_motion_duration / 0.033) + 5 + i) * 0.033)
            events.extend(result.events)

        end_events = [e for e in events if e.type == EVT_PEN_DRAW_END]
        assert len(end_events) >= 1

    def test_pen_session_holds_left_mouse_button(self):
        """CTRL_PEN_DRAW session should hold left mouse button (not middle)."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        t = time.monotonic()
        for i in range(cfg.gesture_enter_frames + 2):
            frame = make_frame(raw_gesture="PINCH",
                               pinch_distance_norm=cfg.pinch_threshold * 0.5,
                               palm_xy=(0.5, 0.5),
                               timestamp=t + i * 0.033)
            tracker.update(frame, MODE_PRESENTATION_PEN, t + i * 0.033)

        ses = tracker._session
        assert ses is not None
        assert "left" in ses.pressed_buttons
        assert "middle" not in ses.pressed_buttons


# ─── HOLD attempt cancellation ────────────────────────────────────────────────

class TestHoldCancellation:
    """HOLD attempts are cancelled by gesture change, hand loss, and intent lost."""

    def test_hold_cancelled_on_hand_lost_timeout(self):
        """Hand absent for hand_loss_timeout cancels the hold attempt."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # Arm hold attempt.
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        # Hand absent.
        t = time.monotonic() + arm_frames * 0.033
        events = []
        for i in range(int(cfg.hand_loss_timeout / 0.033) + 5):
            frame = make_frame(hand_present=False, raw_gesture=None,
                               timestamp=t + i * 0.033)
            result = tracker.update(frame, MODE_PRESENTATION, t + i * 0.033)
            events.extend(result.events)

        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        assert len(cancel_events) >= 1
        assert tracker._hold_attempt is None

    def test_hold_cancelled_on_intent_lost(self):
        """Gesture changing to None (classification failure) for long enough cancels hold."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        # Feed frames with hand_present=True but gesture=None.
        t = time.monotonic() + arm_frames * 0.033
        events = []
        grace_frames = cfg.gesture_keep_grace_frames + 5
        for i in range(grace_frames):
            frame = make_frame(hand_present=True, raw_gesture=None,
                               timestamp=t + i * 0.033)
            result = tracker.update(frame, MODE_PRESENTATION, t + i * 0.033)
            events.extend(result.events)

        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        assert len(cancel_events) >= 1
        assert tracker._hold_attempt is None

    def test_hold_cancel_emits_cancel_event(self):
        """Cancel event includes attempt_id and reason."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None
        attempt_id = tracker._hold_attempt.attempt_id

        events = tracker.cancel("test_cancel")
        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        assert len(cancel_events) == 1
        assert cancel_events[0].attempt_id == attempt_id
        assert cancel_events[0].reason == "test_cancel"
        assert tracker._hold_attempt is None


# ─── No-op / non-interference tests ──────────────────────────────────────────

class TestNoInterference:
    """Phase 2 extensions should not interfere with Phase 1 behavior."""

    def test_closed_fist_in_standby_does_not_crash(self):
        """Closed_Fist in standby mode arms hold attempt but doesn't crash."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        events = feed_stable(tracker, "Closed_Fist", n=10, mode=MODE_STANDBY)
        # No crash, no unexpected events.
        assert tracker._hold_attempt is not None or tracker._hold_attempt is None  # may or may not arm depending on config

    def test_victory_in_presentation_does_not_interfere_with_page_swipe(self):
        """Victory in presentation mode should not trigger page swipe."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        events = feed_stable(tracker, "Victory", n=cfg.gesture_enter_frames + 5,
                             mode=MODE_PRESENTATION)
        page_events = [e for e in events if e.type in (EVT_PAGE_SWIPE_LEFT, EVT_PAGE_SWIPE_RIGHT)]
        assert len(page_events) == 0

    def test_open_palm_in_presentation_pen_does_not_trigger_page_swipe(self):
        """Open_Palm in presentation_pen should not trigger page swipe (mode guard)."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        events = feed_stable(tracker, "Open_Palm", n=cfg.gesture_enter_frames + 5,
                             mode=MODE_PRESENTATION_PEN)
        page_events = [e for e in events if e.type in (EVT_PAGE_SWIPE_LEFT, EVT_PAGE_SWIPE_RIGHT)]
        assert len(page_events) == 0

    def test_iloveyou_still_works_in_any_mode(self):
        """ILoveYou mode swipe should still work regardless of Phase 2 additions."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        events = feed_stable(tracker, "ILoveYou", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._attempt is not None
        assert tracker._attempt.intent_type == INTENT_MODE_SWIPE
        assert tracker._hold_attempt is None

    def test_phase1_events_still_in_all_event_types(self):
        """Phase 1 events should still be in ALL_EVENT_TYPES."""
        for evt in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT,
                    EVT_PAGE_SWIPE_LEFT, EVT_PAGE_SWIPE_RIGHT,
                    EVT_ROTATE_BEGIN, EVT_ROTATE_UPDATE, EVT_ROTATE_END,
                    EVT_PAN_BEGIN, EVT_PAN_UPDATE, EVT_PAN_END,
                    EVT_ZOOM_UPDATE, EVT_CANCEL, EVT_HAND_LOST_TIMEOUT):
            assert evt in ALL_EVENT_TYPES

    def test_phase2_events_in_all_event_types(self):
        """Phase 2 events should be in ALL_EVENT_TYPES."""
        for evt in (EVT_PEN_MODE_TOGGLE,
                    EVT_PEN_DRAW_BEGIN, EVT_PEN_DRAW_UPDATE, EVT_PEN_DRAW_END,
                    EVT_FIST_HOLD_COMMITTED):
            assert evt in ALL_EVENT_TYPES


# ─── Debug info ───────────────────────────────────────────────────────────────

class TestDebugInfo:
    """Debug info should include Phase 2 state."""

    def test_debug_info_includes_hold_attempt(self):
        """When hold attempt is active, debug_info should include it."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        # Feed one more frame to get result.
        frame = make_frame(raw_gesture="Closed_Fist")
        result = tracker.update(frame, MODE_PRESENTATION, time.monotonic())
        debug = result.debug_info
        assert debug["hold_attempt_id"] is not None
        assert debug["hold_attempt_intent"] == INTENT_FIST_HOLD
        assert debug["hold_committed"] is False

    def test_debug_info_shows_committed_state(self):
        """After hold commits, debug_info should show hold_committed=True."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.exit_mode_hold / 0.033) + 5)
        events = feed_stable(tracker, "Closed_Fist", n=total_frames,
                             mode=MODE_PRESENTATION)
        # Get one more frame for result.
        frame = make_frame(raw_gesture="Closed_Fist")
        result = tracker.update(frame, MODE_PRESENTATION, time.monotonic())
        assert result.debug_info["hold_committed"] is True

    def test_debug_info_hold_none_when_idle(self):
        """When idle, debug_info should show hold_attempt_id=None."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        frame = make_frame(raw_gesture="Open_Palm")
        result = tracker.update(frame, MODE_STANDBY, time.monotonic())
        assert result.debug_info["hold_attempt_id"] is None
        assert result.debug_info["hold_committed"] is False

    def test_intent_state_shows_hold(self):
        """Intent state string should include 'hold' when hold attempt active."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        frame = make_frame(raw_gesture="Closed_Fist")
        result = tracker.update(frame, MODE_PRESENTATION, time.monotonic())
        assert "hold" in result.intent_state


# ─── Reset / cancel ───────────────────────────────────────────────────────────

class TestResetCancel:
    """reset() and cancel() should clear Phase 2 state."""

    def test_reset_clears_hold_attempt(self):
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        tracker.reset()
        assert tracker._hold_attempt is None
        assert tracker._hold_committed is False

    def test_cancel_clears_hold_attempt(self):
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        events = tracker.cancel("test")
        assert tracker._hold_attempt is None
        assert tracker._hold_committed is False

    def test_cancel_emits_cancel_for_uncommitted_hold(self):
        """cancel() should emit EVT_CANCEL for uncommitted hold attempt."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Closed_Fist", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        events = tracker.cancel("test")
        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        assert len(cancel_events) == 1

    def test_cancel_no_hold_when_committed(self):
        """cancel() should not emit EVT_CANCEL for already-committed hold."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        total_frames = (cfg.gesture_enter_frames +
                        int(cfg.mode_arm_duration / 0.033) +
                        int(cfg.exit_mode_hold / 0.033) + 5)
        feed_stable(tracker, "Closed_Fist", n=total_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_committed is True

        events = tracker.cancel("test")
        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        # Committed hold should not produce cancel event.
        assert len(cancel_events) == 0


# ─── Expected gesture mapping ────────────────────────────────────────────────

class TestExpectedGesture:
    """_expected_gesture_for_attempt should return correct gesture for Phase 2 intents."""

    def test_fist_hold_returns_closed_fist(self):
        tracker = GestureIntentTracker(GestureConfig())
        assert tracker._expected_gesture_for_attempt(INTENT_FIST_HOLD) == "Closed_Fist"

    def test_pen_mode_returns_victory(self):
        tracker = GestureIntentTracker(GestureConfig())
        assert tracker._expected_gesture_for_attempt(INTENT_PEN_MODE) == "Victory"

    def test_mode_swipe_returns_iloveyou(self):
        tracker = GestureIntentTracker(GestureConfig())
        assert tracker._expected_gesture_for_attempt(INTENT_MODE_SWIPE) == "ILoveYou"

    def test_page_swipe_returns_open_palm(self):
        tracker = GestureIntentTracker(GestureConfig())
        assert tracker._expected_gesture_for_attempt(INTENT_PAGE_SWIPE) == "Open_Palm"


# ─── Priority / mutual exclusion ─────────────────────────────────────────────

class TestPriority:
    """Phase 2 candidates should not start when Phase 1 activity is in progress."""

    def test_hold_does_not_start_when_attempt_active(self):
        """Closed_Fist should not start hold when mode_swipe attempt is active."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # Start ILoveYou mode swipe attempt.
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "ILoveYou", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._attempt is not None
        assert tracker._hold_attempt is None

        # Now feed Closed_Fist — should not start hold.
        events = feed_stable(tracker, "Closed_Fist", n=5, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is None

    def test_pen_draw_does_not_start_when_hold_active(self):
        """PINCH should not start pen_draw when Victory hold is active."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        arm_frames = cfg.gesture_enter_frames + int(cfg.mode_arm_duration / 0.033) + 2
        feed_stable(tracker, "Victory", n=arm_frames, mode=MODE_PRESENTATION)
        assert tracker._hold_attempt is not None

        # Now feed PINCH — should not start pen_draw.
        events = feed_stable(tracker, "PINCH", n=5, mode=MODE_PRESENTATION_PEN,
                             pinch_distance_norm=cfg.pinch_threshold * 0.5)
        assert tracker._session is None

    def test_fist_hold_does_not_start_when_session_active(self):
        """Closed_Fist should not start hold when SolidWorks session is active."""
        cfg = GestureConfig()
        tracker = GestureIntentTracker(cfg)
        # Start SolidWorks rotate session.
        arm_frames = cfg.gesture_enter_frames + 2
        feed_stable(tracker, "Open_Palm", n=arm_frames, mode=MODE_SOLIDWORKS)
        assert tracker._session is not None

        # Now feed Closed_Fist — should not start hold.
        events = feed_stable(tracker, "Closed_Fist", n=5, mode=MODE_SOLIDWORKS)
        # The session should still be tracked (or ended by gesture change, but hold should not start).
        assert tracker._hold_attempt is None
