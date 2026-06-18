"""MediaPipe hand-landmark recognition + gesture classification.

Split into:
    - Pure classification functions (``classify_gesture``, ``finger_bent``,
      ``palm_center``, ``pinch_distance``) that operate on a landmark list and
      are unit-tested without a camera.
    - ``HandRecognizer`` which owns the MediaPipe ``HandLandmarker`` and turns
      a BGR/RGB camera frame into a :class:`HandInput` for the state machine.

Landmark convention (MediaPipe Hands, 21 points): the classification logic is
ported from ``hands/test2.py`` (``is_hand_open``, ``get_finger_bent_status``)
but expressed as functions of a ``landmarks`` list where each entry is
``[id, x_px, y_px]`` — identical shape to the reference so behavior matches.

Uses the MediaPipe Task API (mediapipe >= 0.10.0) which requires the
hand_landmarker.task model file placed alongside the project root.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .gesture_state import Gesture, HandInput

logger = logging.getLogger("hands.recognition")

# Path to the hand landmarker model file (download on first use if missing).
_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)

# A landmark row mirrors the reference impl: [id, x_px, y_px].
Landmark = List[float]
LandmarkList = List[Landmark]

# Finger tip / root landmark indices (MediaPipe Hands).
TIPS = (8, 12, 16, 20)     # index, middle, ring, pinky
ROOTS = (5, 9, 13, 17)     # corresponding MCP joints
THUMB_TIP = 4
THUMB_IP = 2
WRIST = 0
MIDDLE_MCP = 9


# ── pure classification helpers ──────────────────────────────────────────────
def finger_bent(landmarks: LandmarkList, tip_idx: int, root_idx: int) -> bool:
    """A finger is "bent" when its tip is below (larger y) its root.

    This is the same heuristic as the reference implementation; it assumes an
    upright hand. ``True`` means bent.
    """
    if len(landmarks) <= max(tip_idx, root_idx):
        return False
    return landmarks[tip_idx][2] > landmarks[root_idx][2]


def finger_bent_status(landmarks: LandmarkList) -> List[bool]:
    """Return ``[index, middle, ring, pinky]`` bent flags."""
    if len(landmarks) < 21:
        return [False, False, False, False]
    return [finger_bent(landmarks, TIPS[i], ROOTS[i]) for i in range(4)]


def is_hand_open(landmarks: LandmarkList) -> bool:
    """True when thumb + all four fingers are extended (open palm)."""
    if len(landmarks) < 21:
        return False
    # Thumb: tip is to the side (smaller x in a right hand, but the reference
    # uses y-comparison against the IP joint — keep parity with test2.py).
    thumb_straight = landmarks[THUMB_TIP][2] < landmarks[THUMB_IP][2]
    fingers_straight = [not b for b in finger_bent_status(landmarks)]
    return thumb_straight and all(fingers_straight)


def is_fist(landmarks: LandmarkList) -> bool:
    """True when all four fingers are bent (thumb ignored, matching reference)."""
    return all(finger_bent_status(landmarks))


def classify_gesture(landmarks: LandmarkList) -> Gesture:
    """Map a 21-point landmark list to a single :class:`Gesture`.

    Priority order (highest first):
        1. fist            — all four fingers bent
        2. two_finger      — index + middle straight, ring + pinky bent  (drag)
        3. single_finger   — only index straight                          (mouse)
        4. open_palm       — every finger straight                        (wave)
        5. unknown         — anything else
    """
    if len(landmarks) < 21:
        return Gesture.UNKNOWN

    bent = finger_bent_status(landmarks)  # [index, middle, ring, pinky]
    index_straight = not bent[0]
    middle_straight = not bent[1]
    ring_bent = bent[2]
    pinky_bent = bent[3]

    if all(bent):
        return Gesture.FIST
    if index_straight and middle_straight and ring_bent and pinky_bent:
        return Gesture.TWO_FINGER
    if index_straight and (not middle_straight) and ring_bent and pinky_bent:
        return Gesture.SINGLE_FINGER
    if is_hand_open(landmarks):
        return Gesture.OPEN_PALM
    return Gesture.UNKNOWN


def palm_center(landmarks: LandmarkList) -> Optional[Tuple[int, int]]:
    """Midpoint of wrist(0) and middle-finger MCP(9) — same anchor as test2.py."""
    if len(landmarks) <= MIDDLE_MCP:
        return None
    x = int((landmarks[WRIST][1] + landmarks[MIDDLE_MCP][1]) / 2)
    y = int((landmarks[WRIST][2] + landmarks[MIDDLE_MCP][2]) / 2)
    return (x, y)


def pinch_distance(landmarks: LandmarkList) -> Optional[float]:
    """Euclidean distance between thumb tip(4) and index tip(8), in camera px."""
    if len(landmarks) <= THUMB_TIP or len(landmarks) <= TIPS[0]:
        return None
    x4, y4 = landmarks[THUMB_TIP][1], landmarks[THUMB_TIP][2]
    x8, y8 = landmarks[TIPS[0]][1], landmarks[TIPS[0]][2]
    return math.hypot(x8 - x4, y8 - y4)


def landmarks_to_hand_input(landmarks: LandmarkList) -> HandInput:
    """Build a :class:`HandInput` from a classified landmark list."""
    if not landmarks or len(landmarks) < 21:
        return HandInput(gesture=Gesture.NONE)
    gesture = classify_gesture(landmarks)
    palm = palm_center(landmarks)
    return HandInput(
        gesture=gesture,
        palm_xy=palm,
        wave_x=float(palm[0]) if palm is not None else None,
        pinch_distance=pinch_distance(landmarks),
    )


# ── model download helper ─────────────────────────────────────────────────────
def _resolve_model_path() -> str:
    """Return the path to hand_landmarker.task, downloading it if needed.

    Looks in the project root (one level above the ``hands`` package).
    """
    # One level up from hands/ → project root
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(pkg_dir)
    model_path = os.path.join(root, "hand_landmarker.task")
    if not os.path.exists(model_path):
        logger.info("downloading hand landmarker model to %s", model_path)
        import urllib.request

        urllib.request.urlretrieve(_MODEL_URL, model_path)
    return model_path


# ── MediaPipe wrapper ────────────────────────────────────────────────────────
@dataclass
class _FrameResult:
    landmarks: Optional[LandmarkList] = None   # None when no hand detected
    raw_hand_landmarks: Optional[List] = None  # for debug drawing (Task API)


class HandRecognizer:
    """Owns the MediaPipe ``HandLandmarker`` model and converts frames to HandInput.

    Uses the Task API (mediapipe >= 0.10.0).  The underlying TFLite model is
    constructed lazily so importing this module (e.g. in tests) does not require
    MediaPipe to be installed.
    """

    def __init__(
        self,
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        self._max_num_hands = max_num_hands
        self._min_detection = min_detection_confidence
        self._min_tracking = min_tracking_confidence
        self._landmarker = None  # HandLandmarker | None
        self._model_path: Optional[str] = None  # resolved lazily

    # ── lifecycle ──────────────────────────────────────────────────────────
    def _ensure_model(self) -> None:
        if self._landmarker is not None:
            return
        import mediapipe.tasks
        from mediapipe.tasks.python.vision import (
            HandLandmarker,
            HandLandmarkerOptions,
            RunningMode,
        )

        self._model_path = _resolve_model_path()

        options = HandLandmarkerOptions(
            base_options=mediapipe.tasks.BaseOptions(
                model_asset_path=self._model_path
            ),
            running_mode=RunningMode.IMAGE,
            num_hands=self._max_num_hands,
            min_hand_detection_confidence=self._min_detection,
            min_tracking_confidence=self._min_tracking,
        )
        self._landmarker = HandLandmarker.create_from_options(options)

    def close(self) -> None:
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("closing MediaPipe HandLandmarker failed")
            self._landmarker = None

    # ── frame processing ───────────────────────────────────────────────────
    def process_frame(self, img_rgb) -> _FrameResult:
        """Run MediaPipe on an RGB frame and extract the first hand's landmarks."""
        self._ensure_model()
        import mediapipe as mp

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        result = self._landmarker.detect(mp_image)  # type: ignore[union-attr]

        hand_landmarks = result.hand_landmarks
        if not hand_landmarks:
            return _FrameResult()

        hand_lms = hand_landmarks[0]  # list[NormalizedLandmark] (21 points)
        h, w = img_rgb.shape[:2]
        landmarks: LandmarkList = []
        for idx, lm in enumerate(hand_lms):
            landmarks.append([idx, int(lm.x * w), int(lm.y * h)])
        return _FrameResult(landmarks, hand_landmarks)

    def to_hand_input(self, frame_result: _FrameResult) -> HandInput:
        if frame_result.landmarks is None:
            return HandInput(gesture=Gesture.NONE)
        return landmarks_to_hand_input(frame_result.landmarks)

    # ── debug drawing ──────────────────────────────────────────────────────
    def draw(self, img_bgr, frame_result: _FrameResult) -> None:
        """Draw landmarks on a BGR image for the debug window (no-op if no model)."""
        if self._landmarker is None or frame_result.raw_hand_landmarks is None:
            return
        try:
            from mediapipe.tasks.python.vision import (
                drawing_utils,
                HandLandmarksConnections,
            )

            for hand_lms in frame_result.raw_hand_landmarks:
                drawing_utils.draw_landmarks(
                    img_bgr,
                    hand_lms,
                    HandLandmarksConnections.HAND_CONNECTIONS,
                )
        except Exception:  # pragma: no cover - drawing must never break the loop
            logger.exception("debug draw failed")
