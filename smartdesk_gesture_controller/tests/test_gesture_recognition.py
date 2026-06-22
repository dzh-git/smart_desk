"""Tests for hands.gesture_recognition — pure classification functions.

These test ``classify_gesture``, ``is_hand_open``, ``is_fist``,
``finger_bent_status``, ``palm_center``, and ``pinch_distance`` by constructing
synthetic landmark lists. No MediaPipe model, no camera.

Phase 8 adds tests for:
    * ``normalize_gesture_name`` — official ↔ legacy name mapping.
    * ``_FrameResult`` + ``to_hand_input`` priority logic (GestureRecognizer
      primary, rule fallback, Closed_Fist safety, low-confidence → None).
    * ``gesture_recognizer_model_exists`` helper.
    * PINCH still computed from landmarks (not from GestureRecognizer).
"""
from __future__ import annotations

import math
from typing import Optional, Tuple
from unittest.mock import patch

import pytest

from hands.gesture_recognition import (
    CANONICAL_GESTURE_NAMES,
    HandRecognizer,
    _FrameResult,
    classify_gesture,
    finger_bent_status,
    gesture_recognizer_model_exists,
    is_fist,
    is_hand_open,
    landmarks_to_hand_input,
    normalize_gesture_name,
    palm_center,
    pinch_distance,
)
from hands.gesture_state import Gesture, HandInput


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_landmarks(
    *,
    thumb_tip_y: int = 100,
    thumb_ip_y: int = 120,
    index_tip_y: int = 60,
    index_mcp_y: int = 150,
    middle_tip_y: int = 60,
    middle_mcp_y: int = 150,
    ring_tip_y: int = 60,
    ring_mcp_y: int = 150,
    pinky_tip_y: int = 60,
    pinky_mcp_y: int = 150,
    wrist_x: int = 100,
    wrist_y: int = 300,
    middle_mcp_x: int = 200,
    middle_mcp_y_actual: int = 150,
    thumb_tip_x: int = 150,
    index_tip_x: int = 200,
) -> list:
    """Build a 21-element ``[id, x_px, y_px]`` landmark list.

    Default values represent a hand where all fingers are extended (open palm),
    with y increasing downward (camera convention). Values can be overridden
    to construct specific gestures.
    """
    lm = []
    for i in range(21):
        lm.append([i, 0, 0])  # placeholder
    # Set key points
    lm[0][1], lm[0][2] = wrist_x, wrist_y          # wrist
    lm[2][2] = thumb_ip_y                            # thumb IP
    lm[4][1], lm[4][2] = thumb_tip_x, thumb_tip_y  # thumb tip
    lm[5][2] = index_mcp_y                            # index MCP
    lm[8][1], lm[8][2] = index_tip_x, index_tip_y  # index tip
    lm[9][1], lm[9][2] = middle_mcp_x, middle_mcp_y_actual  # middle MCP
    lm[12][2] = middle_tip_y                          # middle tip
    lm[13][2] = ring_mcp_y                            # ring MCP
    lm[16][2] = ring_tip_y                            # ring tip
    lm[17][2] = pinky_mcp_y                           # pinky MCP
    lm[20][2] = pinky_tip_y                           # pinky tip
    return lm


def _open_palm() -> list:
    return _make_landmarks(
        thumb_tip_y=80, thumb_ip_y=120,  # thumb tip above IP → straight
        index_tip_y=60, index_mcp_y=150,   # tips above MCPs → straight
        middle_tip_y=60, middle_mcp_y=150,
        ring_tip_y=60, ring_mcp_y=150,
        pinky_tip_y=60, pinky_mcp_y=150,
    )


def _closed_fist() -> list:
    return _make_landmarks(
        thumb_tip_y=80, thumb_ip_y=120,
        index_tip_y=200, index_mcp_y=150,  # tips below MCPs → bent
        middle_tip_y=200, middle_mcp_y=150,
        ring_tip_y=200, ring_mcp_y=150,
        pinky_tip_y=200, pinky_mcp_y=150,
    )


def _single_finger() -> list:
    return _make_landmarks(
        thumb_tip_y=80, thumb_ip_y=120,
        index_tip_y=60, index_mcp_y=150,   # index straight
        middle_tip_y=200, middle_mcp_y=150, # middle bent
        ring_tip_y=200, ring_mcp_y=150,    # ring bent
        pinky_tip_y=200, pinky_mcp_y=150,   # pinky bent
    )


def _two_finger() -> list:
    return _make_landmarks(
        thumb_tip_y=80, thumb_ip_y=120,
        index_tip_y=60, index_mcp_y=150,   # index straight
        middle_tip_y=60, middle_mcp_y=150,  # middle straight
        ring_tip_y=200, ring_mcp_y=150,    # ring bent
        pinky_tip_y=200, pinky_mcp_y=150,   # pinky bent
    )


# ── finger_bent_status ────────────────────────────────────────────────────────

class TestFingerBentStatus:
    def test_all_straight(self) -> None:
        bent = finger_bent_status(_open_palm())
        assert bent == [False, False, False, False]

    def test_all_bent(self) -> None:
        bent = finger_bent_status(_closed_fist())
        assert bent == [True, True, True, True]

    def test_single_finger(self) -> None:
        bent = finger_bent_status(_single_finger())
        assert bent == [False, True, True, True]

    def test_two_finger(self) -> None:
        bent = finger_bent_status(_two_finger())
        assert bent == [False, False, True, True]

    def test_short_landmarks(self) -> None:
        bent = finger_bent_status([[0, 0, 0]] * 10)
        assert bent == [False, False, False, False]


# ── is_hand_open ─────────────────────────────────────────────────────────────

class TestIsHandOpen:
    def test_open_palm(self) -> None:
        assert is_hand_open(_open_palm()) is True

    def test_closed_fist(self) -> None:
        assert is_hand_open(_closed_fist()) is False

    def test_single_finger(self) -> None:
        assert is_hand_open(_single_finger()) is False

    def test_short_landmarks(self) -> None:
        assert is_hand_open([[0, 0, 0]] * 5) is False


# ── is_fist ───────────────────────────────────────────────────────────────────

class TestIsFist:
    def test_closed_fist(self) -> None:
        assert is_fist(_closed_fist()) is True

    def test_open_palm(self) -> None:
        assert is_fist(_open_palm()) is False

    def test_single_finger(self) -> None:
        assert is_fist(_single_finger()) is False


# ── classify_gesture ────────────────────────────────────────────────────────

class TestClassifyGesture:
    def test_open_palm(self) -> None:
        assert classify_gesture(_open_palm()) == Gesture.OPEN_PALM

    def test_fist(self) -> None:
        assert classify_gesture(_closed_fist()) == Gesture.FIST

    def test_single_finger(self) -> None:
        assert classify_gesture(_single_finger()) == Gesture.SINGLE_FINGER

    def test_two_finger(self) -> None:
        assert classify_gesture(_two_finger()) == Gesture.TWO_FINGER

    def test_unknown_partial(self) -> None:
        # Index + ring straight, middle + pinky bent — doesn't match any pattern
        lm = _make_landmarks(
            index_tip_y=60, index_mcp_y=150,    # straight
            middle_tip_y=200, middle_mcp_y=150,  # bent
            ring_tip_y=60, ring_mcp_y=150,        # straight
            pinky_tip_y=200, pinky_mcp_y=150,     # bent
        )
        assert classify_gesture(lm) == Gesture.UNKNOWN

    def test_short_landmarks(self) -> None:
        assert classify_gesture([]) == Gesture.UNKNOWN
        assert classify_gesture([[0, 0, 0]] * 5) == Gesture.UNKNOWN

    def test_priority_fist_over_two(self) -> None:
        # All bent → fist wins over two-finger
        assert classify_gesture(_closed_fist()) == Gesture.FIST


# ── palm_center ─────────────────────────────────────────────────────────────

class TestPalmCenter:
    def test_midpoint(self) -> None:
        lm = _make_landmarks(wrist_x=100, wrist_y=300, middle_mcp_x=200, middle_mcp_y_actual=150)
        center = palm_center(lm)
        assert center is not None
        assert center == (150, 225)  # (100+200)//2, (300+150)//2

    def test_short_landmarks(self) -> None:
        assert palm_center([[0, 0, 0]] * 5) is None


# ── pinch_distance ──────────────────────────────────────────────────────────

class TestPinchDistance:
    def test_close_pinch(self) -> None:
        lm = _make_landmarks(thumb_tip_x=200, thumb_tip_y=100, index_tip_x=205, index_tip_y=100)
        d = pinch_distance(lm)
        assert d is not None
        assert math.isclose(d, 5.0, abs_tol=1)

    def test_far_pinch(self) -> None:
        lm = _make_landmarks(thumb_tip_x=100, thumb_tip_y=100, index_tip_x=300, index_tip_y=100)
        d = pinch_distance(lm)
        assert d is not None
        assert math.isclose(d, 200.0, abs_tol=1)

    def test_short_landmarks(self) -> None:
        assert pinch_distance([[0, 0, 0]] * 5) is None


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — normalize_gesture_name tests
# ═══════════════════════════════════════════════════════════════════════════

class TestNormalizeGestureName:
    """Test spec §5.1 gesture name compatibility mapping."""

    # ── Official GestureRecognizer names → canonical ──────────────────────
    def test_official_none(self) -> None:
        assert normalize_gesture_name("None") == "None"

    def test_official_closed_fist(self) -> None:
        assert normalize_gesture_name("Closed_Fist") == "Closed_Fist"

    def test_official_open_palm(self) -> None:
        assert normalize_gesture_name("Open_Palm") == "Open_Palm"

    def test_official_pointing_up(self) -> None:
        assert normalize_gesture_name("Pointing_Up") == "Pointing_Up"

    def test_official_thumb_down(self) -> None:
        assert normalize_gesture_name("Thumb_Down") == "Thumb_Down"

    def test_official_thumb_up(self) -> None:
        assert normalize_gesture_name("Thumb_Up") == "Thumb_Up"

    def test_official_victory(self) -> None:
        assert normalize_gesture_name("Victory") == "Victory"

    def test_official_iloveyou(self) -> None:
        assert normalize_gesture_name("ILoveYou") == "ILoveYou"

    # ── Legacy rule names → canonical ─────────────────────────────────────
    def test_legacy_fist_to_closed_fist(self) -> None:
        assert normalize_gesture_name("fist") == "Closed_Fist"

    def test_legacy_open_palm(self) -> None:
        assert normalize_gesture_name("open_palm") == "Open_Palm"

    def test_legacy_single_finger_to_pointing_up(self) -> None:
        assert normalize_gesture_name("single_finger") == "Pointing_Up"

    def test_legacy_two_finger_to_victory(self) -> None:
        assert normalize_gesture_name("two_finger") == "Victory"

    def test_legacy_unknown_to_none(self) -> None:
        assert normalize_gesture_name("unknown") == "None"

    def test_legacy_no_hand_to_none(self) -> None:
        # "none" is the Gesture.NONE value
        assert normalize_gesture_name("none") == "None"

    # ── Gesture enum members ──────────────────────────────────────────────
    def test_enum_fist(self) -> None:
        assert normalize_gesture_name(Gesture.FIST) == "Closed_Fist"

    def test_enum_open_palm(self) -> None:
        assert normalize_gesture_name(Gesture.OPEN_PALM) == "Open_Palm"

    def test_enum_single_finger(self) -> None:
        assert normalize_gesture_name(Gesture.SINGLE_FINGER) == "Pointing_Up"

    def test_enum_two_finger(self) -> None:
        assert normalize_gesture_name(Gesture.TWO_FINGER) == "Victory"

    def test_enum_closed_fist(self) -> None:
        assert normalize_gesture_name(Gesture.CLOSED_FIST) == "Closed_Fist"

    def test_enum_none(self) -> None:
        assert normalize_gesture_name(Gesture.NONE) == "None"

    def test_enum_unknown(self) -> None:
        assert normalize_gesture_name(Gesture.UNKNOWN) == "None"

    # ── None / unrecognised ───────────────────────────────────────────────
    def test_none_input(self) -> None:
        assert normalize_gesture_name(None) == "None"

    def test_unrecognised_string(self) -> None:
        assert normalize_gesture_name("foobar") == "None"

    # ── PINCH preserved ───────────────────────────────────────────────────
    def test_pinch_preserved(self) -> None:
        assert normalize_gesture_name(Gesture.PINCH) == "PINCH"

    # ── All canonical names are in CANONICAL_GESTURE_NAMES ────────────────
    def test_all_official_names_in_canonical_set(self) -> None:
        for name in ["None", "Closed_Fist", "Open_Palm", "Pointing_Up",
                      "Thumb_Down", "Thumb_Up", "Victory", "ILoveYou"]:
            assert name in CANONICAL_GESTURE_NAMES


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — landmarks_to_hand_input produces canonical names
# ═══════════════════════════════════════════════════════════════════════════

class TestLandmarksToHandInputCanonical:
    """Verify that the rule path outputs canonical Gesture enum members."""

    def test_fist_becomes_closed_fist(self) -> None:
        hi = landmarks_to_hand_input(_closed_fist())
        assert hi.gesture == Gesture.CLOSED_FIST

    def test_open_palm_stays_open_palm(self) -> None:
        hi = landmarks_to_hand_input(_open_palm())
        assert hi.gesture == Gesture.OPEN_PALM

    def test_single_finger_becomes_pointing_up(self) -> None:
        hi = landmarks_to_hand_input(_single_finger())
        assert hi.gesture == Gesture.POINTING_UP

    def test_two_finger_becomes_victory(self) -> None:
        hi = landmarks_to_hand_input(_two_finger())
        assert hi.gesture == Gesture.VICTORY

    def test_empty_landmarks_gives_none(self) -> None:
        hi = landmarks_to_hand_input([])
        assert hi.gesture == Gesture.NONE

    def test_pinch_distance_still_computed(self) -> None:
        """PINCH is still computed from landmarks, not from GestureRecognizer."""
        hi = landmarks_to_hand_input(_open_palm())
        assert hi.pinch_distance is not None
        assert hi.pinch_distance > 0


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — to_hand_input priority logic (GestureRecognizer vs fallback)
# ═══════════════════════════════════════════════════════════════════════════

def _make_frame_result(
    landmarks: Optional[list] = None,
    gesture: Optional[str] = None,
    gesture_confidence: Optional[float] = None,
    gesture_source: Optional[str] = None,
    raw_gesture: Optional[str] = None,
) -> _FrameResult:
    """Build a _FrameResult for testing to_hand_input without a camera."""
    return _FrameResult(
        landmarks=landmarks,
        raw_hand_landmarks=None,
        gesture=gesture,
        gesture_confidence=gesture_confidence,
        gesture_source=gesture_source,
        raw_gesture=raw_gesture,
    )


class TestToHandInputGestureRecognizer:
    """Test §11 acceptance points 1–9: GestureRecognizer output → HandInput.gesture."""

    def _recognizer(self, **kwargs) -> HandRecognizer:
        defaults = dict(
            use_gesture_recognizer=True,
            min_gesture_confidence=0.65,
            fallback_to_rule_gestures=True,
        )
        defaults.update(kwargs)
        return HandRecognizer(**defaults)

    # 1. Closed_Fist
    def test_gr_closed_fist(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_closed_fist(),
            gesture="Closed_Fist",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="Closed_Fist",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.CLOSED_FIST

    # 2. Open_Palm
    def test_gr_open_palm(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_open_palm(),
            gesture="Open_Palm",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="Open_Palm",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.OPEN_PALM

    # 3. Pointing_Up
    def test_gr_pointing_up(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_single_finger(),
            gesture="Pointing_Up",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="Pointing_Up",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.POINTING_UP

    # 4. Thumb_Up
    def test_gr_thumb_up(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_open_palm(),
            gesture="Thumb_Up",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="Thumb_Up",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.THUMB_UP

    # 5. Thumb_Down
    def test_gr_thumb_down(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_open_palm(),
            gesture="Thumb_Down",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="Thumb_Down",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.THUMB_DOWN

    # 6. Victory
    def test_gr_victory(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_two_finger(),
            gesture="Victory",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="Victory",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.VICTORY

    # 7. ILoveYou
    def test_gr_iloveyou(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_open_palm(),
            gesture="ILoveYou",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
            raw_gesture="ILoveYou",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.ILOVEYOU

    # 8. Low confidence → fallback to rule
    def test_low_confidence_falls_back_to_rule(self) -> None:
        """Acceptance #8: low confidence result falls back to old rule logic."""
        r = self._recognizer(min_gesture_confidence=0.65, fallback_to_rule_gestures=True)
        # GestureRecognizer says "Open_Palm" with 0.3 confidence (below threshold).
        # Rule says FIST (from _closed_fist landmarks) → should normalize to Closed_Fist.
        fr = _make_frame_result(
            landmarks=_closed_fist(),
            gesture="Closed_Fist",       # fallback result
            gesture_confidence=0.3,      # below threshold
            gesture_source="rule_fallback",
            raw_gesture="fist",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.CLOSED_FIST

    # 9. Low confidence + fallback disabled → None
    def test_low_confidence_no_fallback_gives_none(self) -> None:
        """Acceptance #9: low confidence with fallback off → None."""
        r = self._recognizer(min_gesture_confidence=0.65, fallback_to_rule_gestures=False)
        # When fallback is off and confidence is low, the _FrameResult.gesture
        # would be "None" (set by _rule_fallback).  But Closed_Fist safety
        # override still applies.
        fr = _make_frame_result(
            landmarks=_open_palm(),  # not a fist
            gesture="None",
            gesture_confidence=0.3,
            gesture_source="none",
            raw_gesture="Open_Palm",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.NONE

    def test_low_confidence_no_fallback_but_fist_safety(self) -> None:
        """Closed_Fist safety: even with fallback off, rule fist is preserved."""
        r = self._recognizer(min_gesture_confidence=0.65, fallback_to_rule_gestures=False)
        fr = _make_frame_result(
            landmarks=_closed_fist(),
            gesture="Closed_Fist",  # safety override from _rule_fallback
            gesture_confidence=0.3,
            gesture_source="rule_fallback",
            raw_gesture="fist",
        )
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.CLOSED_FIST

    def test_no_landmarks_gives_none(self) -> None:
        r = self._recognizer()
        fr = _make_frame_result(landmarks=None, gesture="None", gesture_source="none")
        hi = r.to_hand_input(fr)
        assert hi.gesture == Gesture.NONE

    def test_pinch_distance_still_in_hand_input(self) -> None:
        """PINCH is still computed from landmarks, not from GestureRecognizer."""
        r = self._recognizer()
        fr = _make_frame_result(
            landmarks=_open_palm(),
            gesture="Open_Palm",
            gesture_confidence=0.9,
            gesture_source="gesture_recognizer",
        )
        hi = r.to_hand_input(fr)
        assert hi.pinch_distance is not None
        assert hi.pinch_distance > 0


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — process_frame with injected fake recognizer
# ═══════════════════════════════════════════════════════════════════════════

class TestProcessFrameWithFakeRecognizer:
    """Test process_frame priority logic using a fake gesture recognizer fn.

    The HandLandmarker is mocked so no real MediaPipe model is loaded.
    """

    def _make_recognizer_with_fake_landmarker(
        self,
        fake_gesture_fn: Optional[callable] = None,
        **kwargs,
    ) -> HandRecognizer:
        """Build a HandRecognizer whose HandLandmarker is faked.

        The fake landmarker returns a fixed set of landmarks every call.
        """
        defaults = dict(
            use_gesture_recognizer=True,
            min_gesture_confidence=0.65,
            fallback_to_rule_gestures=True,
            gesture_recognizer_fn=fake_gesture_fn,
        )
        defaults.update(kwargs)
        r = HandRecognizer(**defaults)

        # Inject a fake landmarker that returns closed-fist landmarks.
        class _FakeLandmark:
            def __init__(self, x, y):
                self.x = x
                self.y = y

        class _FakeResult:
            hand_landmarks = [[_FakeLandmark(0.5, 0.5) for _ in range(21)]]

        class _FakeLandmarker:
            def detect(self, mp_image):
                return _FakeResult()

            def close(self):
                pass

        r._landmarker = _FakeLandmarker()
        return r

    def test_gr_high_confidence_uses_recognizer(self) -> None:
        """When GR confidence >= threshold, use GR output."""
        def fake_fn(mp_image):
            return ("Closed_Fist", 0.95)

        r = self._make_recognizer_with_fake_landmarker(fake_fn)
        import numpy as np
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        fr = r.process_frame(img)

        assert fr.gesture == "Closed_Fist"
        assert fr.gesture_source == "gesture_recognizer"
        assert fr.gesture_confidence == 0.95

    def test_gr_low_confidence_falls_back_to_rule(self) -> None:
        """When GR confidence < threshold, fall back to rule classification."""
        def fake_fn(mp_image):
            return ("Open_Palm", 0.3)  # below 0.65

        r = self._make_recognizer_with_fake_landmarker(fake_fn)
        import numpy as np
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        fr = r.process_frame(img)

        # The fake landmarker returns all-same landmarks (0.5, 0.5), which
        # classify_gesture would see as... all tips at same y as MCPs → not bent
        # → open_palm or unknown.  The key assertion is source != "gesture_recognizer".
        assert fr.gesture_source != "gesture_recognizer"

    def test_gr_no_result_falls_back_to_rule(self) -> None:
        """When GR returns None, fall back to rule."""
        def fake_fn(mp_image):
            return None

        r = self._make_recognizer_with_fake_landmarker(fake_fn)
        import numpy as np
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        fr = r.process_frame(img)

        assert fr.gesture_source in ("rule_fallback", "none")

    def test_use_gesture_recognizer_false_skips_gr(self) -> None:
        """When use_gesture_recognizer=False, GR is never called."""
        gr_called = []

        def fake_fn(mp_image):
            gr_called.append(True)
            return ("Closed_Fist", 0.99)

        r = self._make_recognizer_with_fake_landmarker(
            fake_fn, use_gesture_recognizer=False
        )
        import numpy as np
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        fr = r.process_frame(img)

        assert len(gr_called) == 0  # GR never called
        assert fr.gesture_source in ("rule_fallback", "none")

    def test_no_hand_returns_none_gesture(self) -> None:
        """When no hand is detected, gesture is None."""
        r = self._make_recognizer_with_fake_landmarker(
            lambda mp_image: ("Closed_Fist", 0.99)
        )

        # Override landmarker to return no hands.
        class _EmptyResult:
            hand_landmarks = []

        class _EmptyLandmarker:
            def detect(self, mp_image):
                return _EmptyResult()

            def close(self):
                pass

        r._landmarker = _EmptyLandmarker()

        import numpy as np
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        fr = r.process_frame(img)

        assert fr.landmarks is None
        assert fr.gesture == "None"
        assert fr.gesture_source == "none"


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — gesture_recognizer_model_exists helper
# ═══════════════════════════════════════════════════════════════════════════

class TestGestureRecognizerModelExists:
    def test_returns_bool(self) -> None:
        result = gesture_recognizer_model_exists()
        assert isinstance(result, bool)

    def test_returns_false_for_nonexistent_file(self) -> None:
        assert gesture_recognizer_model_exists("nonexistent_model.task") is False
