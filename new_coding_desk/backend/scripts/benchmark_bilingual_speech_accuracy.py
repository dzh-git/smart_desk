"""Evaluate final bilingual ASR and translation on the prepared FLEURS subset."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("ENABLE_TRANSLATION_MODEL", "true")

from backend.services.translation_model_service import NOT_AVAILABLE, TranslationModelService
from backend.scripts.prepare_speech_latency_stress_sessions import _normalize_active_rms
from backend.speech_module.audio_utils import load_audio
from backend.speech_module.speech_module import SpeechModule
from backend.speech_module.text_utils import compute_cer, compute_wer, normalize_en, normalize_zh


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _latency(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 2) if values else None,
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "max_ms": round(max(values), 2) if values else None,
    }


def benchmark(dataset_root: Path, *, normalize_audio: bool = False) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    utterances = json.loads(
        (dataset_root / "utterances.json").read_text(encoding="utf-8")
    )
    speech = SpeechModule()
    print("Preloading speech models...", flush=True)
    speech.preload()
    if not speech.ready:
        raise RuntimeError(f"Speech models failed to preload: {speech.status}")
    translation = TranslationModelService.get_instance()
    if not translation.load_all():
        raise RuntimeError(f"Translation models failed to preload: {translation.get_status()}")

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(utterances, 1):
        language = str(item["language"])
        audio_path = dataset_root / "audio" / language / item["filename"]
        audio, sample_rate = load_audio(str(audio_path))
        if normalize_audio:
            audio, _ = _normalize_active_rms(audio)
        asr_started = time.perf_counter()
        recognition = speech.transcribe_array_with_language(audio, sample_rate)
        asr_ms = (time.perf_counter() - asr_started) * 1000
        target_language = "en" if language == "zh" else "zh"
        translation_started = time.perf_counter()
        translated = translation.translate(
            recognition.text,
            recognition.source_lang,
            target_language,
            quality="final",
        )
        translation_ms = (time.perf_counter() - translation_started) * 1000
        reference = str(item["normalized_transcript"])
        if language == "zh":
            reference_normalized = normalize_zh(reference)
            hypothesis_normalized = normalize_zh(recognition.text)
            error = compute_cer(reference_normalized, hypothesis_normalized)
            error_rate = float(error["cer"])
            metric = "cer"
        else:
            reference_normalized = normalize_en(reference)
            hypothesis_normalized = normalize_en(recognition.text)
            error = compute_wer(reference_normalized, hypothesis_normalized)
            error_rate = float(error["wer"])
            metric = "wer"
        row = {
            "audio": audio_path.relative_to(dataset_root).as_posix(),
            "expected_language": language,
            "detected_language": recognition.source_lang,
            "recognition_model": recognition.recognition_model,
            "reference": str(item["transcript"]),
            "recognized_text": recognition.text,
            "metric": metric,
            "error_rate": round(error_rate, 4),
            "error_counts": error,
            "asr_ms": round(asr_ms, 2),
            "translation_status": (
                "ok" if translated and translated != NOT_AVAILABLE else "unavailable"
            ),
            "translated_text": translated if translated != NOT_AVAILABLE else "",
            "translation_ms": round(translation_ms, 2),
        }
        rows.append(row)
        print(
            f"[{index}/{len(utterances)}] {language} detected={recognition.source_lang} "
            f"{metric}={error_rate:.3f} asr={asr_ms:.0f}ms "
            f"translation={row['translation_status']} {translation_ms:.0f}ms",
            flush=True,
        )

    summaries: dict[str, Any] = {}
    for language in ("zh", "en"):
        selected = [row for row in rows if row["expected_language"] == language]
        errors = [row["error_counts"] for row in selected]
        total_reference = sum(int(item["N"]) for item in errors)
        total_edits = sum(
            int(item["S"]) + int(item["D"]) + int(item["I"])
            for item in errors
        )
        summaries[language] = {
            "count": len(selected),
            "language_detection_accuracy": round(
                sum(row["detected_language"] == language for row in selected)
                / max(1, len(selected)),
                4,
            ),
            "metric": "cer" if language == "zh" else "wer",
            "micro_error_rate": round(total_edits / max(1, total_reference), 4),
            "mean_utterance_error_rate": round(
                statistics.fmean(row["error_rate"] for row in selected), 4,
            ),
            "asr_latency": _latency([float(row["asr_ms"]) for row in selected]),
            "translation_latency": _latency(
                [float(row["translation_ms"]) for row in selected]
            ),
            "translation_ok": sum(
                row["translation_status"] == "ok" for row in selected
            ),
        }
    return {
        "report_type": "smartdesk-bilingual-speech-accuracy",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_root),
        "input_normalization": "active_rms_-23_dbfs" if normalize_audio else "original",
        "summary": summaries,
        "utterances": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("working/speech_latency_dataset/fleurs_zh_en"),
    )
    parser.add_argument("--normalize-audio", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("working/speech_latency_dataset/bilingual_accuracy_report.json"),
    )
    args = parser.parse_args()
    report = benchmark(args.dataset, normalize_audio=args.normalize_audio)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Report written to {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
