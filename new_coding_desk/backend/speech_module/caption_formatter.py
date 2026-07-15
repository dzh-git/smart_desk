"""Caption Formatter: punctuated two-line live caption for streaming ASR.

Transforms cumulative raw ASR text into a punctuated two-line caption state
suitable for real-time subtitle-style display:

    previous_line — last committed short sentence
    current_line  — sentence currently being formed/refined
    mode          — "two_line"

Sentence splitting is driven by:
  1. Punctuation boundaries (。？！!? 优先，, 作为次选)
  2. Length-based forced split at configurable maximum (default 35 chars)
  3. Idle timeout (default 2 s of no text change)

Usage:
    from speech_module.caption_formatter import CaptionFormatter, CaptionConfig

    fmt = CaptionFormatter()
    result = fmt.update("今天天气真好我们", time.monotonic())
    # → CaptionResult(punctuated_text="今天天气真好，我们",
    #                  previous_line="今天天气真好，",
    #                  current_line="我们",
    #                  mode="two_line")
    fmt.reset()            # between utterances
    fmt.check_timeout(t2)  # when no new text arrives
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .punctuation import add_punctuation, ALL_BOUNDARY, SENTENCE_END


# ── Data Structures ──────────────────────────────────────────────────────────


@dataclass
class CaptionConfig:
    """Tunable parameters for sentence splitting decisions.

    All lengths count **characters** (Unicode code points), not bytes.
    """

    sentence_end: frozenset[str] = field(
        default_factory=lambda: SENTENCE_END,
    )
    comma_boundary: frozenset[str] = field(
        default_factory=lambda: frozenset({"，", ",", "、", "；", ";"}),
    )
    all_boundary: frozenset[str] = field(
        default_factory=lambda: ALL_BOUNDARY,
    )

    #: Minimum characters before a punctuation boundary causes a line break.
    min_line_length: int = 20

    #: Maximum characters (including punctuation) before a forced line break.
    max_line_length: int = 35

    #: Seconds of no text change before the uncommitted line is auto-submitted.
    text_change_timeout_s: float = 2.0


@dataclass
class CaptionResult:
    """Output of a single ``update()`` or ``check_timeout()`` call."""

    #: The full cumulative text with punctuation inserted.
    punctuated_text: str = ""

    #: The last complete sentence (or short phrase).
    previous_line: str = ""

    #: The sentence being formed — may be empty when text was just committed.
    current_line: str = ""

    #: Always ``"two_line"`` for this formatter.
    mode: str = "two_line"

    #: True only when this update committed a punctuation boundary that was
    #: already inside the text. A provisional punctuation mark at the current
    #: text tail and a length-forced split both leave this False.
    natural_boundary_committed: bool = False

    #: Punctuation character for the most recent natural boundary committed
    #: during this update; empty when no natural boundary was committed.
    committed_boundary: str = ""


# ── Formatter ────────────────────────────────────────────────────────────────


class CaptionFormatter:
    """Convert cumulative ASR text → punctuated two-line caption.

    **Stateful per utterance.** Call ``reset()`` between utterances (speech
    start / cancel / seat switch) to prevent state leakage.

    Thread-safety: not guaranteed. Each speech session should own its own
    ``CaptionFormatter`` instance.
    """

    def __init__(
        self,
        config: Optional[CaptionConfig] = None,
        punctuator=None,
    ):
        """Parameters
        ----------
        config:
            Tunable sentence-splitting parameters.  See ``CaptionConfig``.
        punctuator:
            Callable ``(raw_text: str) -> str`` that returns punctuated text.
            Defaults to ``add_punctuation`` from ``punctuation.py``.
            Override for testing (e.g. identity function).
        """
        self.config = config or CaptionConfig()
        self._punctuator = punctuator or add_punctuation

        # Number of *raw* (non-punctuation) characters that have been
        # fully committed as complete sentences.  Used to derive the
        # uncommitted suffix from the punctuated text.
        self._committed_raw_len: int = 0

        # Last complete sentence in its punctuated form.
        self._previous_line: str = ""

        # Idempotency / change detection.
        self._last_raw: str = ""
        self._last_punctuated: str = ""
        self._last_change_time: float = 0.0
        self._natural_boundary_committed: bool = False
        self._committed_boundary: str = ""

    # ── Public API ─────────────────────────────────────────────────────────

    def update(self, raw_text: str, now: float) -> CaptionResult:
        """Feed the **full cumulative** ASR text and get the updated caption.

        Parameters
        ----------
        raw_text:
            The entire text recognised so far for the current utterance,
            **without** backend-added punctuation.
        now:
            Value of ``time.monotonic()`` at the time the raw text was
            received (used for idle-timeout tracking).

        Returns
        -------
        CaptionResult with the current two-line caption state.
        """
        # ── Empty / no-change short-circuit ────────────────────────────
        if not raw_text:
            return CaptionResult()

        if raw_text == self._last_raw:
            self._natural_boundary_committed = False
            self._committed_boundary = ""
            return self._make_result()

        # ── Handle text shortening (ASR correction) ────────────────────
        if self._committed_raw_len > len(raw_text):
            self._committed_raw_len = 0
            self._previous_line = ""

        # ── Punctuate ─────────────────────────────────────────────────
        self._last_raw = raw_text
        self._last_change_time = now
        self._last_punctuated = self._punctuator(raw_text)
        self._natural_boundary_committed = False
        self._committed_boundary = ""

        # ── Commit any complete sentences ─────────────────────────────
        self._commit_sentences()

        return self._make_result()

    def check_timeout(self, now: float) -> Optional[CaptionResult]:
        """If no text change for longer than the timeout, commit the
        current uncommitted line (provided it has at least ``min_line_length``
        characters).

        Returns ``None`` when the timeout has not yet expired or when there
        is nothing to commit.  Otherwise returns the updated ``CaptionResult``.
        """
        if not self._last_raw:
            return None

        elapsed = now - self._last_change_time
        if elapsed < self.config.text_change_timeout_s:
            return None

        uncommitted = self._get_uncommitted()
        if len(uncommitted) < self.config.min_line_length:
            return None

        raw_chars = _count_raw_chars(uncommitted, self.config.all_boundary)
        if raw_chars == 0:
            return None

        self._previous_line = uncommitted.strip()
        self._committed_raw_len += raw_chars
        self._last_change_time = now  # prevent repeated trigger
        self._natural_boundary_committed = False
        self._committed_boundary = ""
        return self._make_result()

    def reset(self) -> None:
        """Clear all state for a new utterance."""
        self._committed_raw_len = 0
        self._previous_line = ""
        self._last_raw = ""
        self._last_punctuated = ""
        self._last_change_time = 0.0
        self._natural_boundary_committed = False
        self._committed_boundary = ""

    # ── Internal helpers ───────────────────────────────────────────────

    def _get_uncommitted(self) -> str:
        """Return the suffix of ``_last_punctuated`` that has not yet been
        committed as a completed sentence."""
        if not self._last_punctuated:
            return ""
        offset = _punc_offset_for_raw(self._last_punctuated,
                                      self._committed_raw_len,
                                      self.config.all_boundary)
        return self._last_punctuated[offset:]

    def _commit_sentences(self) -> None:
        """Repeatedly find and commit complete sentences from the
        uncommitted suffix until no more can be found."""
        while True:
            uncommitted = self._get_uncommitted()
            if not uncommitted:
                break

            split, natural_boundary = _find_split_details(
                uncommitted,
                max_len=self.config.max_line_length,
                min_len=self.config.min_line_length,
                all_boundary=self.config.all_boundary,
                sentence_end=self.config.sentence_end,
                comma_boundary=self.config.comma_boundary,
            )
            if split == 0:
                break

            sentence = uncommitted[:split].strip()
            if not sentence:
                break

            raw_chars = _count_raw_chars(sentence,
                                         self.config.all_boundary)
            if raw_chars == 0:
                break  # safety: prevents infinite loop

            self._previous_line = sentence
            self._committed_raw_len += raw_chars
            self._natural_boundary_committed |= natural_boundary
            if natural_boundary:
                self._committed_boundary = sentence[-1]

    def _make_result(self) -> CaptionResult:
        return CaptionResult(
            punctuated_text=self._last_punctuated,
            previous_line=self._previous_line,
            current_line=self._get_uncommitted(),
            mode="two_line",
            natural_boundary_committed=self._natural_boundary_committed,
            committed_boundary=self._committed_boundary,
        )


# ── Stateless helpers (purpose-agnostic, easy to unit-test) ──────────────────


def _find_split(
    text: str,
    max_len: int = 35,
    min_len: int = 20,
    all_boundary: frozenset[str] = ALL_BOUNDARY,
    sentence_end: frozenset[str] = SENTENCE_END,
    comma_boundary: frozenset[str] = frozenset({"，", ",", "、", "；", ";"}),
) -> int:
    """Find the best position at which to split ``text`` into a complete
    sentence + remainder.

    Returns the index *after* the last character that belongs to the
    complete sentence (i.e. ``text[:return_value]`` is the sentence).
    Returns **0** when no split should happen.

    Decision logic
    --------------
    1. **Earliest valid boundary** (any type): scan left→right within the
       first ``max_len`` characters.  The moment a punctuation character
       that is **not at the very end** of ``text`` appears with at least
       ``min_len`` characters before it, split there.  This gives the
       most responsive live captions — whichever boundary (strong or weak)
       appears first wins.

       The "not at the very end" condition (``i + 1 < len(text)``)
       prevents a heuristic fallback period added only because no other
       punctuation exists from immediately emptying ``current_line``.

    2. **Forced split** (``len(text) > max_len``): if no valid natural
       boundary exists in the 20--35 character target window, split at
       ``max_len``.
    """
    return _find_split_details(
        text,
        max_len=max_len,
        min_len=min_len,
        all_boundary=all_boundary,
        sentence_end=sentence_end,
        comma_boundary=comma_boundary,
    )[0]


def _find_split_details(
    text: str,
    max_len: int = 35,
    min_len: int = 20,
    all_boundary: frozenset[str] = ALL_BOUNDARY,
    sentence_end: frozenset[str] = SENTENCE_END,
    comma_boundary: frozenset[str] = frozenset({"，", ",", "、", "；", ";"}),
) -> tuple[int, bool]:
    """Return ``(split_index, is_natural_punctuation_boundary)``."""
    if not text:
        return 0, False

    # ── 1. Earliest valid boundary (any type) ─────────────────────────────
    #     Boundary at the very end of text is *not* a split trigger —
    #     it's provisional (e.g. heuristic fallback 。).
    for i, ch in enumerate(text):
        if i >= max_len:
            break
        if ch in all_boundary and i + 1 >= min_len and i + 1 < len(text):
            return i + 1, True

    # ── 2. Forced split (text longer than max_len) ────────────────────────
    #     Use the LAST boundary within max_len for the most natural break.
    if len(text) > max_len:
        last_boundary = 0
        for i, ch in enumerate(text[:max_len]):
            if ch in all_boundary and i + 1 >= min_len:
                last_boundary = i + 1
        if last_boundary > 0:
            return last_boundary, True
        return max_len, False

    return 0, False


def _punc_offset_for_raw(
    punctuated: str,
    raw_len: int,
    boundary_chars: frozenset[str] = ALL_BOUNDARY,
) -> int:
    """Given ``raw_len`` raw (non-boundary) characters, return the
    corresponding offset in the punctuated string.

    The returned offset is *past* any trailing boundary characters that
    belong to the same sentence unit (e.g. the period a sentence ends
    with).  This ensures that when a sentence like ``"今天天气真好。"``
    is committed (6 raw chars), the offset points *after* the period.

    Example
    -------
    >>> _punc_offset_for_raw("今天天气真好。", 6, ALL_BOUNDARY)
    7
    # 6 raw chars "今天天气真好" + trailing 。= offset 7.
    """
    if raw_len <= 0 or not punctuated:
        return 0
    count = 0
    for i in range(len(punctuated)):
        if punctuated[i] not in boundary_chars:
            count += 1
            if count == raw_len:
                # Skip any trailing boundary characters — they belong to
                # the committed sentence (e.g. the 。or ，that triggered
                # the split).
                j = i + 1
                while j < len(punctuated) and punctuated[j] in boundary_chars:
                    j += 1
                return j
    return len(punctuated)


def _count_raw_chars(
    text: str,
    boundary_chars: frozenset[str] = ALL_BOUNDARY,
) -> int:
    """Count the number of non-boundary (i.e. raw content) characters."""
    if not text:
        return 0
    return sum(1 for c in text if c not in boundary_chars)
