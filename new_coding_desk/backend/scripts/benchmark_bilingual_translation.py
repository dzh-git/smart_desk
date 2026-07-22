"""Warm-model latency smoke test for bilingual final ASR plus translation."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.translation_model_service import NOT_AVAILABLE, TranslationModelService
from backend.speech_module.audio_utils import load_audio
from backend.speech_module.speech_module import SpeechModule


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark bilingual sentence finalization")
    parser.add_argument("--iterations", type=int, default=10, help="iterations per language")
    parser.add_argument("--max-seconds", type=float, default=3.0)
    args = parser.parse_args()
    os.environ.setdefault("ENABLE_TRANSLATION_MODEL", "true")

    speech = SpeechModule()
    speech.preload()
    if not speech.ready:
        raise RuntimeError(f"Speech models failed to load: {speech.status}")
    translation = TranslationModelService.get_instance()
    if not translation.load_all():
        raise RuntimeError(f"Translation models failed to load: {translation.get_status()}")

    examples = {
        "zh": PROJECT_ROOT / "models" / "SenseVoiceSmall" / "example" / "zh.mp3",
        "en": PROJECT_ROOT / "models" / "SenseVoiceSmall" / "example" / "en.mp3",
    }
    audio = {lang: load_audio(str(path))[0] for lang, path in examples.items()}
    timings: list[float] = []
    recognized: dict[str, int] = {"zh": 0, "en": 0}
    for index in range(args.iterations * 2):
        expected = "zh" if index % 2 == 0 else "en"
        started = time.monotonic()
        result = speech.transcribe_array_with_language(audio[expected])
        target = "en" if result.source_lang == "zh" else "zh"
        translated = translation.translate(result.text, result.source_lang, target)
        timings.append(time.monotonic() - started)
        recognized[result.source_lang] += 1
        if translated == NOT_AVAILABLE:
            raise RuntimeError(f"Translation unavailable for {result.source_lang}->{target}")

    sorted_timings = sorted(timings)
    p95_index = max(0, min(len(sorted_timings) - 1, int(len(sorted_timings) * 0.95) - 1))
    report = {
        "count": len(timings),
        "recognized": recognized,
        "max_ms": round(max(timings) * 1000),
        "p95_ms": round(sorted_timings[p95_index] * 1000),
        "mean_ms": round(statistics.mean(timings) * 1000),
        "target_ms": round(args.max_seconds * 1000),
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if max(timings) <= args.max_seconds else 1


if __name__ == "__main__":
    raise SystemExit(main())
