"""
Tests for CaptionFormatter (two-line live caption) and helper functions.

These tests do NOT require ASR models.  All punctuation is provided by the
heuristic fallback (adds 。 at end of text) unless a custom punctuator is
injected via the ``punctuator=`` parameter.

Run:  pytest tests/test_caption_formatter.py -q
"""

from __future__ import annotations

import time

import pytest

from backend.speech_module.caption_formatter import (
    CaptionConfig,
    CaptionFormatter,
    CaptionResult,
    _count_raw_chars,
    _find_split,
    _punc_offset_for_raw,
)
from backend.speech_module.punctuation import ALL_BOUNDARY


# ═════════════════════════════════════════════════════════════════════════════
# Helpers  (used as punctuator= arguments)
# ═════════════════════════════════════════════════════════════════════════════


def _no_punc(text: str) -> str:
    """Identity punctuator — returns text unchanged."""
    return text


def _embed_comma_punc(text: str) -> str:
    """Insert ，after the 14th character (as a realistic mid-sentence break),
    plus 。 at the very end."""
    if len(text) >= 14:
        return text[:14] + "，" + text[14:] + "。"
    return text + "。"


def _embed_period_punc(text: str) -> str:
    """Insert 。 after the 6th character (mid-text) + 。 at end."""
    if len(text) >= 6:
        return text[:6] + "。" + text[6:] + "。"
    return text + "。"


# ═════════════════════════════════════════════════════════════════════════════
# Stateless helper: _count_raw_chars
# ═════════════════════════════════════════════════════════════════════════════


class TestCountRawChars:
    def test_empty(self):
        assert _count_raw_chars("") == 0

    def test_all_raw(self):
        assert _count_raw_chars("今天天气真好") == 6

    def test_mixed(self):
        # "今天，天气真好。" = 6 raw chars (今 天 天 气 真 好)
        assert _count_raw_chars("今天，天气真好。") == 6

    def test_only_punctuation(self):
        assert _count_raw_chars("。？！") == 0


# ═════════════════════════════════════════════════════════════════════════════
# Stateless helper: _punc_offset_for_raw
# ═════════════════════════════════════════════════════════════════════════════


class TestPuncOffsetForRaw:
    def test_zero_raw_len(self):
        assert _punc_offset_for_raw("今天天气真好。", 0) == 0

    def test_no_punctuation(self):
        assert _punc_offset_for_raw("今天天气真好", 6) == 6

    def test_with_trailing_boundary(self):
        """6 raw chars + trailing 。→ offset should be past the 。"""
        assert _punc_offset_for_raw("今天天气真好。", 6) == 7

    def test_with_embedded_comma(self):
        """6 raw chars + ，→ offset past the ，"""
        assert _punc_offset_for_raw("今天天气真好，我们。", 6) == 7

    def test_raw_len_exceeds(self):
        """When raw_len exceeds available raw chars, returns full string length."""
        assert _punc_offset_for_raw("今天。", 10) == 3

    def test_empty_punctuated(self):
        assert _punc_offset_for_raw("", 5) == 0


# ═════════════════════════════════════════════════════════════════════════════
# Stateless helper: _find_split  (core splitting logic)
# ═════════════════════════════════════════════════════════════════════════════


class TestFindSplit:
    """Rules:
    1. Earliest valid boundary (any type) within max_len wins.
    2. A boundary at the very end of text is NOT a split trigger.
    3. Forced split at max_len when text exceeds max_len.
    """

    def _split(self, text: str, **kw):
        # These tests exercise the helper's configurable legacy thresholds.
        kw.setdefault("min_len", 5)
        kw.setdefault("max_len", 31)
        return _find_split(text, **kw)

    def test_empty_text_returns_zero(self):
        assert self._split("") == 0

    def test_no_boundary_short(self):
        """Text within max_len and no punctuation → no split."""
        assert self._split("今天天气真好") == 0

    def test_strong_boundary_embedded_splits(self):
        """。at pos 6, not at end → i+1=7 >= 5 → split at 7."""
        assert self._split("今天天气真好。我们") == 7

    def test_weak_boundary_embedded_splits(self):
        """，at pos 6, not at end → i+1=7 >= 5 → split at 7."""
        assert self._split("今天天气真好，我们") == 7

    def test_trailing_boundary_at_end_does_not_split(self):
        """Boundary as the last character is provisional → no split."""
        assert self._split("今天天气真好。") == 0   # 。 at end
        assert self._split("今天天气真好，") == 0   # ， at end

    def test_earliest_boundary_wins(self):
        """Comma at pos 4 comes before period at later pos → split at comma."""
        # "天气真好，我们去。" — ， at pos 4 (i+1=5, 5<len) → split at 5
        assert self._split("天气真好，我们去。") == 5

    def test_short_before_period_no_split(self):
        """<5 raw chars before 。→ no split."""
        assert self._split("你好。") == 0  # 。at end + len<5 anyway

    def test_short_before_comma_no_split(self):
        """<5 raw chars before ，→ no split."""
        assert self._split("我，") == 0  # 2 chars

    def test_no_forced_split_under_31(self):
        """31 chars with no punctuation → no forced split (len not > 31)."""
        assert self._split("A" * 31) == 0

    def test_forced_split_at_max_len(self):
        """32 chars with no punctuation → forced split at 31."""
        assert self._split("A" * 32) == 31

    def test_comma_within_first_max_len_of_long_text(self):
        """Long text with comma not at end → split at comma."""
        text = "A" * 10 + "，" + "B" * 24
        # ， at pos 10, i+1=11 >= 5, 11 < len=35 → split at 11
        assert self._split(text) == 11

    def test_forced_split_no_boundary_in_range(self):
        """32-char text without punctuation in first 31 → forced split at 31."""
        assert self._split("A" * 32) == 31


class TestDefaultTwentyToThirtyFiveLayout:
    def test_short_boundary_waits_for_next_natural_boundary(self):
        text = "A" * 10 + "，" + "B" * 14 + "。" + "C"
        assert _find_split(text) == 26

    def test_boundary_in_target_range_splits(self):
        assert _find_split("A" * 20 + "，" + "后续") == 21

    def test_colon_is_a_display_boundary_in_target_range(self):
        assert _find_split("A" * 20 + "：" + "后续") == 21

    def test_forced_split_happens_only_after_35_characters(self):
        assert _find_split("A" * 35) == 0
        assert _find_split("A" * 36) == 35

    def test_result_only_commits_terminal_boundary_with_later_text(self):
        natural = CaptionFormatter(
            punctuator=lambda text: text[:20] + "。" + text[20:],
        ).update("A" * 24, time.monotonic())
        assert natural.natural_boundary_committed is True
        assert natural.committed_boundary == "。"

        provisional = CaptionFormatter(
            punctuator=lambda text: text + "。",
        ).update("A" * 24, time.monotonic())
        assert provisional.natural_boundary_committed is False

        forced = CaptionFormatter(punctuator=_no_punc).update(
            "A" * 36, time.monotonic(),
        )
        assert forced.natural_boundary_committed is False
        assert forced.previous_line == ""
        assert forced.current_line == "A" * 36

    def test_timeout_keeps_short_line_waiting(self):
        formatter = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        formatter.update("短句仍需继续", now)
        assert formatter.check_timeout(now + 3.0) is None


# ═════════════════════════════════════════════════════════════════════════════
# NEW: Live interim  behaviour  (Issue 1  — fallback 标点不导致 current_line 为空)
# ═════════════════════════════════════════════════════════════════════════════


class TestLiveInterimNotCommittedEarly:
    """With the default heuristic punctuator, short-to-medium live interim
    text must stay in ``current_line`` and NOT be committed to
    ``previous_line`` just because a trailing heuristic 。 exists.
    """

    def test_default_heuristic_keeps_current_line(self):
        """Core scenario from the bug report:
        ``CaptionFormatter().update("今天天气真好", now).current_line``
        should NOT be empty.
        """
        f = CaptionFormatter(CaptionConfig(min_line_length=5))
        result = f.update("今天天气真好", time.monotonic())
        assert result.previous_line == ""   # NOT committed
        assert result.current_line != ""    # stays in current-line
        assert "今天天气真好" in result.current_line

    def test_cumulative_text_grows_in_current_line(self):
        """With fallback punctuation, current_line reflects the latest
        cumulative text across multiple frames."""
        heuristic = lambda text: text if not text or text[-1] in ALL_BOUNDARY else text + "。"
        f = CaptionFormatter(punctuator=heuristic)
        now = time.monotonic()
        texts = ["今天", "今天天气", "今天天气真好", "今天天气真好我们"]
        for i, t in enumerate(texts):
            r = f.update(t, now + i * 0.1)
            assert r.previous_line == ""
            assert t in r.current_line, (
                f"Frame {i}: expected '{t}' in current_line, got '{r.current_line}'"
            )

    def test_timeout_does_not_visually_commit_heuristic_text(self):
        """Speech VAD, not a frozen caption, owns natural-pause commit."""
        f = CaptionFormatter(CaptionConfig(min_line_length=5))
        now = time.monotonic()
        f.update("今天天气真好", now)
        assert f.check_timeout(now + 2.5) is None

    def test_already_punctuated_text_stays_in_current(self):
        """Text that already ends with 。stays in current_line when it
        is the last character."""
        heuristic = lambda text: text if not text or text[-1] in ALL_BOUNDARY else text + "。"
        f = CaptionFormatter(punctuator=heuristic)
        result = f.update("好的。", time.monotonic())
        assert result.previous_line == ""
        assert result.current_line == "好的。"


# ═════════════════════════════════════════════════════════════════════════════
# Punctuation boundary triggers split (embedded — not at end of text)
# ═════════════════════════════════════════════════════════════════════════════


class TestPunctuationTriggersSplit:
    """Punctuation NOT at the very end of text triggers a split."""

    def test_period_triggers_split_when_embedded(self):
        """。mid-text → split."""
        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=_embed_period_punc)
        result = f.update("今天天气真好我们", time.monotonic())
        # punc: "今天天气真好。我们。" — 。at pos 6, 7 < len → split at 7
        assert result.previous_line == "今天天气真好。"
        assert "我们" in result.current_line

    def test_question_mark_triggers_split(self):
        """？mid-text → split."""
        def q_punc(text):
            if len(text) >= 5:
                return text[:5] + "？" + text[5:] + "。"
            return text + "？"

        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=q_punc)
        result = f.update("你吃饭了吗明天", time.monotonic())
        # "你吃饭了吗？明天。" — ？at pos 5, i+1=6 >= 5, 6 < len → split at 6
        assert result.previous_line == "你吃饭了吗？"
        assert "明天" in result.current_line

    def test_comma_does_not_trigger_semantic_split(self):
        """A visual clause comma remains in the forming semantic sentence."""
        def comma_punc(text):
            if len(text) >= 6:
                return text[:6] + "，" + text[6:] + "。"
            return text + "。"

        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=comma_punc)
        result = f.update("今天天气真好我们", time.monotonic())
        assert result.previous_line == ""
        assert result.current_line == "今天天气真好，我们。"


# ═════════════════════════════════════════════════════════════════════════════
# NEW: Comma-first split  (Issue 2 — 逗号优先于句号断句)
# ═════════════════════════════════════════════════════════════════════════════


class TestCommaFirstSplit:
    """When both comma and period exist, the EARLIEST valid boundary wins."""

    def test_comma_before_period_remains_one_caption_sentence(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=_embed_comma_punc)
        # "中华民族遭受了前所未有的劫难，一批又一批仁人志士。"
        raw = "中华民族遭受了前所未有的劫难一批又一批仁人志士"
        result = f.update(raw, time.monotonic())
        assert result.previous_line == ""
        assert result.current_line.endswith("一批又一批仁人志士。")

    def test_period_before_comma_splits_at_period(self):
        """Period appears earlier than comma → split at period."""
        def early_period_punc(text: str) -> str:
            # Insert 。 after 6 chars only — no other punctuation
            if len(text) >= 6:
                return text[:6] + "。" + text[6:]
            return text

        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=early_period_punc)
        raw = "今天天气真好我们出去散步了"  # 13 raw chars
        result = f.update(raw, time.monotonic())
        # punctuated = "今天天气真好。我们出去散步了" (14 chars)
        # 。at pos 6 is earliest valid (7 < 14) → split at 7
        assert result.previous_line == "今天天气真好。"
        assert "我们出去散步了" in result.current_line


# ═════════════════════════════════════════════════════════════════════════════
# <5 chars before punctuation, no early break
# ═════════════════════════════════════════════════════════════════════════════


class TestMinLineLength:
    """Punctuation before min_line_length (5) does NOT cause a split."""

    def test_short_text_with_period_no_split(self):
        f = CaptionFormatter()
        result = f.update("你好", time.monotonic())
        assert result.previous_line == ""
        assert result.current_line == "你好。"

    def test_short_text_with_comma_no_split(self):
        """Comma after 2 chars → no split (<5)."""
        def comma_early_punc(text):
            if len(text) >= 2:
                return text[:2] + "，" + text[2:] + "。"
            return text + "。"

        f = CaptionFormatter(punctuator=comma_early_punc)
        result = f.update("我你", time.monotonic())
        assert result.previous_line == ""
        assert len(result.current_line) >= 3


# ═════════════════════════════════════════════════════════════════════════════
# 31-char forced split
# ═════════════════════════════════════════════════════════════════════════════


class TestNoForcedVisualSplit:
    """Long text is retained; browser layout owns visual wrapping."""

    def test_long_unpunctuated_text_is_not_committed(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5, max_line_length=31), punctuator=_no_punc)
        text = "A" * 32
        result = f.update(text, time.monotonic())
        assert result.previous_line == ""
        assert result.current_line == text

    def test_long_text_with_no_terminal_boundary_is_not_committed(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5, max_line_length=31), punctuator=_no_punc)
        text = "B" * 32
        result = f.update(text, time.monotonic())
        assert result.previous_line == ""
        assert result.current_line == text

    def test_comma_in_long_text_does_not_commit(self):
        def comma_only_punc(text):
            if len(text) >= 16:
                return text[:16] + "，" + text[16:]
            return text

        f = CaptionFormatter(CaptionConfig(min_line_length=5, max_line_length=31), punctuator=comma_only_punc)
        raw = "A" * 32
        result = f.update(raw, time.monotonic())
        assert result.previous_line == ""
        assert result.current_line == "A" * 16 + "，" + "A" * 16

    def test_multiple_long_updates_keep_complete_cumulative_text(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5, max_line_length=31), punctuator=_no_punc)
        now = time.monotonic()

        f.update("A" * 20, now)
        f.update("A" * 30, now + 0.1)
        r3 = f.update("A" * 32, now + 0.2)
        assert r3.previous_line == ""
        assert r3.current_line == "A" * 32

        r4 = f.update("A" * 40, now + 0.3)
        assert r4.previous_line == ""
        assert r4.current_line == "A" * 40


# ═════════════════════════════════════════════════════════════════════════════
# Timeout compatibility remains a no-op; PCM/VAD owns pause boundaries
# ═════════════════════════════════════════════════════════════════════════════


class TestTimeoutSplit:
    """>2 seconds without text change does not commit current_line."""

    def test_timeout_before_expiry_no_split(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=_no_punc)
        now = time.monotonic()
        f.update("今天天气真好我们", now)
        assert f.check_timeout(now + 1.0) is None

    def test_timeout_does_not_trigger_visual_split(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=_no_punc)
        now = time.monotonic()
        result = f.update("今天天气真好我们", now)
        assert result.previous_line == ""
        assert result.current_line == "今天天气真好我们"

        assert f.check_timeout(now + 2.5) is None

    def test_timeout_only_commits_when_min_length_met(self):
        """Short text (<5 chars) is NOT committed by timeout."""
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        f.update("你好", now)
        assert f.check_timeout(now + 3.0) is None

    def test_timeout_does_not_repeat_after_commit(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        f.update("今天天气真好我们", now)
        f.check_timeout(now + 2.5)
        assert f.check_timeout(now + 3.0) is None  # nothing new

    def test_timeout_is_noop_with_heuristic(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5))
        now = time.monotonic()
        f.update("今天天气真好", now)
        assert f.check_timeout(now + 2.5) is None


# ═════════════════════════════════════════════════════════════════════════════
# Identical input does not grow
# ═════════════════════════════════════════════════════════════════════════════


class TestIdenticalInputNoGrowth:
    """Repeated identical cumulative input must not produce duplicated text."""

    def test_same_text_returns_same_result(self):
        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=_no_punc)
        now = time.monotonic()
        r1 = f.update("今天天气真好", now)
        r2 = f.update("今天天气真好", now + 0.1)
        assert r1.punctuated_text == r2.punctuated_text
        assert r1.previous_line == r2.previous_line
        assert r1.current_line == r2.current_line

    def test_identical_repeated_does_not_change(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        for i in range(5):
            r = f.update("共青", now + i * 0.1)
            assert r.previous_line == ""
            assert r.current_line == "共青"
            assert len(r.punctuated_text) == 2

    def test_repeated_with_heuristic_stable(self):
        """Even with heuristic punctuation, repeated input is stable."""
        f = CaptionFormatter(CaptionConfig(min_line_length=5))
        now = time.monotonic()
        r1 = f.update("共青", now)
        r2 = f.update("共青", now + 0.1)
        assert r1.punctuated_text == r2.punctuated_text
        assert len(r1.punctuated_text) == 3
        assert len(r2.punctuated_text) == 3


# ═════════════════════════════════════════════════════════════════════════════
# Cumulative updates must not duplicate text
# ═════════════════════════════════════════════════════════════════════════════


class TestCumulativeNoDuplication:
    """Growing cumulative input must not re-paste already-committed text."""

    def test_growing_text_no_duplication(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        texts = ["今天", "今天天气", "今天天气真好", "今天天气真好我们"]
        for i, t in enumerate(texts):
            r = f.update(t, now + i * 0.1)
            assert r.punctuated_text == t
            if i > 0:
                assert t.startswith(texts[i - 1])

    def test_punctuated_growth_preserves_order(self):
        f = CaptionFormatter()
        result = f.update("今天天气真好我们去", time.monotonic())
        raw = "".join(c for c in result.punctuated_text
                      if c not in "。？！，、；：,.?!;:")
        assert raw == "今天天气真好我们去"

    def test_cumulative_commit_no_missing_chars(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        r1 = f.update("今天天气", now)
        assert r1.current_line == "今天天气"
        r2 = f.update("今天天气真好我们", now + 0.1)
        assert r2.current_line == "今天天气真好我们"
        assert r2.current_line.startswith("今天天气")


# ═════════════════════════════════════════════════════════════════════════════
# Two-line only (previous_line / current_line)
# ═════════════════════════════════════════════════════════════════════════════


class TestTwoLineOnly:
    """Only one previous_line is retained (the latest committed sentence)."""

    def test_previous_line_tracks_latest_true_terminal_sentence(self):
        """Only a terminal punctuation boundary moves a compatibility line."""
        f = CaptionFormatter(CaptionConfig(min_line_length=5), punctuator=_no_punc)
        now = time.monotonic()

        r1 = f.update("AAAAA。BBBBB", now)
        assert r1.previous_line == "AAAAA。"
        r2 = f.update("AAAAA。BBBBB。CCCCC", now + 0.1)
        assert r2.previous_line == "BBBBB。"
        assert r2.current_line == "CCCCC"

    def test_two_line_mode_flag(self):
        f = CaptionFormatter()
        result = f.update("测试", time.monotonic())
        assert result.mode == "two_line"


# ═════════════════════════════════════════════════════════════════════════════
# Reset clears state
# ═════════════════════════════════════════════════════════════════════════════


class TestReset:
    """reset() clears all previous state so the next utterance starts clean."""

    def test_reset_clears_lines(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        f.update("今天天气真好", now)
        f.reset()
        result = f.update("新的", now + 5.0)
        assert "今天" not in result.punctuated_text
        assert result.punctuated_text == "新的"

    def test_reset_allows_reuse(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        f.update("第一句", now)
        f.reset()
        r = f.update("第二句完整文本", now + 1.0)
        assert "第一" not in r.punctuated_text
        assert r.punctuated_text == "第二句完整文本"

    def test_reset_with_heuristic_does_not_leak(self):
        f = CaptionFormatter()
        now = time.monotonic()
        f.update("今天天气真好", now)  # stays in current_line (no early commit)
        f.reset()
        r = f.update("你好", now + 1.0)
        assert "今天" not in r.punctuated_text
        assert r.previous_line == ""


# ═════════════════════════════════════════════════════════════════════════════
# Integration scenarios
# ═════════════════════════════════════════════════════════════════════════════


class TestIntegrationScenarios:
    """Multi-frame sequences that simulate real ASR streaming."""

    def test_simple_incremental_flow(self):
        """Default formatter keeps text until a true terminal boundary."""
        f = CaptionFormatter(CaptionConfig(min_line_length=5))
        now = time.monotonic()

        r1 = f.update("今天", now)
        assert r1.previous_line == ""
        assert "今天" in r1.current_line

        r2 = f.update("今天天气真好", now + 0.1)
        assert r2.previous_line == ""
        assert "今天天气真好" in r2.current_line

        assert f.check_timeout(now + 2.5) is None
        r3 = f.update("今天天气真好。我们去了", now + 2.6)
        assert r3.previous_line == "今天天气真好。"
        assert "我们去了" in r3.current_line

    def test_asr_refinement_no_duplication(self):
        f = CaptionFormatter(punctuator=_no_punc)
        now = time.monotonic()
        r1 = f.update("我喝了好多", now)
        assert r1.current_line == "我喝了好多"
        r2 = f.update("我喝了很多", now + 0.1)
        assert "好多" not in r2.current_line

    def test_no_leak_between_utterances(self):
        """Two complete utterances with reset in between."""
        f = CaptionFormatter()
        now = time.monotonic()

        # Utterance 1: grows, timeout commits, reset
        f.update("今天天气不错", now)
        f.check_timeout(now + 2.5)  # commit via timeout
        f.reset()

        # Utterance 2: no trace of utterance 1
        r2 = f.update("新的句子", now + 3.0)
        assert "今天" not in r2.punctuated_text
        assert "天气" not in r2.punctuated_text
        assert r2.previous_line == ""  # fresh start

    def test_mode_is_always_two_line(self):
        f = CaptionFormatter()
        result = f.update("你好", time.monotonic())
        assert result.mode == "two_line"
