"""Tests for hands.gesture_intent_tracker 鈥?pure-logic tracker.

Phase 1 of the control-flow-driven refactor.

No camera, no pyautogui, no MediaPipe. Just the tracker fed synthetic
GestureFrame inputs and asserted on ControlEvent lists.

Covers the acceptance criteria from 搂7.1 of the refactor plan.
"""
from __future__ import annotations

import pytest

from hands.gesture_config import (
    GestureConfig,
    MODE_PRESENTATION,
    MODE_SOLIDWORKS,
    MODE_STANDBY,
)
from hands.gesture_intent_tracker import (
    ControlEvent,
    ControlSession,
    GestureAttempt,
    GestureFrame,
    GestureIntentTracker,
    GestureSource,
    TrackerResult,
    # Event type constants
    EVT_CANCEL,
    EVT_HAND_LOST_TIMEOUT,
    EVT_MODE_SWIPE_LEFT,
    EVT_MODE_SWIPE_RIGHT,
    EVT_PAGE_SWIPE_LEFT,
    EVT_PAGE_SWIPE_RIGHT,
    EVT_PAN_BEGIN,
    EVT_PAN_END,
    EVT_PAN_UPDATE,
    EVT_ROTATE_BEGIN,
    EVT_ROTATE_END,
    EVT_ROTATE_UPDATE,
    EVT_ZOOM_UPDATE,
    # Attempt phase constants
    AP_ARMED,
    AP_TRACKING,
    AP_COMMITTED,
    AP_RELEASED,
    AP_CANCELLED,
    # Session constants
    SESSION_IDLE,
    SESSION_ACTIVE,
    CTRL_ROTATE,
    CTRL_PAN,
    # Intent type constants
    INTENT_MODE_SWIPE,
    INTENT_PAGE_SWIPE,
)


# 鈹€鈹€ helpers 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def _cfg(**overrides) -> GestureConfig:
    """Build a test config with fast timings for unit tests."""
    defaults = dict(
        initial_mode=MODE_STANDBY,
        pause_on_start=False,
        hand_loss_timeout=1.0,
        gesture_enter_frames=4,
        gesture_enter_window_frames=5,
        gesture_keep_grace_frames=6,
        gesture_enter_confidence=0.70,
        gesture_keep_confidence=0.45,
        intent_lost_timeout=0.25,
        mode_arm_duration=0.20,
        mode_swipe_timeout=1.20,
        page_swipe_timeout=0.80,
        landmark_smoothing=0.45,
        motion_deadzone=0.015,
        max_motion_step=0.08,
        max_motion_velocity=1.5,
        min_motion_duration=0.12,
        direction_consistency_frames=3,
        swipe_threshold_x=0.18,
        swipe_threshold_y_limit=0.12,
        iloveyou_swipe_threshold_x=0.22,
        pinch_threshold=0.045,
        pinch_release_threshold=0.065,
        pinch_zoom_deadzone=0.01,
        solidworks_zoom_sensitivity=8.0,
        solidworks_min_zoom_step=1,
        invert_scroll=False,
    )
    defaults.update(overrides)
    return GestureConfig(**defaults)


def _frame(
    hand_present: bool = True,
    gesture: str | None = None,
    confidence: float = 0.9,
    source: GestureSource = GestureSource.RECOGNIZER,
    palm: tuple[float, float] | None = (0.5, 0.5),
    pinch: float | None = None,
    pinch_norm: float | None = None,
    hand_size: float | None = None,
    ts: float = 0.0,
) -> GestureFrame:
    return GestureFrame(
        hand_present=hand_present,
        raw_gesture=gesture,
        gesture_confidence=confidence,
        gesture_source=source,
        palm_xy=palm,
        index_tip_xy=None,
        pinch_distance=pinch,
        pinch_distance_norm=pinch_norm,
        hand_size=hand_size,
        timestamp=ts,
    )


def _feed_stable_gesture(
    tracker: GestureIntentTracker,
    gesture: str,
    mode: str = MODE_STANDBY,
    n_frames: int = 4,
    confidence: float = 0.9,
    palm: tuple[float, float] = (0.5, 0.5),
    start_ts: float = 0.0,
    dt: float = 0.033,
) -> list[TrackerResult]:
    """Feed n_frames of the same gesture to stabilise the candidate."""
    results = []
    for i in range(n_frames):
        f = _frame(gesture=gesture, confidence=confidence, palm=palm,
                   ts=start_ts + i * dt)
        r = tracker.update(f, mode, start_ts + i * dt)
        results.append(r)
    return results


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: hand_present=True, raw_gesture=None does not trigger hand_lost
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestHandPresentNoneGesture:
    """hand_present=True, raw_gesture=None should not start hand-loss timer
    and should not produce release_all or hand_lost_timeout."""

    def test_no_hand_lost_event(self):
        tracker = GestureIntentTracker(_cfg())
        # Feed frames: hand present but no classification.
        for i in range(30):
            f = _frame(hand_present=True, gesture=None, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
        # No hand_lost_timeout should fire.
        assert not any(e.type == EVT_HAND_LOST_TIMEOUT for e in r.events)

    def test_no_events_from_none_gesture(self):
        tracker = GestureIntentTracker(_cfg())
        for i in range(10):
            f = _frame(hand_present=True, gesture=None, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
            assert r.events == []


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: hand_present=False and hand_lost_timeout
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestHandLostTimeout:
    """hand_present=False for longer than hand_loss_timeout produces
    exactly one hand_lost_timeout event."""

    def test_short_absence_no_event(self):
        tracker = GestureIntentTracker(_cfg(hand_loss_timeout=1.0))
        # 0.5s of no hand 鈥?under timeout.
        for i in range(15):
            f = _frame(hand_present=False, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
        assert not any(e.type == EVT_HAND_LOST_TIMEOUT for e in r.events)

    def test_timeout_produces_one_event(self):
        tracker = GestureIntentTracker(_cfg(hand_loss_timeout=1.0))
        events = []
        # Feed 2 seconds of no hand.
        for i in range(61):
            f = _frame(hand_present=False, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
            events.extend(r.events)
        hand_lost_events = [e for e in events if e.type == EVT_HAND_LOST_TIMEOUT]
        assert len(hand_lost_events) == 1

    def test_repeated_frames_after_timeout_no_duplicate(self):
        tracker = GestureIntentTracker(_cfg(hand_loss_timeout=1.0))
        events = []
        for i in range(120):
            f = _frame(hand_present=False, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
            events.extend(r.events)
        hand_lost_events = [e for e in events if e.type == EVT_HAND_LOST_TIMEOUT]
        assert len(hand_lost_events) == 1

    def test_hand_reappearance_rearms(self):
        tracker = GestureIntentTracker(_cfg(hand_loss_timeout=0.5))
        events = []
        # No hand for 1s 鈫?fires once.
        for i in range(31):
            f = _frame(hand_present=False, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
            events.extend(r.events)
        assert len([e for e in events if e.type == EVT_HAND_LOST_TIMEOUT]) == 1
        # Hand reappears for 0.5s.
        for i in range(31, 46):
            f = _frame(hand_present=True, gesture="Open_Palm", ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
            events.extend(r.events)
        # No hand again for 1s 鈫?should fire again.
        for i in range(46, 77):
            f = _frame(hand_present=False, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
            events.extend(r.events)
        hand_lost_events = [e for e in events if e.type == EVT_HAND_LOST_TIMEOUT]
        assert len(hand_lost_events) == 2


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: candidate confirmation 鈥?4/5 frames required
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestCandidateConfirmation:
    """Single frame or fewer than 4/5 frames cannot enter armed."""

    def test_single_frame_no_attempt(self):
        tracker = GestureIntentTracker(_cfg())
        f = _frame(gesture="ILoveYou", confidence=0.9, ts=0.0)
        r = tracker.update(f, MODE_STANDBY, 0.0)
        assert r.active_attempt is None
        assert r.events == []

    def test_three_frames_no_attempt(self):
        tracker = GestureIntentTracker(_cfg())
        for i in range(3):
            f = _frame(gesture="ILoveYou", confidence=0.9, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
        assert r.active_attempt is None

    def test_four_frames_stabilises(self):
        tracker = GestureIntentTracker(_cfg())
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
        assert r.stable_gesture == "ILoveYou"

    def test_low_confidence_not_counted(self):
        tracker = GestureIntentTracker(_cfg(gesture_enter_confidence=0.70))
        for i in range(5):
            f = _frame(gesture="ILoveYou", confidence=0.50, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
        assert r.stable_gesture is None

    def test_rule_fallback_no_confidence_gate(self):
        """Rule fallback results bypass confidence but must still meet frame count."""
        tracker = GestureIntentTracker(_cfg(gesture_enter_confidence=0.99))
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.0,
                       source=GestureSource.RULE_FALLBACK, ts=i * 0.033)
            r = tracker.update(f, MODE_STANDBY, i * 0.033)
        assert r.stable_gesture == "ILoveYou"


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: mode switch attempt 鈥?single commit
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestModeSwitchAttempt:
    """ILoveYou stabilised 鈫?armed 鈫?tracking 鈫?committed 鈫?released.
    One attempt = one commit."""

    def _arm_iloveyou(self, tracker, mode=MODE_STANDBY, start_ts=0.0):
        """Feed 4 frames ILoveYou + arm_duration to get armed."""
        dt = 0.033
        # 4 frames to stabilise.
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=start_ts + i * dt)
            tracker.update(f, mode, start_ts + i * dt)
        # Wait for arm_duration.
        arm_end = start_ts + 4 * dt + 0.25  # > mode_arm_duration=0.20
        f = _frame(gesture="ILoveYou", confidence=0.9,
                   palm=(0.5, 0.5), ts=arm_end)
        r = tracker.update(f, mode, arm_end)
        return r, arm_end

    def test_armed_after_stable_and_arm_duration(self):
        tracker = GestureIntentTracker(_cfg())
        r, _ = self._arm_iloveyou(tracker)
        assert r.active_attempt is not None
        assert r.active_attempt.phase in (AP_ARMED, AP_TRACKING)

    def test_right_swipe_commits_once(self):
        tracker = GestureIntentTracker(_cfg())
        _, arm_ts = self._arm_iloveyou(tracker)
        # Swipe right: move palm x from 0.5 to 0.8 over several frames.
        dt = 0.033
        ts = arm_ts + dt
        events = []
        for i in range(8):
            x = 0.5 + (i + 1) * 0.06  # 0.56, 0.62, 0.68, 0.74, 0.80, 0.86, ...
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        mode_swipe_events = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe_events) == 1
        assert mode_swipe_events[0].type == EVT_MODE_SWIPE_RIGHT

    def test_left_swipe_commits_once(self):
        tracker = GestureIntentTracker(_cfg())
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        for i in range(8):
            x = 0.5 - (i + 1) * 0.06
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        mode_swipe_events = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe_events) == 1
        assert mode_swipe_events[0].type == EVT_MODE_SWIPE_LEFT

    def test_no_double_commit(self):
        tracker = GestureIntentTracker(_cfg())
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        # First swipe right.
        for i in range(8):
            x = 0.5 + (i + 1) * 0.06
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        # Continue moving right.
        for i in range(8, 14):
            x = 0.5 + (i + 1) * 0.06
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        mode_swipe_events = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe_events) == 1

    def test_vertical_too_large_cancels(self):
        tracker = GestureIntentTracker(_cfg())
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        # Move with large vertical component.
        for i in range(10):
            x = 0.5 + (i + 1) * 0.06
            y = 0.5 + (i + 1) * 0.04  # dy > swipe_threshold_y_limit
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, y), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        mode_swipe_events = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe_events) == 0

    def test_timeout_cancels(self):
        tracker = GestureIntentTracker(_cfg(mode_swipe_timeout=0.30))
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        # Small movement 鈥?not enough to commit.
        for i in range(15):
            x = 0.5 + i * 0.005
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        assert len(cancel_events) >= 1

    def test_committed_not_recommitted_before_release(self):
        """After commit, attempt stays committed until released/cancelled."""
        tracker = GestureIntentTracker(_cfg())
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        # Swipe right enough to commit.
        for i in range(8):
            x = 0.5 + (i + 1) * 0.06
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        assert r.active_attempt is not None
        assert r.active_attempt.committed is True

    def test_swipe_commits_within_default_timeout(self):
        """ILoveYou swipe commits within the new default 1.20s timeout.

        Real-record analysis showed that a typical ILoveYou swipe takes
        ~0.9s from attempt start to commit.  The old 0.80s timeout was
        too tight and caused premature cancellation.
        """
        tracker = GestureIntentTracker(_cfg())
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.03
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        mode_swipe = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe) >= 1, "swipe should commit within default 1.20s timeout"

    def test_swipe_commits_within_new_1_2s_timeout(self):
        """ILoveYou swipe that takes ~0.9s from attempt start commits with 1.20s timeout.

        Real-record analysis showed att_3 was cancelled at ~0.9s with the old
        0.80s timeout.  With 1.20s the same swipe would commit successfully.
        """
        tracker = GestureIntentTracker(_cfg(mode_swipe_timeout=1.20))
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        # Hold position for 20 frames (~0.66s).  This pushes total time
        # from attempt start to ~0.69s before motion starts.
        for i in range(20):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        # Now move: 0.05 per frame, 8 frames (~0.26s).
        # Total from attempt start ~0.69s + 0.26s = ~0.95s.
        # With 0.80s timeout this would be cancelled; with 1.20s it commits.
        move_ts = ts + 20 * dt
        for i in range(8):
            x = 0.5 + (i + 1) * 0.05
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=move_ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, move_ts + i * dt)
            events.extend(r.events)
        mode_swipe = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe) >= 1, "swipe at ~0.95s should commit with 1.20s timeout"

    def test_swipe_cancelled_with_old_0_8s_timeout(self):
        """Same late swipe cancelled with old 0.80s timeout - confirms the fix.

        The swipe commits on move frame 5 (elapsed ~0.79s) with 1.20s timeout,
        but with 0.80s the timeout fires before displacement crosses 0.22.
        """
        tracker = GestureIntentTracker(_cfg(mode_swipe_timeout=0.80))
        _, arm_ts = self._arm_iloveyou(tracker)
        dt = 0.033
        ts = arm_ts + dt
        events = []
        for i in range(20):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts + i * dt)
            events.extend(r.events)
        move_ts = ts + 20 * dt
        for i in range(8):
            x = 0.5 + (i + 1) * 0.05
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=move_ts + i * dt)
            r = tracker.update(f, MODE_STANDBY, move_ts + i * dt)
            events.extend(r.events)
        cancel_events = [e for e in events if e.type == EVT_CANCEL and e.reason == "timeout"]
        assert len(cancel_events) >= 1, "swipe >0.80s should be cancelled with old timeout"


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: page turn attempt
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestPageTurnAttempt:
    """Open_Palm in presentation mode stabilises 鈫?attempt 鈫?commit."""

    def test_right_swipe_one_commit(self):
        tracker = GestureIntentTracker(_cfg())
        # Stabilise Open_Palm.
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_PRESENTATION, i * dt)
        # Swipe right.
        ts = 4 * dt + 0.25  # wait for arm_duration equivalent
        # Re-stabilise at the new timestamp to create attempt.
        f = _frame(gesture="Open_Palm", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_PRESENTATION, ts)
        ts += dt
        events = []
        for i in range(8):
            x = 0.5 + (i + 1) * 0.06
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_PRESENTATION, ts + i * dt)
            events.extend(r.events)
        page_events = [e for e in events if e.type in (EVT_PAGE_SWIPE_LEFT, EVT_PAGE_SWIPE_RIGHT)]
        assert len(page_events) == 1
        assert page_events[0].type == EVT_PAGE_SWIPE_RIGHT

    def test_left_swipe_one_commit(self):
        tracker = GestureIntentTracker(_cfg())
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_PRESENTATION, i * dt)
        ts = 4 * dt + 0.25
        f = _frame(gesture="Open_Palm", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_PRESENTATION, ts)
        ts += dt
        events = []
        for i in range(8):
            x = 0.5 - (i + 1) * 0.06
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_PRESENTATION, ts + i * dt)
            events.extend(r.events)
        page_events = [e for e in events if e.type in (EVT_PAGE_SWIPE_LEFT, EVT_PAGE_SWIPE_RIGHT)]
        assert len(page_events) == 1
        assert page_events[0].type == EVT_PAGE_SWIPE_LEFT


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: SolidWorks rotate session
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestRotateSession:
    """Open_Palm in SolidWorks 鈫?rotate_begin 鈫?rotate_update 鈫?rotate_end."""

    def test_begin_and_update(self):
        tracker = GestureIntentTracker(_cfg(min_motion_duration=0.12))
        # Stabilise Open_Palm in SolidWorks.
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        # Motion to trigger begin (need > min_motion_duration = 0.12s).
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            y = 0.5 + (i + 1) * 0.03
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, y), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        begin_events = [e for e in events if e.type == EVT_ROTATE_BEGIN]
        update_events = [e for e in events if e.type == EVT_ROTATE_UPDATE]
        assert len(begin_events) >= 1
        assert len(update_events) >= 1

    def test_no_repeated_begin(self):
        """rotate_begin should only fire once per session."""
        tracker = GestureIntentTracker(_cfg(min_motion_duration=0.12))
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(30):
            x = 0.5 + (i + 1) * 0.02
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        begin_events = [e for e in events if e.type == EVT_ROTATE_BEGIN]
        assert len(begin_events) == 1

    def test_gesture_change_does_not_immediately_end(self):
        """Brief classification jitter should not end the session."""
        tracker = GestureIntentTracker(_cfg(
            min_motion_duration=0.12,
            intent_lost_timeout=0.25,
        ))
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        # Start motion.
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        # Brief classification failure (3 frames = ~0.1s, under intent_lost_timeout).
        ts2 = ts + 10 * dt
        for i in range(3):
            f = _frame(hand_present=True, gesture=None,
                       palm=(0.9, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts2 + i * dt)
            events.extend(r.events)
        # No end event should have fired yet.
        end_events = [e for e in events if e.type == EVT_ROTATE_END]
        assert len(end_events) == 0

    def test_intent_lost_timeout_ends_session(self):
        """Classification failure beyond intent_lost_timeout ends the session."""
        tracker = GestureIntentTracker(_cfg(
            min_motion_duration=0.12,
            intent_lost_timeout=0.10,
        ))
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        dt = 0.033
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        # Sustained classification failure > intent_lost_timeout.
        ts2 = ts + 10 * dt
        for i in range(8):
            f = _frame(hand_present=True, gesture=None,
                       palm=(0.9, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts2 + i * dt)
            events.extend(r.events)
        end_events = [e for e in events if e.type == EVT_ROTATE_END]
        assert len(end_events) == 1


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: SolidWorks pan session
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestPanSession:
    """Victory in SolidWorks 鈫?pan_begin 鈫?pan_update 鈫?pan_end."""

    def test_begin_and_update(self):
        tracker = GestureIntentTracker(_cfg(min_motion_duration=0.12))
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Victory", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Victory", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        begin_events = [e for e in events if e.type == EVT_PAN_BEGIN]
        update_events = [e for e in events if e.type == EVT_PAN_UPDATE]
        assert len(begin_events) >= 1
        assert len(update_events) >= 1

    def test_active_session_blocks_rotate(self):
        """Active pan session should not start a rotate candidate."""
        tracker = GestureIntentTracker(_cfg(min_motion_duration=0.12))
        dt = 0.033
        # Start pan.
        for i in range(4):
            f = _frame(gesture="Victory", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Victory", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        # Now switch to Open_Palm 鈥?should not start rotate while pan active.
        ts2 = ts + 10 * dt
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5 + (i + 1) * 0.03), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts2 + i * dt)
            events.extend(r.events)
        rotate_begin = [e for e in events if e.type == EVT_ROTATE_BEGIN]
        # No rotate_begin while pan is still active.
        assert len(rotate_begin) == 0


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: SolidWorks zoom
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestZoomAttempt:
    """Pinch distance-based zoom using pinch_distance_norm (scale-invariant)."""

    def test_zoom_update_on_pinch(self):
        tracker = GestureIntentTracker(_cfg(pinch_zoom_deadzone=0.002))
        # Feed a frame with pinch_distance_norm below threshold.
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.040, ts=0.0)
        r = tracker.update(f0, MODE_SOLIDWORKS, 0.0)
        # Zoom should be active.
        # Feed decreasing pinch_distance_norm.
        events = []
        for i in range(1, 6):
            pd = 0.040 - i * 0.005
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), pinch_norm=pd, ts=i * 0.033)
            r = tracker.update(f, MODE_SOLIDWORKS, i * 0.033)
            events.extend(r.events)
        zoom_events = [e for e in events if e.type == EVT_ZOOM_UPDATE]
        assert len(zoom_events) >= 1

    def test_zoom_works_with_gesture_change(self):
        """Zoom should still work when classification changes."""
        tracker = GestureIntentTracker(_cfg(pinch_zoom_deadzone=0.002))
        # Start zoom with Open_Palm.
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.040, ts=0.0)
        tracker.update(f0, MODE_SOLIDWORKS, 0.0)
        # Change gesture - zoom should continue based on pinch_distance_norm.
        events = []
        for i in range(1, 6):
            pd = 0.040 - i * 0.005
            f = _frame(gesture="Victory", confidence=0.9,
                       palm=(0.5, 0.5), pinch_norm=pd, ts=i * 0.033)
            r = tracker.update(f, MODE_SOLIDWORKS, i * 0.033)
            events.extend(r.events)
        zoom_events = [e for e in events if e.type == EVT_ZOOM_UPDATE]
        assert len(zoom_events) >= 1

    def test_zoom_release_at_threshold(self):
        tracker = GestureIntentTracker(_cfg())
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.040, ts=0.0)
        tracker.update(f0, MODE_SOLIDWORKS, 0.0)
        # Increase pinch_distance_norm beyond release threshold.
        f1 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.080, ts=0.033)
        r = tracker.update(f1, MODE_SOLIDWORKS, 0.033)
        # Zoom should be inactive.
        assert r.debug_info["zoom_active"] is False

    def test_zoom_blocks_rotate_and_pan(self):
        """Active zoom should prevent starting rotate or pan."""
        tracker = GestureIntentTracker(_cfg())
        # Start zoom.
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.040, ts=0.0)
        tracker.update(f0, MODE_SOLIDWORKS, 0.0)
        # Stabilise Open_Palm (would normally start rotate).
        events = []
        for i in range(1, 10):
            x = 0.5 + i * 0.02
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), pinch_norm=0.035, ts=i * 0.033)
            r = tracker.update(f, MODE_SOLIDWORKS, i * 0.033)
            events.extend(r.events)
        rotate_begin = [e for e in events if e.type == EVT_ROTATE_BEGIN]
        assert len(rotate_begin) == 0

    def test_zoom_no_norm_no_zoom(self):
        """Only pinch_distance without pinch_distance_norm must not trigger zoom."""
        tracker = GestureIntentTracker(_cfg())
        # Provide pinch_distance but NOT pinch_distance_norm.
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch=0.040, ts=0.0)
        r = tracker.update(f0, MODE_SOLIDWORKS, 0.0)
        assert r.debug_info["zoom_active"] is False
        # Feed more frames - still no zoom.
        events = []
        for i in range(1, 6):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), pinch=0.030, ts=i * 0.033)
            r = tracker.update(f, MODE_SOLIDWORKS, i * 0.033)
            events.extend(r.events)
        zoom_events = [e for e in events if e.type == EVT_ZOOM_UPDATE]
        assert len(zoom_events) == 0

    def test_zoom_norm_not_below_threshold_no_zoom(self):
        """pinch_distance_norm not below pinch_threshold must not trigger zoom."""
        tracker = GestureIntentTracker(_cfg(pinch_threshold=0.045))
        # pinch_distance_norm is above threshold - no zoom.
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.050, pinch=0.040, ts=0.0)
        r = tracker.update(f0, MODE_SOLIDWORKS, 0.0)
        assert r.debug_info["zoom_active"] is False
        # Feed more frames with changing pinch_distance but stable norm.
        events = []
        for i in range(1, 6):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), pinch_norm=0.048,
                       pinch=0.040 - i * 0.005, ts=i * 0.033)
            r = tracker.update(f, MODE_SOLIDWORKS, i * 0.033)
            events.extend(r.events)
        zoom_events = [e for e in events if e.type == EVT_ZOOM_UPDATE]
        assert len(zoom_events) == 0

    def test_zoom_norm_continues_after_gesture_change(self):
        """pinch_distance_norm below threshold enters zoom; gesture change still zoom_update."""
        tracker = GestureIntentTracker(_cfg(pinch_zoom_deadzone=0.002))
        # Stabilise a neutral gesture first (Pointing_Up does not trigger SW actions).
        _feed_stable_gesture(tracker, "Pointing_Up", mode=MODE_SOLIDWORKS)
        # Now feed a frame with pinch_distance_norm below threshold to start zoom.
        f0 = _frame(gesture="Pointing_Up", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.040, ts=0.132)
        tracker.update(f0, MODE_SOLIDWORKS, 0.132)
        assert tracker._zoom_active
        # Change to Victory - zoom continues.
        events = []
        for i in range(1, 6):
            pd = 0.040 - i * 0.005
            f = _frame(gesture="Victory", confidence=0.9,
                       palm=(0.5, 0.5), pinch_norm=pd, ts=0.132 + i * 0.033)
            r = tracker.update(f, MODE_SOLIDWORKS, 0.132 + i * 0.033)
            events.extend(r.events)
        zoom_events = [e for e in events if e.type == EVT_ZOOM_UPDATE]
        assert len(zoom_events) >= 1

    def test_zoom_norm_release_at_threshold(self):
        """pinch_distance_norm exceeding pinch_release_threshold releases zoom."""
        tracker = GestureIntentTracker(_cfg())
        # Stabilise a neutral gesture first (Pointing_Up does not trigger SW actions).
        _feed_stable_gesture(tracker, "Pointing_Up", mode=MODE_SOLIDWORKS)
        # Start zoom with pinch_distance_norm below threshold.
        f0 = _frame(gesture="Pointing_Up", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.040, ts=0.132)
        tracker.update(f0, MODE_SOLIDWORKS, 0.132)
        assert tracker._zoom_active
        # Increase norm beyond release threshold.
        f1 = _frame(gesture="Pointing_Up", confidence=0.9,
                    palm=(0.5, 0.5), pinch_norm=0.080, ts=0.165)
        r = tracker.update(f1, MODE_SOLIDWORKS, 0.165)
        assert not tracker._zoom_active
        assert r.debug_info["zoom_active"] is False

class TestResetCancel:
    """reset() and cancel() should cleanly clear state."""

    def test_cancel_emits_end_events(self):
        tracker = GestureIntentTracker(_cfg(min_motion_duration=0.12))
        dt = 0.033
        # Start a rotate session.
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
        # Cancel.
        events = tracker.cancel("manual_cancel")
        end_events = [e for e in events if e.type == EVT_ROTATE_END]
        assert len(end_events) == 1

    def test_reset_clears_state(self):
        tracker = GestureIntentTracker(_cfg())
        # Build some state.
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9, ts=i * 0.033)
            tracker.update(f, MODE_STANDBY, i * 0.033)
        tracker.reset()
        assert tracker._attempt is None
        assert tracker._session is None
        assert tracker._zoom_active is False
        assert tracker._stable_gesture is None

    def test_cancel_no_active_state_returns_empty(self):
        tracker = GestureIntentTracker(_cfg())
        events = tracker.cancel()
        assert events == []


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: debug info
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestDebugInfo:
    """TrackerResult.debug_info should contain key diagnostic fields."""

    def test_debug_fields_present(self):
        tracker = GestureIntentTracker(_cfg())
        f = _frame(gesture="Open_Palm", confidence=0.9, ts=0.0)
        r = tracker.update(f, MODE_STANDBY, 0.0)
        d = r.debug_info
        assert "tracker_state" in d
        assert "stable_gesture" in d
        assert "active_attempt_id" in d
        assert "active_session_id" in d
        assert "zoom_active" in d
        assert "bad_frames" in d
        assert "hand_lost_duration" in d
        assert "smoothed_palm" in d

    def test_debug_shows_attempt_id(self):
        tracker = GestureIntentTracker(_cfg())
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9, ts=i * 0.033)
            tracker.update(f, MODE_STANDBY, i * 0.033)
        # Feed one more to arm.
        ts = 4 * 0.033 + 0.25
        f = _frame(gesture="ILoveYou", confidence=0.9, ts=ts)
        r = tracker.update(f, MODE_STANDBY, ts)
        if r.active_attempt:
            assert r.debug_info["active_attempt_id"] == r.active_attempt.attempt_id


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: landmark smoothing
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestLandmarkSmoothing:
    """Palm position should be smoothed via low-pass filter."""

    def test_smoothing_applied(self):
        tracker = GestureIntentTracker(_cfg(landmark_smoothing=0.45))
        # First frame sets position.
        f0 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.5, 0.5), ts=0.0)
        r0 = tracker.update(f0, MODE_STANDBY, 0.0)
        assert r0.debug_info["smoothed_palm"] == (0.5, 0.5)
        # Second frame jumps to (0.8, 0.8) 鈥?should be smoothed.
        f1 = _frame(gesture="Open_Palm", confidence=0.9,
                    palm=(0.8, 0.8), ts=0.033)
        r1 = tracker.update(f1, MODE_STANDBY, 0.033)
        sx, sy = r1.debug_info["smoothed_palm"]
        # Should be between 0.5 and 0.8, not equal to 0.8.
        assert 0.5 < sx < 0.8
        assert 0.5 < sy < 0.8


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?# Test: mode swipe with classification change after armed
# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?
class TestClassificationChangeAfterArmed:
    """After armed, ILoveYou classification is not required to complete swipe."""

    def test_swipe_completes_with_different_gesture(self):
        tracker = GestureIntentTracker(_cfg())
        # Stabilise ILoveYou.
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_STANDBY, i * dt)
        # Arm.
        ts = 4 * dt + 0.25
        f = _frame(gesture="ILoveYou", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_STANDBY, ts)
        # Swipe right with classification changing to None (hand still present).
        ts2 = ts + dt
        events = []
        for i in range(8):
            x = 0.5 + (i + 1) * 0.06
            f = _frame(hand_present=True, gesture=None,
                       palm=(x, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts2 + i * dt)
            events.extend(r.events)
        mode_swipe_events = [e for e in events if e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT)]
        assert len(mode_swipe_events) == 1
        assert mode_swipe_events[0].type == EVT_MODE_SWIPE_RIGHT


# ═══════════════════════════════════════════════════════════════════════════
# Test: gesture_keep_grace_frames enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestGestureKeepGraceFrames:
    """gesture_keep_grace_frames must end sessions/attempts when exceeded."""

    def test_rotate_survives_6_bad_frames_but_not_7(self):
        """6 consecutive bad frames should not end rotate; 7 should."""
        cfg = _cfg(
            min_motion_duration=0.12,
            intent_lost_timeout=10.0,
            gesture_keep_grace_frames=6,
        )
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_ROTATE_BEGIN for e in events)

        # 6 bad frames — should survive.
        ts2 = ts + 10 * dt
        for i in range(6):
            f = _frame(hand_present=True, gesture=None,
                       palm=(0.9, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts2 + i * dt)
            events.extend(r.events)
        assert not any(e.type == EVT_ROTATE_END for e in events)

        # 7th bad frame — should end.
        ts3 = ts2 + 6 * dt
        f = _frame(hand_present=True, gesture=None,
                   palm=(0.9, 0.5), ts=ts3)
        r = tracker.update(f, MODE_SOLIDWORKS, ts3)
        events.extend(r.events)
        assert any(e.type == EVT_ROTATE_END for e in events)

    def test_grace_exceeds_before_timeout(self):
        """Frame-count gate triggers before time gate."""
        cfg = _cfg(
            min_motion_duration=0.12,
            intent_lost_timeout=1.0,
            gesture_keep_grace_frames=3,
        )
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.04
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_ROTATE_BEGIN for e in events)

        # 4 bad frames (exceeds grace=3, within timeout=1.0s).
        ts2 = ts + 10 * dt
        for i in range(4):
            f = _frame(hand_present=True, gesture="Victory",
                       palm=(0.9, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts2 + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_ROTATE_END for e in events)

    def test_attempt_cancelled_by_grace(self):
        """Mode swipe attempt should cancel when grace exceeded in armed phase."""
        cfg = _cfg(
            gesture_keep_grace_frames=3,
            intent_lost_timeout=10.0,
        )
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_STANDBY, i * dt)
        ts = 4 * dt + 0.25
        f = _frame(gesture="ILoveYou", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_STANDBY, ts)
        # In armed phase, feed wrong gesture without palm movement
        # so attempt stays in armed (no trajectory motion to trigger tracking).
        ts2 = ts + dt
        events = []
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts2 + i * dt)
            events.extend(r.events)
        cancel_events = [e for e in events if e.type == EVT_CANCEL]
        assert len(cancel_events) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# Test: direction_consistency_frames enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestDirectionConsistencyFrames:
    """direction_consistency_frames must require N consistent direction samples."""

    def test_single_direction_sample_not_enough(self):
        """With direction_consistency_frames=3, 2 samples should not commit."""
        cfg = _cfg(direction_consistency_frames=3)
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_STANDBY, i * dt)
        ts = 4 * dt + 0.25
        f = _frame(gesture="ILoveYou", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_STANDBY, ts)
        # Two frames with rightward motion: 2 direction samples, need 3.
        ts2 = ts + dt
        events = []
        f1 = _frame(gesture="ILoveYou", confidence=0.9,
                    palm=(0.60, 0.5), ts=ts2)
        r = tracker.update(f1, MODE_STANDBY, ts2)
        events.extend(r.events)
        f2 = _frame(gesture="ILoveYou", confidence=0.9,
                    palm=(0.85, 0.5), ts=ts2 + dt)
        r = tracker.update(f2, MODE_STANDBY, ts2 + dt)
        events.extend(r.events)
        assert not any(e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT) for e in events)

    def test_three_consistent_directions_commit(self):
        """3 consistent direction samples should allow commit."""
        cfg = _cfg(direction_consistency_frames=3)
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_STANDBY, i * dt)
        ts = 4 * dt + 0.25
        f = _frame(gesture="ILoveYou", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_STANDBY, ts)
        ts2 = ts + dt
        events = []
        for i in range(5):
            x = 0.5 + (i + 1) * 0.08
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts2 + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_MODE_SWIPE_RIGHT for e in events)

    def test_mixed_directions_no_commit(self):
        """Alternating left-right directions should not commit."""
        cfg = _cfg(direction_consistency_frames=3)
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_STANDBY, i * dt)
        ts = 4 * dt + 0.25
        f = _frame(gesture="ILoveYou", confidence=0.9,
                   palm=(0.5, 0.5), ts=ts)
        tracker.update(f, MODE_STANDBY, ts)
        # Alternate: right, left, right, left, right.
        ts2 = ts + dt
        events = []
        positions = [0.58, 0.52, 0.60, 0.54, 0.62]
        for i, x in enumerate(positions):
            f = _frame(gesture="ILoveYou", confidence=0.9,
                       palm=(x, 0.5), ts=ts2 + i * dt)
            r = tracker.update(f, MODE_STANDBY, ts2 + i * dt)
            events.extend(r.events)
        assert not any(e.type in (EVT_MODE_SWIPE_LEFT, EVT_MODE_SWIPE_RIGHT) for e in events)


# ═══════════════════════════════════════════════════════════════════════════
# Test: max_motion_velocity enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestMaxMotionVelocity:
    """max_motion_velocity must limit per-frame displacement based on speed."""

    def test_low_velocity_limits_large_move(self):
        """Very low max_motion_velocity should clamp large update events."""
        cfg = _cfg(
            min_motion_duration=0.12,
            max_motion_velocity=0.5,
            max_motion_step=1.0,
            motion_deadzone=0.001,
            landmark_smoothing=1.0,
        )
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.01
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_ROTATE_BEGIN for e in events)

        # Large jump exceeding velocity limit.
        ts2 = ts + 10 * dt
        f = _frame(gesture="Open_Palm", confidence=0.9,
                   palm=(0.9, 0.5), ts=ts2)
        r = tracker.update(f, MODE_SOLIDWORKS, ts2)
        events.extend(r.events)
        update_events = [e for e in events if e.type == EVT_ROTATE_UPDATE]
        if update_events:
            last_update = update_events[-1]
            assert abs(last_update.dx) < 0.1, f"dx={last_update.dx} not clamped"

    def test_high_velocity_no_clamp(self):
        """High max_motion_velocity should not interfere with normal motion."""
        cfg = _cfg(
            min_motion_duration=0.12,
            max_motion_velocity=100.0,
            max_motion_step=1.0,
            motion_deadzone=0.001,
            landmark_smoothing=1.0,
        )
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.01
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_ROTATE_BEGIN for e in events)

        # Normal small step.
        ts2 = ts + 10 * dt
        x_before = 0.5 + 10 * 0.01
        f = _frame(gesture="Open_Palm", confidence=0.9,
                   palm=(x_before + 0.02, 0.5), ts=ts2)
        r = tracker.update(f, MODE_SOLIDWORKS, ts2)
        events.extend(r.events)
        update_events = [e for e in events if e.type == EVT_ROTATE_UPDATE]
        assert any(abs(e.dx) > 0 for e in update_events)

    def test_max_motion_step_still_enforced(self):
        """max_motion_step should still cap displacement regardless of velocity."""
        cfg = _cfg(
            min_motion_duration=0.12,
            max_motion_velocity=100.0,
            max_motion_step=0.02,
            motion_deadzone=0.001,
            landmark_smoothing=1.0,
        )
        tracker = GestureIntentTracker(cfg)
        dt = 0.033
        for i in range(4):
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(0.5, 0.5), ts=i * dt)
            tracker.update(f, MODE_SOLIDWORKS, i * dt)
        ts = 4 * dt
        events = []
        for i in range(10):
            x = 0.5 + (i + 1) * 0.01
            f = _frame(gesture="Open_Palm", confidence=0.9,
                       palm=(x, 0.5), ts=ts + i * dt)
            r = tracker.update(f, MODE_SOLIDWORKS, ts + i * dt)
            events.extend(r.events)
        assert any(e.type == EVT_ROTATE_BEGIN for e in events)

        # Large jump exceeding max_motion_step.
        ts2 = ts + 10 * dt
        f = _frame(gesture="Open_Palm", confidence=0.9,
                   palm=(0.9, 0.5), ts=ts2)
        r = tracker.update(f, MODE_SOLIDWORKS, ts2)
        events.extend(r.events)
        update_events = [e for e in events if e.type == EVT_ROTATE_UPDATE]
        if update_events:
            last_update = update_events[-1]
            assert abs(last_update.dx) <= 0.02 + 0.001, f"dx={last_update.dx} exceeds max_motion_step"
