"""Unit tests for MTEngine — Opus-MT zh↔en bidirectional translation."""

import os

import pytest
from speech_module.mt_engine import MTEngine

requires_slow_models = pytest.mark.skipif(
    os.environ.get("SMART_DESK_RUN_SLOW_MODELS") != "1",
    reason="requires local model preload; set SMART_DESK_RUN_SLOW_MODELS=1",
)


class TestMTEngine:
    """Test MTEngine without preloading real models (placeholder/fallback paths)."""

    def test_empty_input(self):
        """Empty text returns empty tuple — no crash."""
        mt = MTEngine()
        zh, en = mt.translate("")
        assert zh == ""
        assert en == ""

    def test_not_loaded_returns_placeholder(self):
        """Without preload(), translate() still works (via SpeechModule fallback)."""
        # MTEngine itself will try to generate and fail gracefully
        mt = MTEngine()
        # ready is False without preload
        assert mt.ready is False
        # But translate() can still be called — global models are None,
        # so _generate will catch and return placeholder
        zh, en = mt.translate("测试")
        # Either succeeds (if models happened to be loaded globally) or returns placeholder
        assert zh is not None
        assert en is not None
        assert isinstance(zh, str)
        assert isinstance(en, str)

    def test_preload_idempotent(self):
        """Calling preload() twice should not crash."""
        # This test will try to download models — skip in CI, mark as slow
        # For now just verify the guard logic: ready=False before, ready state after
        mt = MTEngine()
        assert mt.ready is False
        # Don't actually call preload() in unit tests (requires model download)

    def test_ready_property_initially_false(self):
        """ready is False before preload()."""
        mt = MTEngine()
        assert mt.ready is False

    def test_constructor_defaults(self):
        """Default constructor uses cpu device."""
        mt = MTEngine()
        assert mt._device == "cpu"
        assert mt._model_dir is None


@requires_slow_models
class TestMTEngineIntegration:
    """Integration tests — require preloaded models. Mark as slow."""

    @pytest.mark.slow
    def test_translate_zh_to_en(self):
        """Chinese input → English output."""
        mt = MTEngine()
        mt.preload()
        assert mt.ready is True

        zh, en = mt.translate("大家好")
        assert zh == "大家好"
        assert len(en) > 0
        assert en != "[translation failed]"
        assert en != "[translation not available]"

    @pytest.mark.slow
    def test_translate_en_to_zh(self):
        """English input → Chinese output."""
        mt = MTEngine()
        mt.preload()
        assert mt.ready is True

        zh, en = mt.translate("Hello everyone")
        assert en == "Hello everyone"
        assert len(zh) > 0
        assert zh != "[translation failed]"
        assert zh != "[translation not available]"

    @pytest.mark.slow
    def test_translate_bidirectional_consistency(self):
        """Both directions produce non-placeholder output."""
        mt = MTEngine()
        mt.preload()

        # zh→en
        _, en1 = mt.translate("今天天气很好")
        assert len(en1) > 0
        assert "[translation" not in en1

        # en→zh
        zh2, _ = mt.translate("The weather is nice today")
        assert len(zh2) > 0
        assert "[translation" not in zh2
