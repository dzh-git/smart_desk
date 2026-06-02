"""SentenceMerger: merge ASR segment texts into readable display lines.

Joint decision: punctuation + text length + elapsed time + inter-segment gap.
Replaces pure-punctuation merging with a more robust strategy for real-time
streaming ASR where punctuation may be absent or delayed.

Usage:
    merger = SentenceMerger()
    for segment in segments:
        flushed = merger.feed(segment["text"], segment["end_time_s"],
                              segment["segment_id"])
    if merger.pending_text:
        merger.flush()
    display_lines = merger.committed_lines
    # [{text, start_time_s, end_time_s, source_segments}, ...]
"""

from __future__ import annotations


class SentenceMerger:
    """Merge streaming ASR final texts into display lines at sentence boundaries.

    Feeds segment texts one at a time (mimicking real-time arrival). Holds
    text in a pending buffer until a sentence boundary is detected via the
    joint decision function, then flushes the buffer as a committed display line.

    Joint flush criteria (any one triggers flush):
      1. Text ends with sentence-final punctuation (。！？.!?)
      2. Pending text exceeds `flush_chars` (default 40)
      3. Pending text age exceeds `flush_age_s` (default 3.0s)
      4. Pending text > `flush_chars_with_gap` (default 25) AND gap since
         last segment > `flush_gap_s` (default 1.2s) — likely sentence boundary
    """

    def __init__(
        self,
        sentence_end_chars: set[str] | None = None,
        flush_chars: int = 30,
        flush_age_s: float = 2.0,
        flush_chars_with_gap: int = 25,
        flush_gap_s: float = 1.2,
    ):
        self._sentence_end = sentence_end_chars or {"。", "！", "？", ".", "!", "?"}
        self._flush_chars = flush_chars
        self._flush_age_s = flush_age_s
        self._flush_chars_with_gap = flush_chars_with_gap
        self._flush_gap_s = flush_gap_s

        self._pending = ""
        self._committed: list[dict] = []
        self._pending_start_time: float | None = None
        self._pending_end_time: float | None = None
        self._pending_source_segments: list[int] = []

    # ── Public ─────────────────────────────────────────────────────────────

    def feed(self, text: str, end_time_s: float, segment_id: int,
             start_time_s: float | None = None) -> str | None:
        """Feed one segment's ASR final text.

        Returns the flushed text if a sentence boundary was detected,
        or None if the text is held in pending buffer.
        """
        if not text:
            return None

        from .text_utils import merge_texts

        merged = merge_texts(self._pending, text) if self._pending else text
        if not merged:
            return None

        t_start = start_time_s if start_time_s is not None else end_time_s

        # First segment in pending: record start time
        if self._pending_start_time is None:
            self._pending_start_time = t_start

        self._pending_end_time = end_time_s
        self._pending_source_segments.append(segment_id)

        if self._should_flush(merged, end_time_s):
            return self._commit(merged, end_time_s)
        else:
            self._pending = merged
            return None

    def flush(self) -> str | None:
        """Force-flush pending text. Returns the flushed text or None."""
        if not self._pending:
            return None
        return self._commit(self._pending, self._pending_end_time or 0.0)

    @property
    def committed_lines(self) -> list[dict]:
        """Committed display lines.

        Each dict: {text, start_time_s, end_time_s, source_segments: [int]}.
        """
        return list(self._committed)

    @property
    def pending_text(self) -> str:
        """Current uncommitted pending text."""
        return self._pending

    def reset(self) -> None:
        """Full reset: clear committed lines and pending buffer."""
        self._committed = []
        self._pending = ""
        self._pending_start_time = None
        self._pending_end_time = None
        self._pending_source_segments = []

    # ── Internal ───────────────────────────────────────────────────────────

    def _should_flush(self, merged: str, end_time_s: float) -> bool:
        """Joint decision: punctuation + length + age + gap."""
        if merged[-1] in self._sentence_end:
            return True

        age = end_time_s - self._pending_start_time if self._pending_start_time else 0.0

        if len(merged) > self._flush_chars:
            return True
        if age > self._flush_age_s:
            return True

        # Gap-based: long-ish pending + significant pause
        if self._pending and self._pending_end_time is not None:
            gap = end_time_s - self._pending_end_time
            if len(merged) > self._flush_chars_with_gap and gap > self._flush_gap_s:
                return True

        return False

    def _commit(self, text: str, end_time_s: float) -> str:
        """Record committed line and reset pending."""
        self._committed.append({
            "text": text,
            "start_time_s": self._pending_start_time or end_time_s,
            "end_time_s": end_time_s,
            "source_segments": list(self._pending_source_segments),
        })
        self._pending = ""
        self._pending_start_time = None
        self._pending_end_time = None
        self._pending_source_segments = []
        return text
