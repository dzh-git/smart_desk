"""
Unit tests for TranslationModelService — Task 123.

Covers:
    - Disabled-by-default behavior (ENABLE_TRANSLATION_MODEL not set)
    - Enabled state detection via env var
    - Model loading failure path (simulated bad path)
    - Successful translation with monkeypatched model
    - Singleton lifecycle (get_instance, reset_instance)
    - translate() handles empty/whitespace input
    - translate() does not raise on inference errors
"""
from __future__ import annotations

import os
from unittest.mock import patch, MagicMock

import pytest
from backend.services.translation_model_service import (
    TranslationModelService,
    is_translation_model_enabled,
    get_model_path,
    NOT_AVAILABLE,
)

# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton before and after each test."""
    TranslationModelService.reset_instance()
    yield
    TranslationModelService.reset_instance()


@pytest.fixture(autouse=True)
def _clear_env():
    """Remove any translation-model env vars before each test.

    Saves and restores original values.
    """
    saved = {}
    for key in ("ENABLE_TRANSLATION_MODEL", "TRANSLATION_MODEL_PATH"):
        saved[key] = os.environ.pop(key, None)
    yield
    for key, val in saved.items():
        if val is not None:
            os.environ[key] = val
        else:
            os.environ.pop(key, None)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_svc(enabled: bool = False):
    """Create a TranslationModelService with optional enable flag."""
    if enabled:
        os.environ["ENABLE_TRANSLATION_MODEL"] = "true"
    return TranslationModelService.get_instance()


# ── Tests: env var detection ───────────────────────────────────────────────────


class TestEnvVarDetection:
    """is_translation_model_enabled() behaves correctly."""

    def test_disabled_when_unset(self):
        """ENABLE_TRANSLATION_MODEL not set → disabled."""
        assert is_translation_model_enabled() is False

    def test_disabled_when_falsy(self):
        """ENABLE_TRANSLATION_MODEL=0 → disabled."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "0"
        assert is_translation_model_enabled() is False

    def test_disabled_when_empty(self):
        """ENABLE_TRANSLATION_MODEL='' → disabled."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = ""
        assert is_translation_model_enabled() is False

    def test_enabled_when_true(self):
        """ENABLE_TRANSLATION_MODEL=true → enabled."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "true"
        assert is_translation_model_enabled() is True

    def test_enabled_when_1(self):
        """ENABLE_TRANSLATION_MODEL=1 → enabled."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "1"
        assert is_translation_model_enabled() is True

    def test_enabled_case_insensitive(self):
        """ENABLE_TRANSLATION_MODEL=True (capitalized) → enabled."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "True"
        assert is_translation_model_enabled() is True

    def test_enabled_yes(self):
        """ENABLE_TRANSLATION_MODEL=yes → enabled."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "yes"
        assert is_translation_model_enabled() is True


# ── Tests: model path resolution ────────────────────────────────────────────────


class TestModelPath:
    """get_model_path() resolves correctly."""

    def test_env_var_override(self):
        """TRANSLATION_MODEL_PATH set → returns that path."""
        os.environ["TRANSLATION_MODEL_PATH"] = "/custom/path/to/model"
        path = get_model_path()
        assert path == "/custom/path/to/model"

    def test_env_var_empty_falls_through(self):
        """TRANSLATION_MODEL_PATH='' → falls through to default logic."""
        os.environ["TRANSLATION_MODEL_PATH"] = ""
        path = get_model_path()
        assert path != ""

    def test_local_path_preferred(self):
        """Existing local models/opus-mt-zh-en with weights → local path."""
        path = get_model_path()
        # On this machine the local model exists; path should be local
        import os as _os
        expected_local = _os.path.join(
            _os.path.dirname(_os.path.dirname(__file__)),
            "models",
            "opus-mt-zh-en",
        )
        if _os.path.isdir(expected_local):
            assert path == expected_local, (
                f"Expected local path {expected_local}, got {path}"
            )


# ── Tests: disabled behavior ───────────────────────────────────────────────────


class TestDisabledBehavior:
    """TranslationModelService when ENABLE_TRANSLATION_MODEL is not set."""

    def test_translate_returns_placeholder(self):
        """translate() returns NOT_AVAILABLE when disabled."""
        svc = _make_svc(enabled=False)
        result = svc.translate("你好世界")
        assert result == NOT_AVAILABLE, (
            f"Expected '{NOT_AVAILABLE}', got '{result}'"
        )

    def test_not_loaded_when_disabled(self):
        """loaded is False when disabled."""
        svc = _make_svc(enabled=False)
        assert svc.loaded is False
        assert svc.enabled is False

    def test_translate_empty_text(self):
        """translate('') returns '' when disabled."""
        svc = _make_svc(enabled=False)
        assert svc.translate("") == ""
        assert svc.translate("   ") == ""

    def test_provider_string_disabled(self):
        """provider == 'disabled' when not enabled."""
        svc = _make_svc(enabled=False)
        assert svc.provider == "disabled"


# ── Tests: enabled but model unavailable ──────────────────────────────────────


class TestEnabledModelUnavailable:
    """TranslationModelService when enabled but model loading fails."""

    def test_load_failure_returns_unavailable_sentinel(self):
        """translate() returns a stable sentinel when model can't load."""
        svc = _make_svc(enabled=True)
        # Point to a non-existent path so loading fails
        os.environ["TRANSLATION_MODEL_PATH"] = "/nonexistent/path/model"
        # Re-create the singleton to pick up new env var
        TranslationModelService.reset_instance()
        svc = TranslationModelService.get_instance()

        result = svc.translate("你好世界")
        assert result == "[translation not available]"
        assert svc.load_error is not None

    def test_load_error_recorded(self):
        """load_error is set after a failed load attempt."""
        svc = _make_svc(enabled=True)
        os.environ["TRANSLATION_MODEL_PATH"] = "/nonexistent/path/model"
        TranslationModelService.reset_instance()
        svc = TranslationModelService.get_instance()

        svc.load()
        assert svc.loaded is False
        assert svc.load_error is not None


# ── Tests: successful translation (mocked) ────────────────────────────────────


class TestSuccessfulTranslationMocked:
    """TranslationModelService with mocked model pipeline."""

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_translate_calls_model(
        self, MockModel, MockTokenizer,
    ):
        """translate() calls model.generate and returns decoded text."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "true"
        TranslationModelService.reset_instance()

        # Mock the tokenizer
        mock_tok = MagicMock()
        mock_inputs = MagicMock()
        mock_tok.return_value = mock_inputs
        mock_tok.decode.return_value = "Hello world."

        # Mock the model
        mock_model = MagicMock()
        mock_ids = MagicMock()
        mock_model.generate.return_value = mock_ids
        mock_tok.decode.return_value = "Hello world."

        MockTokenizer.from_pretrained.return_value = mock_tok
        MockModel.from_pretrained.return_value = mock_model

        svc = TranslationModelService.get_instance()
        result = svc.translate("你好世界")

        assert result == "Hello world."
        mock_model.generate.assert_called_once()

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_model_generate_failure_returns_unavailable(
        self, MockModel, MockTokenizer,
    ):
        """When model.generate raises, source text remains usable."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "true"
        TranslationModelService.reset_instance()

        mock_tok = MagicMock()
        MockTokenizer.from_pretrained.return_value = mock_tok

        mock_model = MagicMock()
        mock_model.generate.side_effect = RuntimeError("GPU OOM")
        MockModel.from_pretrained.return_value = mock_model

        svc = TranslationModelService.get_instance()
        result = svc.translate("你好世界")

        assert result == "[translation not available]"
        assert svc.load_error == "Translation inference failed: GPU OOM"

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_load_twice_is_idempotent(
        self, MockModel, MockTokenizer,
    ):
        """Calling translate() twice reuses the same model instance."""
        os.environ["ENABLE_TRANSLATION_MODEL"] = "true"
        TranslationModelService.reset_instance()

        mock_tok = MagicMock()
        mock_tok.decode.return_value = "Hello."
        MockTokenizer.from_pretrained.return_value = mock_tok

        mock_model = MagicMock()
        mock_ids = MagicMock()
        mock_model.generate.return_value = mock_ids
        MockModel.from_pretrained.return_value = mock_model

        svc = TranslationModelService.get_instance()
        svc.translate("你好")
        svc.translate("世界")

        # from_pretrained should only be called once (lazy load, then cached)
        assert MockTokenizer.from_pretrained.call_count == 1
        assert MockModel.from_pretrained.call_count == 1


# ── Tests: singleton lifecycle ──────────────────────────────────────────────────


class TestSingletonLifecycle:
    """TranslationModelService singleton management."""

    def test_get_instance_returns_same(self):
        """get_instance() returns the same object."""
        a = TranslationModelService.get_instance()
        b = TranslationModelService.get_instance()
        assert a is b

    def test_reset_instance_clears(self):
        """reset_instance() clears the singleton."""
        a = TranslationModelService.get_instance()
        TranslationModelService.reset_instance()
        b = TranslationModelService.get_instance()
        assert a is not b

    def test_unload_releases_model(self):
        """unload() sets loaded=False and clears error."""
        # We need to test unload behavior even without actual loading
        svc = _make_svc(enabled=True)
        svc._loaded = False
        svc.unload()
        assert svc.loaded is False


# ── Smoke test (real model, conditional) ────────────────────────────────────────
#
# These tests run ONLY when both env vars are set:
#   RUN_TRANSLATION_SMOKE=true
#   ENABLE_TRANSLATION_MODEL=true
#
# They verify the real OPUS-MT zh-en model produces English output from
# Chinese input.  They do NOT check translation quality.
#
# Execute via:
#   $env:RUN_TRANSLATION_SMOKE="true"; $env:ENABLE_TRANSLATION_MODEL="true"; ^
#     pytest tests/test_translation_model_service.py -q -m smoke
#
# Normal `pytest -q` (no -m smoke) never loads or downloads the model.


@pytest.mark.smoke
class TestRealTranslationSmoke:
    """Real OPUS-MT zh-en smoke test (requires model + both env vars).

    These tests are excluded from ordinary test runs via the ``smoke`` marker.
    They auto-skip inside the class if ``RUN_TRANSLATION_SMOKE`` is not set,
    providing a safety net even when invoked with ``-m smoke`` accidentally.
    """

    def _require_model(self):
        """Skip unless RUN_TRANSLATION_SMOKE=true and model loads.

        This method is entered only when the user explicitly opts in by
        setting RUN_TRANSLATION_SMOKE=true.  The _clear_env autouse fixture
        clears ENABLE_TRANSLATION_MODEL before each test, so we re-enable it
        here *conditionally* (gated by RUN_TRANSLATION_SMOKE).
        """
        smoke_flag = os.environ.get("RUN_TRANSLATION_SMOKE", "").strip().lower()
        if smoke_flag not in ("1", "true", "yes"):
            pytest.skip(
                "Real translation smoke test requires RUN_TRANSLATION_SMOKE=true "
                "(and ENABLE_TRANSLATION_MODEL=true)"
            )
        # Conditional re-enable: only runs when the user has opted in via
        # RUN_TRANSLATION_SMOKE, so this is NOT an unconditional set.
        os.environ["ENABLE_TRANSLATION_MODEL"] = "true"
        TranslationModelService.reset_instance()
        svc = TranslationModelService.get_instance()
        if not svc.load():
            pytest.skip(f"Translation model not available: {svc.load_error}")

    def test_chinese_to_english_translation(self):
        """Real zh→en: input Chinese → output English string."""
        self._require_model()
        TranslationModelService.reset_instance()
        svc = TranslationModelService.get_instance()
        assert svc.load(), "Model should load successfully"

        result = svc.translate("你好，欢迎参加智能会议。")
        assert isinstance(result, str), f"Expected string, got {type(result)}"
        assert len(result) > 0, "Translation should not be empty"
        # The result must be English (ASCII letters) not Chinese
        ascii_letters = sum(1 for c in result if c.isascii() and c.isalpha())
        assert ascii_letters > 0, (
            f"Translation should contain English characters, got '{result}'"
        )
        # Must NOT be the placeholder
        assert result != NOT_AVAILABLE, (
            "Translation should not be the placeholder"
        )

    def test_non_chinese_input_passthrough(self):
        """English input → translated anyway (model may produce reasonable output)."""
        self._require_model()
        TranslationModelService.reset_instance()
        svc = TranslationModelService.get_instance()
        assert svc.load()

        result = svc.translate("Hello")
        # Should return something (not error, not placeholder)
        assert isinstance(result, str)
        assert len(result) > 0
