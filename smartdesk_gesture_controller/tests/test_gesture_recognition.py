"""Tests for hands.gesture_recognition — pure classification functions.

These test ``classify_gesture``, ``is_hand_open``, ``is_fist``,
``finger_bent_status``, ``palm_center``, and ``pinch_distance`` by constructing
synthetic landmark lists. No MediaPipe model, no camera.
"""
from __future__ import annotations

import math

import pytest

from hands.gesture_recognition import (
    classify_gesture,
    finger_bent_status,
    is_fist,
    is_hand_open,
    palm_center,
    pinch_distance,
)
from hands.gesture_state import Gesture


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
