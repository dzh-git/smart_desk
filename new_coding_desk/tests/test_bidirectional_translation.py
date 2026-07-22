from __future__ import annotations

from unittest.mock import MagicMock, patch
from pathlib import Path

from backend.services.translation_model_service import TranslationModelService, get_model_path


def _local_test_dir(name: str) -> Path:
    path = Path(".pytest_tmp") / "bilingual_models" / name
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def test_direction_specific_paths_override_legacy(monkeypatch) -> None:
    zh_en = _local_test_dir("path-zh-en")
    en_zh = _local_test_dir("path-en-zh")
    monkeypatch.setenv("TRANSLATION_MODEL_PATH", "legacy")
    monkeypatch.setenv("TRANSLATION_ZH_EN_MODEL_PATH", str(zh_en))
    monkeypatch.setenv("TRANSLATION_EN_ZH_MODEL_PATH", str(en_zh))
    assert get_model_path("zh", "en") == str(zh_en)
    assert get_model_path("en", "zh") == str(en_zh)


@patch("transformers.AutoTokenizer")
@patch("transformers.AutoModelForSeq2SeqLM")
def test_both_directions_load_once_and_route_independently(
    mock_model_cls, mock_tokenizer_cls, monkeypatch,
) -> None:
    zh_en = _local_test_dir("load-zh-en")
    en_zh = _local_test_dir("load-en-zh")
    monkeypatch.setenv("ENABLE_TRANSLATION_MODEL", "true")
    monkeypatch.setenv("TRANSLATION_ZH_EN_MODEL_PATH", str(zh_en))
    monkeypatch.setenv("TRANSLATION_EN_ZH_MODEL_PATH", str(en_zh))
    TranslationModelService.reset_instance()

    zh_tokenizer = MagicMock()
    zh_tokenizer.decode.return_value = "Hello."
    en_tokenizer = MagicMock()
    en_tokenizer.decode.return_value = "你好。"
    mock_tokenizer_cls.from_pretrained.side_effect = [zh_tokenizer, en_tokenizer]
    mock_model_cls.from_pretrained.side_effect = [MagicMock(), MagicMock()]

    service = TranslationModelService.get_instance()
    assert service.translate("你好", "zh", "en") == "Hello."
    assert service.translate("Hello", "en", "zh") == "你好。"
    assert service.translate("世界", "zh", "en") == "Hello."
    assert mock_tokenizer_cls.from_pretrained.call_count == 2
    assert service.get_status()["zh_en"]["status"] == "loaded"
    assert service.get_status()["en_zh"]["status"] == "loaded"
    TranslationModelService.reset_instance()
