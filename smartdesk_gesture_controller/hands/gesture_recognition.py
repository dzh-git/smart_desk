"""MediaPipe hand-landmark recognition + gesture classification.

Split into:
    - Pure classification functions (``classify_gesture``, ``finger_bent``,
      ``palm_center``, ``pinch_distance``) that operate on a landmark list and
      are unit-tested without a camera.
    - ``HandRecognizer`` which owns the MediaPipe ``HandLandmarker`` (and,
      since Phase 8, optionally a ``GestureRecognizer``) and turns a BGR/RGB
      camera frame into a :class:`HandInput` for the state machine.

Landmark convention (MediaPipe Hands, 21 points): the classification logic is
ported from ``hands/test2.py`` (``is_hand_open``, ``get_finger_bent_status``)
but expressed as functions of a ``landmarks`` list where each entry is
``[id, x_px, y_px]`` — identical shape to the reference so behavior matches.

Uses the MediaPipe Task API (mediapipe >= 0.10.0) which requires the
hand_landmarker.task model file placed alongside the project root.

Phase 8 (GestureRecognizer integration):
    * When ``use_gesture_recognizer=True`` the recognizer also loads
      ``gesture_recognizer.task`` and uses MediaPipe's official canned-gesture
      classification as the *primary* source for static gestures.
    * Legacy landmark-rule classification (``classify_gesture``) is kept as a
      fallback when the official confidence is below ``min_gesture_confidence``.
    * PINCH / SWIPE / HOLD / DRAG are **not** affected — they continue to be
      computed from landmarks / state-machine logic.
    * Gesture names are normalised to the spec-canonical set before reaching
      the state machine: ``None``, ``Closed_Fist``, ``Open_Palm``,
      ``Pointing_Up``, ``Thumb_Down``, ``Thumb_Up``, ``Victory``, ``ILoveYou``.
"""
from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

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

# ═══════════════════════════════════════════════════════════════════════════
# Phase 8 — Gesture name normalisation
# ═══════════════════════════════════════════════════════════════════════════
# The spec-canonical gesture names (GESTURE_MAPPING_SPEC §5.1).  The state
# machine only ever sees these names.
CANONICAL_GESTURE_NAMES = frozenset({
    "None", "Closed_Fist", "Open_Palm", "Pointing_Up",
    "Thumb_Down", "Thumb_Up", "Victory", "ILoveYou",
})

# Map MediaPipe GestureRecognizer official category names → Gesture enum.
# Official names are already canonical, but "None" (capital) must become
# Gesture.NONE so the state machine's _normalize_gesture maps it to "none".
_OFFICIAL_TO_GESTURE: dict[str, Gesture] = {
    "None": Gesture.NONE,
    "Closed_Fist": Gesture.CLOSED_FIST,
    "Open_Palm": Gesture.OPEN_PALM,
    "Pointing_Up": Gesture.POINTING_UP,
    "Thumb_Down": Gesture.THUMB_DOWN,
    "Thumb_Up": Gesture.THUMB_UP,
    "Victory": Gesture.VICTORY,
    "ILoveYou": Gesture.ILOVEYOU,
}

# Map legacy rule-based Gesture enum members → canonical Gesture enum members.
# This implements the GESTURE_MAPPING_SPEC §5.1 compatibility table.
_LEGACY_TO_CANONICAL_GESTURE: dict[Gesture, Gesture] = {
    Gesture.NONE: Gesture.NONE,
    Gesture.FIST: Gesture.CLOSED_FIST,
    Gesture.OPEN_PALM: Gesture.OPEN_PALM,
    Gesture.SINGLE_FINGER: Gesture.POINTING_UP,
    Gesture.TWO_FINGER: Gesture.VICTORY,
    Gesture.PINCH: Gesture.PINCH,           # PINCH is not a static gesture — kept as-is
    Gesture.UNKNOWN: Gesture.NONE,
    # Spec-canonical members pass through.
    Gesture.CLOSED_FIST: Gesture.CLOSED_FIST,
    Gesture.POINTING_UP: Gesture.POINTING_UP,
    Gesture.THUMB_UP: Gesture.THUMB_UP,
    Gesture.THUMB_DOWN: Gesture.THUMB_DOWN,
    Gesture.VICTORY: Gesture.VICTORY,
    Gesture.ILOVEYOU: Gesture.ILOVEYOU,
}


def normalize_gesture_name(gesture) -> str:
    """Normalise any gesture representation to a spec-canonical name string.

    Accepts:
        * A :class:`Gesture` enum member (legacy or canonical).
        * A raw string from the GestureRecognizer (e.g. ``"Closed_Fist"``).
        * ``None`` (treated as no-hand).

    Returns one of the canonical names in :data:`CANONICAL_GESTURE_NAMES`,
    except that ``PINCH`` is preserved as ``"PINCH"`` (it is not a static
    gesture and is computed separately from landmarks).
    """
    if gesture is None:
        return "None"
    if isinstance(gesture, Gesture):
        canonical = _LEGACY_TO_CANONICAL_GESTURE.get(gesture, Gesture.NONE)
        if canonical is Gesture.PINCH:
            return "PINCH"
        # Return the spec-canonical display name.
        return _gesture_to_canonical_string(canonical)
    # Raw string path (e.g. from GestureRecognizer or legacy code).
    s = str(gesture).strip()
    # Direct official-name hit.
    if s in _OFFICIAL_TO_GESTURE:
        g = _OFFICIAL_TO_GESTURE[s]
        if g is Gesture.PINCH:
            return "PINCH"
        return _gesture_to_canonical_string(g)
    # Try matching against Gesture enum values (legacy lowercase names).
    try:
        g = Gesture(s)
    except ValueError:
        pass
    else:
        canonical = _LEGACY_TO_CANONICAL_GESTURE.get(g, Gesture.NONE)
        if canonical is Gesture.PINCH:
            return "PINCH"
        return _gesture_to_canonical_string(canonical)
    # Unrecognised string → None (safe default).
    return "None"


def _gesture_to_canonical_string(g: Gesture) -> str:
    """Return the spec-canonical display string for a Gesture enum member."""
    _MAP = {
        Gesture.NONE: "None",
        Gesture.CLOSED_FIST: "Closed_Fist",
        Gesture.OPEN_PALM: "Open_Palm",
        Gesture.POINTING_UP: "Pointing_Up",
        Gesture.THUMB_UP: "Thumb_Up",
        Gesture.THUMB_DOWN: "Thumb_Down",
        Gesture.VICTORY: "Victory",
        Gesture.ILOVEYOU: "ILoveYou",
        Gesture.PINCH: "PINCH",
    }
    return _MAP.get(g, "None")


def _canonical_gesture_enum(gesture) -> Gesture:
    """Normalise to a canonical Gesture enum member (for HandInput.gesture)."""
    if gesture is None:
        return Gesture.NONE
    if isinstance(gesture, Gesture):
        return _LEGACY_TO_CANONICAL_GESTURE.get(gesture, Gesture.NONE)
    s = str(gesture).strip()
    if s in _OFFICIAL_TO_GESTURE:
        return _OFFICIAL_TO_GESTURE[s]
    try:
        g = Gesture(s)
    except ValueError:
        return Gesture.NONE
    return _LEGACY_TO_CANONICAL_GESTURE.get(g, Gesture.NONE)


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
    """Build a :class:`HandInput` from a classified landmark list (rule path).

    This is the legacy rule-based path.  The resulting ``gesture`` is a
    *canonical* Gesture enum member (e.g. ``Gesture.CLOSED_FIST`` instead of
    ``Gesture.FIST``) so the state machine receives normalised names.
    """
    if not landmarks or len(landmarks) < 21:
        return HandInput(gesture=Gesture.NONE)
    raw = classify_gesture(landmarks)
    gesture = _LEGACY_TO_CANONICAL_GESTURE.get(raw, Gesture.NONE)
    palm = palm_center(landmarks)
    return HandInput(
        gesture=gesture,
        palm_xy=palm,
        wave_x=float(palm[0]) if palm is not None else None,
        pinch_distance=pinch_distance(landmarks),
    )


# ── model path helpers ───────────────────────────────────────────────────────
def _project_root() -> str:
    """Return the project root (one level above the ``hands`` package)."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(pkg_dir)


def _resolve_model_path() -> str:
    """Return the path to hand_landmarker.task, downloading it if needed.

    Looks in the project root (one level above the ``hands`` package).
    """
    model_path = os.path.join(_project_root(), "hand_landmarker.task")
    if not os.path.exists(model_path):
        logger.info("downloading hand landmarker model to %s", model_path)
        import urllib.request

        urllib.request.urlretrieve(_MODEL_URL, model_path)
    return model_path


def _resolve_gesture_recognizer_path(model_filename: str = "gesture_recognizer.task") -> str:
    """Return the path to gesture_recognizer.task.

    Unlike hand_landmarker.task, this file is **never** auto-downloaded
    (spec §18.2: "现场演示不应依赖自动下载模型文件").  The caller is
    responsible for checking existence via :func:`check_model_files`.
    """
    return os.path.join(_project_root(), model_filename)


def gesture_recognizer_model_exists(model_filename: str = "gesture_recognizer.task") -> bool:
    """Check whether gesture_recognizer.task exists in the project root."""
    return os.path.exists(_resolve_gesture_recognizer_path(model_filename))


# ── MediaPipe wrapper ────────────────────────────────────────────────────────
@dataclass
class _FrameResult:
    """Everything extracted from one camera frame.

    ``landmarks`` / ``raw_hand_landmarks`` come from HandLandmarker.
    ``gesture`` / ``gesture_confidence`` / ``gesture_source`` / ``raw_gesture``
    come from the Phase-8 GestureRecognizer + fallback logic.
    """
    landmarks: Optional[LandmarkList] = None   # None when no hand detected
    raw_hand_landmarks: Optional[List] = None  # for debug drawing (Task API)
    # Phase 8 gesture recognition metadata (carried for debug display).
    gesture: Optional[str] = None               # normalised canonical name
    gesture_confidence: Optional[float] = None
    gesture_source: Optional[str] = None        # "gesture_recognizer" / "rule_fallback" / "none"
    raw_gesture: Optional[str] = None           # raw name before normalisation


class HandRecognizer:
    """Owns the MediaPipe ``HandLandmarker`` model and converts frames to HandInput.

    Uses the Task API (mediapipe >= 0.10.0).  The underlying TFLite model is
    constructed lazily so importing this module (e.g. in tests) does not require
    MediaPipe to be installed.

    Phase 8: optionally also loads a ``GestureRecognizer`` for official
    canned-gesture classification.  When enabled, the recognizer output is the
    *primary* source for static gestures; the legacy landmark-rule
    classification is kept as a fallback.
    """

    def __init__(
        self,
        max_num_hands: int = 1,
        min_detection_confidence: float = 0.7,
        min_tracking_confidence: float = 0.5,
        *,
        use_gesture_recognizer: bool = True,
        min_gesture_confidence: float = 0.65,
        fallback_to_rule_gestures: bool = True,
        gesture_recognizer_model_path: str = "gesture_recognizer.task",
        gesture_recognizer_fn: Optional[Callable] = None,
    ) -> None:
        self._max_num_hands = max_num_hands
        self._min_detection = min_detection_confidence
        self._min_tracking = min_tracking_confidence
        self._landmarker = None  # HandLandmarker | None
        self._model_path: Optional[str] = None  # resolved lazily

        # Phase 8 — GestureRecognizer config
        self._use_gesture_recognizer = use_gesture_recognizer
        self._min_gesture_confidence = min_gesture_confidence
        self._fallback_to_rule_gestures = fallback_to_rule_gestures
        self._gesture_recognizer_model_path = gesture_recognizer_model_path
        self._gesture_recognizer = None  # GestureRecognizer | None
        # Injection point for tests: a callable(mp_image) -> Optional[tuple[str, float]]
        # returning (category_name, score) or None.  When None, the real
        # GestureRecognizer is used (lazily).
        self._gesture_recognizer_fn = gesture_recognizer_fn

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

    def _ensure_gesture_recognizer(self) -> None:
        """Lazily create the MediaPipe GestureRecognizer (if enabled)."""
        if not self._use_gesture_recognizer:
            return
        if self._gesture_recognizer is not None or self._gesture_recognizer_fn is not None:
            return  # already created, or test injection will be used
        import mediapipe.tasks
        from mediapipe.tasks.python.vision import (
            GestureRecognizer,
            GestureRecognizerOptions,
            RunningMode,
        )

        model_path = _resolve_gesture_recognizer_path(self._gesture_recognizer_model_path)
        if not os.path.exists(model_path):
            # Should have been caught by check_model_files, but guard anyway.
            raise FileNotFoundError(
                f"Gesture recognizer model not found: {model_path}. "
                f"Set use_gesture_recognizer=False to use rule-based fallback only."
            )

        options = GestureRecognizerOptions(
            base_options=mediapipe.tasks.BaseOptions(model_asset_path=model_path),
            running_mode=RunningMode.IMAGE,
            num_hands=self._max_num_hands,
        )
        self._gesture_recognizer = GestureRecognizer.create_from_options(options)

    def close(self) -> None:
        if self._landmarker is not None:
            try:
                self._landmarker.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("closing MediaPipe HandLandmarker failed")
            self._landmarker = None
        if self._gesture_recognizer is not None:
            try:
                self._gesture_recognizer.close()
            except Exception:  # pragma: no cover - defensive
                logger.exception("closing MediaPipe GestureRecognizer failed")
            self._gesture_recognizer = None

    # ── frame processing ───────────────────────────────────────────────────
    def process_frame(self, img_rgb) -> _FrameResult:
        """Run MediaPipe on an RGB frame and extract landmarks + gesture."""
        self._ensure_model()
        import mediapipe as mp

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=img_rgb)
        result = self._landmarker.detect(mp_image)  # type: ignore[union-attr]

        hand_landmarks = result.hand_landmarks
        if not hand_landmarks:
            return _FrameResult(gesture="None", gesture_source="none", raw_gesture=None)

        hand_lms = hand_landmarks[0]  # list[NormalizedLandmark] (21 points)
        h, w = img_rgb.shape[:2]
        landmarks: LandmarkList = []
        for idx, lm in enumerate(hand_lms):
            landmarks.append([idx, int(lm.x * w), int(lm.y * h)])

        # ── Phase 8: run GestureRecognizer for official canned gestures ──
        gesture_name: Optional[str] = None
        gesture_conf: Optional[float] = None
        raw_gesture: Optional[str] = None
        source: str = "none"

        if self._use_gesture_recognizer:
            gr_result = self._run_gesture_recognizer(mp_image)
            if gr_result is not None:
                raw_gesture, gesture_conf = gr_result
                if gesture_conf is not None and gesture_conf >= self._min_gesture_confidence:
                    gesture_name = normalize_gesture_name(raw_gesture)
                    source = "gesture_recognizer"

        # Fallback to rule-based classification if recognizer didn't give a
        # confident result.
        if gesture_name is None:
            gesture_name, source, raw_gesture = self._rule_fallback(landmarks)

        return _FrameResult(
            landmarks=landmarks,
            raw_hand_landmarks=hand_landmarks,
            gesture=gesture_name,
            gesture_confidence=gesture_conf,
            gesture_source=source,
            raw_gesture=raw_gesture,
        )

    def _run_gesture_recognizer(self, mp_image) -> Optional[Tuple[str, float]]:
        """Run the GestureRecognizer on an mp.Image.

        Returns ``(category_name, score)`` for the top gesture, or ``None``
        if the recognizer is unavailable or produced no result.
        """
        # Test-injection path.
        if self._gesture_recognizer_fn is not None:
            return self._gesture_recognizer_fn(mp_image)

        try:
            self._ensure_gesture_recognizer()
        except FileNotFoundError:
            logger.warning("gesture_recognizer.task not found — using rule fallback")
            return None
        except Exception:  # pragma: no cover - defensive
            logger.exception("GestureRecognizer init failed — using rule fallback")
            return None

        if self._gesture_recognizer is None:
            return None

        try:
            gr_result = self._gesture_recognizer.recognize(mp_image)
        except Exception:  # pragma: no cover - defensive
            logger.exception("GestureRecognizer recognize failed — using rule fallback")
            return None

        # gr_result.gestures is a list of list[Category]; take the first hand's top gesture.
        if not gr_result.gestures or not gr_result.gestures[0]:
            return None
        top = gr_result.gestures[0][0]
        return (top.category_name, float(top.score))

    def _rule_fallback(self, landmarks: LandmarkList) -> Tuple[str, str, Optional[str]]:
        """Run legacy landmark-rule classification and normalise.

        Returns ``(canonical_name, source, raw_name)``.

        Safety note (spec §5.3 point 4): ``Closed_Fist`` is a safety-critical
        gesture used for exit / release_all.  Even when
        ``fallback_to_rule_gestures=False``, if the rule detects a fist we
        still return ``Closed_Fist`` so the user can always exit.
        """
        raw = classify_gesture(landmarks)
        raw_name = raw.value if isinstance(raw, Gesture) else str(raw)

        # Safety override: always allow Closed_Fist from rules.
        if raw is Gesture.FIST:
            return ("Closed_Fist", "rule_fallback", raw_name)

        if not self._fallback_to_rule_gestures:
            return ("None", "none", raw_name)

        canonical = normalize_gesture_name(raw)
        # If the rule returns UNKNOWN, treat as None (spec §5.1: UNKNOWN → None).
        if raw is Gesture.UNKNOWN:
            return ("None", "none", raw_name)
        return (canonical, "rule_fallback", raw_name)

    def to_hand_input(self, frame_result: _FrameResult) -> HandInput:
        """Convert a :class:`_FrameResult` to a :class:`HandInput`.

        The ``gesture`` field is set to a *canonical* Gesture enum member so
        the state machine receives normalised names.  PINCH / palm / pinch
        distance are still computed from landmarks (unchanged).
        """
        if frame_result.landmarks is None:
            return HandInput(gesture=Gesture.NONE)

        # Determine the canonical Gesture enum from the normalised name.
        gesture_enum = _canonical_gesture_enum(frame_result.gesture)

        palm = palm_center(frame_result.landmarks)
        return HandInput(
            gesture=gesture_enum,
            palm_xy=palm,
            wave_x=float(palm[0]) if palm is not None else None,
            pinch_distance=pinch_distance(frame_result.landmarks),
        )

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
