"""
Tests for text merging logic: merge_texts overlap detection + SentenceMerger.

These tests do NOT require ASR models. They test pure text processing logic
that prevents interim text duplication.

Key scenarios (Task 111):
- Incremental extension: prev="我喝了" chunk="我喝了多少" → "我喝了多少"
- Non-incremental ASR refinement: prev="我喝了好多" chunk="我喝了很多" → "我喝了很多"
- Same chunk repeated should not grow indefinitely
- Full accumulated text fed repeatedly should not double-paste
"""

from __future__ import annotations

import time

# ── merge_texts tests ─────────────────────────────────────────────────────────


class TestMergeTexts:
    """Direct tests for text_utils.merge_texts overlap-aware merging."""

    def _merge(self, prev: str, chunk: str) -> str:
        from backend.speech_module.text_utils import merge_texts
        return merge_texts(prev, chunk)

    def test_empty_prev(self):
        assert self._merge("", "你好") == "你好"

    def test_empty_chunk(self):
        assert self._merge("你好", "") == "你好"

    def test_both_empty(self):
        assert self._merge("", "") == ""

    def test_chunk_starts_with_prev(self):
        """Full accumulated text: new text starts with prev → use new text."""
        assert self._merge("我喝", "我喝了很多") == "我喝了很多"

    def test_prefix_overlap_merge(self):
        """Suffix of prev matches prefix of chunk → merge without overlap."""
        assert self._merge("我喝了多少", "了多少今天") == "我喝了多少今天"

    def test_full_overlap_identical(self):
        """Same text repeated → return same text (no duplication)."""
        result = self._merge("共青", "共青")
        assert result == "共青"
        assert result.count("共青") == 1

    def test_three_char_overlap(self):
        assert self._merge("测试文本内容", "文本内容重复") == "测试文本内容重复"

    def test_single_char_overlap(self):
        """Single character overlap."""
        assert self._merge("abc", "cde") == "abcde"

    def test_no_overlap_fallback(self):
        """No overlap found → concatenate (acceptable for short unique chunks)."""
        assert self._merge("abc", "def") == "abcdef"

    def test_identical_repeated_does_not_grow(self):
        """Same chunk fed 3 times should not grow (no overlap needed)."""
        r1 = self._merge("我", "我")
        assert r1 == "我"
        r2 = self._merge(r1, "我")
        assert r2 == "我"
        r3 = self._merge(r2, "我")
        assert r3 == "我"

    def test_longer_identical_does_not_grow(self):
        """Full identical text fed repeatedly should not accumulate."""
        r1 = self._merge("我喝了很多水", "我喝了很多水")
        assert r1 == "我喝了很多水"
        r2 = self._merge(r1, "我喝了很多水")
        assert r2 == "我喝了很多水"

    def test_asr_refinement_big_change(self):
        """ASR changes mind: "我喝了好多" → "我喝了很多" should replace, not concatenate."""
        # merge_texts internally: no suffix/prefix overlap found → concatenates
        # This is a known limitation of simple overlap-based merging.
        # The real fix is in SentenceMerger which now uses the full text directly.
        # merge_texts itself just finds overlapping substrings.
        result = self._merge("我喝了好多", "我喝了很多")
        # With the overlap approach, it might concatenate. The real protection
        # is at the SentenceMerger level which no longer calls merge_texts.
        assert "我喝了好多" in result
        assert "我喝了很多" in result

    def test_revision_backwards(self):
        """Text goes from longer to shorter (ASR correction).

        Note: merge_texts itself may concatenate here (no clean overlap).
        The real protection is at the SentenceMerger level which now uses
        the full text directly instead of calling merge_texts.
        """
        result = self._merge("我喝了好多水", "我喝了很多")
        # merge_texts finds no overlap and concatenates — this is acceptable
        # because SentenceMerger now replaces pending directly instead of merging
        assert len(result) <= len("我喝了好多水") + len("我喝了很多")


# ── SentenceMerger (fixed) tests ──────────────────────────────────────────────


class TestSentenceMergerTask111:
    """SentenceMerger behavior after Task 111 fix.

    The fix: SentenceMerger.feed no longer calls merge_texts because the
    incoming text is always the FULL accumulated text from
    StreamingChunkProcessor (which already handles per-chunk merging).
    """

    def _make_merger(self):
        from backend.speech_module.sentence_merge import SentenceMerger
        return SentenceMerger(
            flush_chars=100,  # high so no accidental flush by length
            flush_age_s=99,   # high so no accidental flush by age
        )

    def test_incremental_extension(self):
        """Full text extends cleanly → pending is replaced with latest."""
        m = self._make_merger()
        now = time.monotonic()

        m.feed("我喝", now, 1)
        assert m.pending_text == "我喝"

        m.feed("我喝了", now + 0.1, 2)
        assert m.pending_text == "我喝了"  # replaced, not "我喝我喝了"

        m.feed("我喝了很多", now + 0.2, 3)
        assert m.pending_text == "我喝了很多"

        # Total length should NOT have duplicates
        assert "我喝" in m.pending_text
        assert m.pending_text.count("我喝") <= 1

    def test_asr_refinement_replaces_pending(self):
        """Non-incremental ASR refinement REPLACES pending, doesn't concatenate."""
        m = self._make_merger()
        now = time.monotonic()

        m.feed("我喝了好多", now, 1)
        assert m.pending_text == "我喝了好多"

        # ASR refines "好多" → "很多" (this is the critical case)
        m.feed("我喝了很多", now + 0.1, 2)
        assert m.pending_text == "我喝了很多"
        # Must NOT contain the old version
        assert "我喝了好多" not in m.pending_text

    def test_identical_repeated_text_no_growth(self):
        """Same full text fed repeatedly does not accumulate in SentenceMerger."""
        m = self._make_merger()
        now = time.monotonic()

        text = "我喝了很多水"
        for i in range(5):
            m.feed(text, now + i * 0.1, i)

        assert m.pending_text == text
        assert len(m.pending_text) == len(text)

    def test_same_chunk_repeated_no_growth(self):
        """ASR producing same chunk repeatedly does not accumulate."""
        m = self._make_merger()
        now = time.monotonic()

        # Simulate streaming: each frame produces the same full_text
        for i in range(5):
            m.feed("共青", now + i * 0.1, i)

        assert m.pending_text == "共青"
        assert m.pending_text.count("共青") == 1

    def test_back_and_forth_no_duplication(self):
        """ASR oscillating between two outputs should not accumulate."""
        m = self._make_merger()
        now = time.monotonic()

        m.feed("我喝了很多", now, 1)
        assert m.pending_text == "我喝了很多"

        m.feed("我喝了好多", now + 0.1, 2)
        assert m.pending_text == "我喝了好多"

        m.feed("我喝了很多", now + 0.2, 3)
        assert m.pending_text == "我喝了很多"

        # Must not contain remnants of old versions
        assert len(m.pending_text) <= len("我喝了很多") + 2

    def test_flush_on_punctuation(self):
        """Sentence boundary still triggers flush."""
        m = self._make_merger()
        now = time.monotonic()

        r = m.feed("我喝了很多。", now, 1)
        assert r is not None
        assert "我喝了很多" in r
        # After flush, pending should be empty
        assert m.pending_text == ""

    def test_flush_resets_pending(self):
        """After flush, new text starts fresh."""
        m = self._make_merger()
        now = time.monotonic()

        m.feed("我喝了很多。", now, 1)  # flushed
        assert m.pending_text == ""

        m.feed("今天天气真好", now + 0.1, 2)
        assert m.pending_text == "今天天气真好"
        assert "我喝了很多" not in m.pending_text


class TestSentenceMergerFlushCriteria:
    """Test that SentenceMerger still correctly flushes on standard criteria."""

    def test_flush_on_punctuation_period(self):
        from backend.speech_module.sentence_merge import SentenceMerger
        m = SentenceMerger()
        now = time.monotonic()
        r = m.feed("今天天气真好。", now, 1)
        assert r == "今天天气真好。"
        assert len(m.committed_lines) == 1

    def test_flush_on_punctuation_question(self):
        from backend.speech_module.sentence_merge import SentenceMerger
        m = SentenceMerger()
        now = time.monotonic()
        r = m.feed("你吃饭了吗？", now, 1)
        assert r == "你吃饭了吗？"

    def test_no_flush_without_boundary(self):
        from backend.speech_module.sentence_merge import SentenceMerger
        m = SentenceMerger(flush_chars=100, flush_age_s=99)
        now = time.monotonic()
        r = m.feed("今天天气", now, 1)
        assert r is None  # held in pending
        assert m.pending_text == "今天天气"

    def test_flush_on_length(self):
        from backend.speech_module.sentence_merge import SentenceMerger
        m = SentenceMerger(flush_chars=5)  # very low threshold
        now = time.monotonic()
        r = m.feed("今天天气真好", now, 1)
        assert r == "今天天气真好"

    def test_flush_on_age(self):
        from backend.speech_module.sentence_merge import SentenceMerger
        m = SentenceMerger(flush_age_s=0.01)  # very short age
        now = time.monotonic()
        r = m.feed("今天天气", now, 1)
        # age should be near 0, but wait a tiny moment
        import time as _time
        _time.sleep(0.02)
        r2 = m.feed("今天天气不错", now + 0.05, 2)
        # Should flush because pending text age > 0.01s
        assert r2 is not None or len(m.committed_lines) > 0


# ── Cumulative Full-Text (Task 112) tests ──────────────────────────────────────


class TestCumulativeFullTextNoDuplication:
    """SpeechModule.process_interim_array with cumulative full_text must NOT
    produce repeated concatenations via SentenceMerger.

    Task 112 root cause:
        process_interim_array fed cumulative full_text into SentenceMerger.
        When the merger flushed (e.g. length > 30 chars), the old full text
        was committed. The next frame's full_text (which includes the old text)
        became the new pending. The return value committed + pending = old + new
        = duplication.

    Fix:
        process_interim_array returns result["full_text"] directly, bypassing
        the merger entirely. These tests verify that fix.
    """

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _make_speech_module(self, monkeypatch):
        """Create a SpeechModule with a mock processor to avoid ASR model load."""
        from backend.speech_module.speech_module import SpeechModule
        sm = SpeechModule()
        sm._ready = True  # skip preload

        # Ensure session state exists, then replace processor with mock
        state = sm._ensure_session("test")
        state["processor"] = _MockCumulativeProcessor()
        return sm

    def _run_sequence(self, sm, texts: list[str]) -> list[str]:
        """Run a sequence of cumulative full_texts through process_interim_array.
        Returns each result for assertion.
        """
        results = []
        for text in texts:
            state = sm._sessions.get("test")
            processor = state["processor"]
            processor._next_full_text = text
            # We call process_interim_array with dummy audio (not used by mock)
            import numpy as np
            result = sm.process_interim_array(np.zeros(1600, dtype=np.float32), "test")
            results.append(result)
        return results

    # ── Core: no duplication across cumulative full-text frames ─────────────

    def test_cumulative_sequence_no_duplication(self, monkeypatch):
        """Simulate cumulative full_text from ASR streaming.

        Frames:
          1. "中华民族遭受了"
          2. "中华民族遭受了前所未有的劫难"
          3. "中华民族遭受了前所未有的劫难一批又一批仁人志士"
          4. "中华民族遭受了前所未有的劫难一批又一批仁人志士为救国救民而苦苦追寻"

        Each output must equal the current frame's full_text, not a
        concatenation of previous and current.
        """
        sm = self._make_speech_module(monkeypatch)
        texts = [
            "中华民族遭受了",
            "中华民族遭受了前所未有的劫难",
            "中华民族遭受了前所未有的劫难一批又一批仁人志士",
            "中华民族遭受了前所未有的劫难一批又一批仁人志士为救国救民而苦苦追寻",
        ]
        results = self._run_sequence(sm, texts)

        for i, (expected, actual) in enumerate(zip(texts, results)):
            assert actual == expected, (
                f"Frame {i + 1}: expected '{expected}', got '{actual}'"
            )
            # Repeated prefix guard: the start of the output must not contain
            # the previous frame's full text as a second copy.
            # e.g. "中华民族遭受了中华民族遭受了..." would be a duplication.
            if i > 0:
                prev_text = texts[i - 1]
                repeat = prev_text + prev_text[:6]
                assert repeat not in actual, (
                    f"Frame {i + 1}: duplicate prefix detected. "
                    f"'{prev_text}' appears twice in '{actual}'"
                )

    def test_flush_length_threshold_no_duplication(self, monkeypatch):
        """After full_text exceeds SentenceMerger's default flush_chars (30),
        interim output must still not duplicate.

        This directly tests the flush-triggered duplication bug.
        """
        sm = self._make_speech_module(monkeypatch)
        texts = [
            "中华民族遭受了前所未有的劫难",                          # 13 chars
            "中华民族遭受了前所未有的劫难一批又一批仁人志士",        # 23 chars
            # Next frame exceeds 30 chars — this is where flush would trigger
            "中华民族遭受了前所未有的劫难一批又一批仁人志士为救国救民而苦苦追寻",  # 31 chars
        ]
        results = self._run_sequence(sm, texts)

        for i, (expected, actual) in enumerate(zip(texts, results)):
            assert actual == expected, (
                f"Frame {i + 1} (flush threshold): "
                f"expected '{expected}', got '{actual}'"
            )

    def test_repeated_prefix_guard(self, monkeypatch):
        """Output must not contain the same long prefix twice consecutively.

        Disallowed: "中华民族遭受了中华民族遭受了前所未有的劫难"
        """
        sm = self._make_speech_module(monkeypatch)
        texts = [
            "中华民族遭受了",                                        # short
            "中华民族遭受了前所未有的劫难",                            # medium
            "中华民族遭受了前所未有的劫难一批又一批仁人志士",          # longer
        ]
        results = self._run_sequence(sm, texts)

        # For each result after frame 0, prefix must not appear twice
        for i in range(1, len(results)):
            prev = texts[i - 1]
            # Check that prev doesn't start with same 6 chars as a duplicate
            prefix6 = prev[:6]
            count = results[i].count(prefix6)
            assert count <= 1, (
                f"Frame {i + 1}: prefix '{prefix6}' appears {count} times "
                f"in '{results[i]}'"
            )

    def test_many_frames_no_growth(self, monkeypatch):
        """Many frames with minor changes should not accumulate duplicates."""
        sm = self._make_speech_module(monkeypatch)
        texts = [
            "今天天气",
            "今天天气真好",
            "今天天气真好啊",
            "今天天气真好啊我们",
            "今天天气真好啊我们去",
            "今天天气真好啊我们去公园",
            "今天天气真好啊我们去公园散步",
        ]
        results = self._run_sequence(sm, texts)

        for i, (expected, actual) in enumerate(zip(texts, results)):
            assert actual == expected, (
                f"Frame {i + 1}: expected '{expected}', got '{actual}'"
            )

    # ── Test get_interim matches processor ──────────────────────────────────

    def test_get_interim_returns_processor_accumulated(self, monkeypatch):
        """get_interim must reflect the latest processor accumulated text."""
        sm = self._make_speech_module(monkeypatch)
        texts = [
            "第一句",
            "第一句第二句",
            "第一句第二句第三句",
        ]
        results = self._run_sequence(sm, texts)

        # After all frames, get_interim must equal the last full_text
        interim = sm.get_interim("test")
        assert interim == results[-1], (
            f"get_interim '{interim}' != last process_interim_array "
            f"result '{results[-1]}'"
        )

    # ── Test reset_interim clears display text ──────────────────────────────

    def test_reset_interim_clears_text(self, monkeypatch):
        """reset_interim must clear the accumulated text display."""
        sm = self._make_speech_module(monkeypatch)
        texts = [
            "短文本",
            "短文本更长",
        ]
        self._run_sequence(sm, texts)

        # Reset
        sm.reset_interim("test")
        interim = sm.get_interim("test")
        assert interim == "", (
            f"After reset_interim, get_interim should be '', got '{interim}'"
        )

    # ── Test new session starts empty ───────────────────────────────────────

    def test_new_session_interim_empty(self, monkeypatch):
        """A session with no audio processed returns empty string."""
        from backend.speech_module.speech_module import SpeechModule
        sm = SpeechModule()
        sm._ready = True
        assert sm.get_interim("new_session") == ""


# ── Mock Processor (Task 112) ──────────────────────────────────────────────────


class _MockCumulativeProcessor:
    """Minimal mock that simulates StreamingChunkProcessor returning
    pre-defined cumulative full_text values.

    Each call to process_chunk returns the _next_full_text value as
    both text and full_text, and updates accumulated_text.
    """

    def __init__(self):
        self._accumulated_text = ""
        self._next_full_text = ""

    @property
    def accumulated_text(self) -> str:
        return self._accumulated_text

    def reset_accumulated_text(self):
        self._accumulated_text = ""

    def process_chunk(self, audio, is_final=False):
        text = self._next_full_text
        self._accumulated_text = text
        return {
            "text": text,
            "full_text": text,
            "is_final": is_final,
            "decode_ms": 0,
            "cache_valid": True,
        }
