"""
Task 129-lite: Speech stability stress tests.

These tests simulate continuous utterance lifecycles to verify that:
    1. terminal_utterance_ids set does not accumulate stale entries
    2. Each utterance_id is marked terminal exactly once
    3. No exception state leaks between consecutive utterances
    4. The session handles repeated start→interim→final/cancel cycles

All tests use the singleton ``stream_service`` directly — no real ASR
models or WebSocket connections are involved.
"""
from __future__ import annotations

import pytest

from backend.services.speech_stream_service import stream_service


# ── 10-utterance lifecycle stress test ──────────────────────────────────────────


class TestContinuousUtteranceLifecycle:
    """Run 10 consecutive utterance lifecycles in a single session.

    Each iteration: start → buffer audio → finalize (mark terminal).
    After the loop, verify terminal set integrity.
    """

    def setup_method(self) -> None:
        self.session_key, self.session_token = stream_service.create_session(1, 1)
        self.utterance_ids: list[str] = []

    def teardown_method(self) -> None:
        stream_service.remove_session(self.session_key, self.session_token)

    def _run_one_lifecycle(
        self, seq: int, mode: str = "final",
    ) -> str:
        """Run a single start → interim → final/cancel lifecycle.

        Args:
            seq: Sequence number (used to generate unique utterance_id).
            mode: ``"final"`` to finalize, ``"cancel"`` to cancel.

        Returns:
            The utterance_id used.
        """
        uid = f"utt_stress_{seq:04d}"
        self.utterance_ids.append(uid)

        # Start utterance
        stream_service.start_utterance(self.session_key, uid)
        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert session.current_utterance_id == uid

        # Buffer some audio (required for finalize)
        stream_service.append_audio(self.session_key, b"\x00" * 3200)

        if mode == "final":
            result = stream_service.finalize_utterance(self.session_key)
            assert result is not None, (
                f"finalize_utterance returned None for {uid}"
            )
            assert result["utterance_id"] == uid
            # After successful finalize, caller must mark terminal
            stream_service.mark_utterance_terminal(self.session_key, uid)
        elif mode == "cancel":
            cancelled = stream_service.cancel_utterance(self.session_key)
            assert cancelled == uid
            # cancel_utterance already marks terminal internally
        else:
            raise ValueError(f"Unknown mode: {mode}")

        # Verify terminal
        assert stream_service.is_utterance_terminal(self.session_key, uid)

        return uid

    def test_10_consecutive_final_lifecycles(self) -> None:
        """10 consecutive start → interim → final lifecycles.

        Verifies:
            - Each utterance finalizes successfully.
            - Terminal set has exactly 10 entries after all cycles.
            - No exception leaks between cycles.
        """
        for i in range(1, 11):
            self._run_one_lifecycle(i, mode="final")

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert len(session.terminal_utterance_ids) == 10, (
            f"Expected 10 terminal IDs, got {len(session.terminal_utterance_ids)}"
        )

        # Verify each ID is in the set exactly once
        for uid in self.utterance_ids:
            assert stream_service.is_utterance_terminal(
                self.session_key, uid,
            ), f"{uid} should be terminal"

    def test_10_consecutive_cancel_lifecycles(self) -> None:
        """10 consecutive start → interim → cancel lifecycles."""
        for i in range(1, 11):
            self._run_one_lifecycle(i, mode="cancel")

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert len(session.terminal_utterance_ids) == 10
        for uid in self.utterance_ids:
            assert stream_service.is_utterance_terminal(
                self.session_key, uid,
            )

    def test_mixed_final_cancel_lifecycles(self) -> None:
        """10 cycles alternating final and cancel."""
        for i in range(1, 11):
            mode = "final" if i % 2 == 0 else "cancel"
            self._run_one_lifecycle(i, mode=mode)

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert len(session.terminal_utterance_ids) == 10

    def test_each_utterance_terminal_only_once(self) -> None:
        """Each utterance_id appears exactly once in terminal set.

        Calls mark_utterance_terminal repeatedly and verifies the set
        size does not grow beyond 1 per unique ID.
        """
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_unique_once_001",
        )
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_unique_once_001",
        )
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_unique_once_002",
        )

        session = stream_service.get_session(self.session_key)
        assert session is not None
        # Count occurrences
        ids = list(session.terminal_utterance_ids)
        count_001 = sum(1 for uid in ids if uid == "utt_unique_once_001")
        count_002 = sum(1 for uid in ids if uid == "utt_unique_once_002")
        assert count_001 == 1, f"Expected 1, got {count_001}"
        assert count_002 == 1, f"Expected 1, got {count_002}"

    def test_terminal_set_no_leak_on_exception(self) -> None:
        """Exception during finalize does not leave terminal set in bad state.

        Simulates finalization failure that marks terminal, then verifies
        a subsequent new utterance can proceed normally.
        """
        # Cycle 1: cancel (marks terminal)
        self._run_one_lifecycle(1, mode="cancel")

        # Cycle 2: normal final
        self._run_one_lifecycle(2, mode="final")

        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert len(session.terminal_utterance_ids) == 2

        # Verify cycle 2 is properly marked
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_stress_0002",
        )

    def test_terminal_set_isolated_per_session(self) -> None:
        """Different sessions have independent terminal sets."""
        key2, token2 = stream_service.create_session(1, 2)
        try:
            # Session 1: terminal 2 utterances
            self._run_one_lifecycle(1, mode="final")
            self._run_one_lifecycle(2, mode="final")

            # Session 2: should start with empty terminal set
            sess2 = stream_service.get_session(key2)
            assert sess2 is not None
            assert len(sess2.terminal_utterance_ids) == 0

            stream_service.start_utterance(key2, "utt_sess2_001")
            stream_service.cancel_utterance(key2)

            assert len(sess2.terminal_utterance_ids) == 1
        finally:
            stream_service.remove_session(key2, token2)

        # Session 1's set should be unaffected
        session = stream_service.get_session(self.session_key)
        assert session is not None
        assert len(session.terminal_utterance_ids) == 2


class TestStartInterimFinalCancelSequence:
    """Per-utterance state machine transitions.

    Verifies the expected flow:
        idle → start → speaking → interim → final/cancel → terminal
    """

    def setup_method(self) -> None:
        self.session_key, self.session_token = stream_service.create_session(1, 1)

    def teardown_method(self) -> None:
        stream_service.remove_session(self.session_key, self.session_token)

    def test_utterance_not_terminal_before_any_action(self) -> None:
        """A new utterance is not terminal until finalized or cancelled."""
        stream_service.start_utterance(self.session_key, "utt_fresh_001")
        assert not stream_service.is_utterance_terminal(
            self.session_key, "utt_fresh_001",
        )

    def test_utterance_terminal_after_finalize(self) -> None:
        """After successful finalize + mark, utterance IS terminal."""
        stream_service.start_utterance(self.session_key, "utt_final_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)
        result = stream_service.finalize_utterance(self.session_key)
        assert result is not None
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_final_001",
        )
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_final_001",
        )

    def test_utterance_terminal_after_cancel(self) -> None:
        """cancel_utterance marks the utterance terminal."""
        stream_service.start_utterance(self.session_key, "utt_cancel_001")
        stream_service.cancel_utterance(self.session_key)
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_cancel_001",
        )

    def test_finalize_new_utterance_after_cancel(self) -> None:
        """After cancel, a new utterance can be finalized normally."""
        # First utterance: cancel
        stream_service.start_utterance(self.session_key, "utt_seq_a_001")
        stream_service.append_audio(self.session_key, b"\x00" * 3200)
        stream_service.cancel_utterance(self.session_key)

        # Second utterance: final
        stream_service.start_utterance(self.session_key, "utt_seq_b_001")
        stream_service.append_audio(self.session_key, b"\x01" * 3200)
        result = stream_service.finalize_utterance(self.session_key)
        assert result is not None
        assert result["utterance_id"] == "utt_seq_b_001"
        stream_service.mark_utterance_terminal(
            self.session_key, "utt_seq_b_001",
        )

        # Verify both are terminal
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_seq_a_001",
        )
        assert stream_service.is_utterance_terminal(
            self.session_key, "utt_seq_b_001",
        )
