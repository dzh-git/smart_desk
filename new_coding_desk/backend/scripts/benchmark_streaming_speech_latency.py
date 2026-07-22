"""Benchmark the production speech stream service with real-time PCM replay.

This benchmark intentionally bypasses microphone capture and browser rendering.
It feeds 100 ms PCM frames through the same bounded ingress queue and
``SpeechStreamService.process_pcm_frame`` path used by the speech WebSocket.
Sentence-level OPUS-MT translation runs concurrently to expose CPU contention.
No FastAPI lifespan, hardware gateway, Arduino, or Display Agent is started.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import statistics
import sys
import threading
import time
import wave
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("ENABLE_TRANSLATION_MODEL", "true")

from backend.events import event_bus
from backend.services.interim_translation_service import sentence_translation_service
from backend.services.speech_stream_service import (
    VAD_SILENCE_THRESHOLD_RMS,
    SpeechStreamService,
)
from backend.services.translation_model_service import TranslationModelService
from backend.websocket.speech_ws import _publish_completed_sentences


FRAME_SECONDS = 0.1
FRAME_SAMPLES = 1_600
FRAME_BYTES = FRAME_SAMPLES * 2
QUEUE_CAPACITY = 50
CHECKPOINT_SECONDS = (30, 60, 120, 180, 300)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 2)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def _distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "count": len(values),
        "mean_ms": round(statistics.fmean(values), 2) if values else None,
        "p50_ms": _percentile(values, 50),
        "p95_ms": _percentile(values, 95),
        "p99_ms": _percentile(values, 99),
        "max_ms": round(max(values), 2) if values else None,
    }


@dataclass
class TranslationCollector:
    pending_at: dict[str, float] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def handler(self, event: Any) -> None:
        payload = dict(event.payload)
        sentence_id = str(payload.get("sentence_id") or "")
        if not sentence_id:
            return
        now = time.perf_counter()
        status = str(payload.get("translation_status") or "")
        with self.lock:
            if status == "pending":
                self.pending_at[sentence_id] = now
                return
            started = self.pending_at.get(sentence_id)
            self.results.append({
                "utterance_id": str(payload.get("utterance_id") or ""),
                "sentence_id": sentence_id,
                "status": status,
                "latency_ms": round((now - started) * 1000, 2) if started else None,
                "source_text_length": len(str(payload.get("source_text") or "")),
                "translated_text_length": len(str(payload.get("translated_text") or "")),
            })

    def results_for(self, utterance_ids: set[str]) -> list[dict[str, Any]]:
        with self.lock:
            return [item for item in self.results if item["utterance_id"] in utterance_ids]


@dataclass(frozen=True)
class QueuedFrame:
    index: int
    pcm: bytes
    enqueued_at: float
    audio_offset_seconds: float


def _load_pcm_frames(path: Path) -> tuple[list[bytes], float]:
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
        ):
            raise RuntimeError(f"Expected PCM16 mono 16 kHz WAV: {path}")
        frame_count = source.getnframes()
        frames: list[bytes] = []
        while True:
            pcm = source.readframes(FRAME_SAMPLES)
            if not pcm:
                break
            if len(pcm) < FRAME_BYTES:
                pcm += b"\x00" * (FRAME_BYTES - len(pcm))
            frames.append(pcm)
    return frames, frame_count / 16_000.0


def _voice_onset_seconds(frames: list[bytes]) -> float | None:
    for index, pcm in enumerate(frames):
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
        if rms >= VAD_SILENCE_THRESHOLD_RMS:
            return round(index * FRAME_SECONDS, 3)
    return None


def _checkpoint_rows(frame_metrics: list[dict[str, float]], duration: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for checkpoint in CHECKPOINT_SECONDS:
        if checkpoint > duration + 0.5:
            continue
        eligible = [
            item for item in frame_metrics
            if item["audio_offset_seconds"] <= checkpoint + 1e-6
        ]
        if not eligible:
            continue
        item = eligible[-1]
        window_start = max(0.0, checkpoint - 10.0)
        window = [
            metric for metric in eligible
            if metric["audio_offset_seconds"] >= window_start
        ]
        rows.append({
            "audio_second": checkpoint,
            "completion_lag_ms": round(item["completion_lag_ms"], 2),
            "queue_wait_ms": round(item["queue_wait_ms"], 2),
            "queue_backlog_ms": int(item["queue_backlog_ms"]),
            "window_processing_p95_ms": _percentile(
                [metric["processing_ms"] for metric in window], 95,
            ),
            "window_completion_lag_p95_ms": _percentile(
                [metric["completion_lag_ms"] for metric in window], 95,
            ),
        })
    return rows


async def _run_one(
    *,
    service: SpeechStreamService,
    collector: TranslationCollector,
    dataset_root: Path,
    session_spec: dict[str, Any],
    language_mode: str,
    run_index: int,
) -> dict[str, Any]:
    audio_path = dataset_root / session_spec["audio"]
    pcm_frames, audio_duration = _load_pcm_frames(audio_path)
    voice_onset_seconds = _voice_onset_seconds(pcm_frames)
    meeting_id = 90_000 + run_index
    seat_id = 1
    session_key, session_token = service.create_session(meeting_id, seat_id)
    utterance_id = service.generate_utterance_id(meeting_id, seat_id)
    service.start_utterance(
        session_key,
        utterance_id,
        language_mode=language_mode,
    )
    utterance_ids = {utterance_id}
    queue: asyncio.Queue[QueuedFrame | None] = asyncio.Queue(maxsize=QUEUE_CAPACITY)
    frame_metrics: list[dict[str, float]] = []
    interim_updates = 0
    first_interim_ms: float | None = None
    first_detected_language_ms: float | None = None
    rollovers: list[dict[str, Any]] = []
    errors: list[str] = []
    last_source_text = ""
    last_detected_language = "unknown"
    last_recognition_engine = "unknown"
    started = time.perf_counter()
    loop = asyncio.get_running_loop()

    async def producer() -> None:
        for index, pcm in enumerate(pcm_frames):
            target = started + (index + 1) * FRAME_SECONDS
            while True:
                delay = target - time.perf_counter()
                if delay <= 0:
                    break
                await asyncio.sleep(delay)
            await queue.put(QueuedFrame(
                index=index,
                pcm=pcm,
                enqueued_at=time.perf_counter(),
                audio_offset_seconds=min((index + 1) * FRAME_SECONDS, audio_duration),
            ))
            service.update_pcm_queue(session_key, queue.qsize())
        await queue.put(None)
        service.update_pcm_queue(session_key, queue.qsize() - 1)

    async def consumer() -> None:
        nonlocal interim_updates, first_interim_ms, first_detected_language_ms
        nonlocal last_source_text, last_detected_language, last_recognition_engine
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                service.update_pcm_queue(session_key, 0)
                return
            processing_started = time.perf_counter()
            queue_wait_ms = (processing_started - item.enqueued_at) * 1000
            service.update_pcm_queue(session_key, queue.qsize())
            try:
                result = await loop.run_in_executor(
                    None,
                    service.process_pcm_frame,
                    session_key,
                    item.pcm,
                )
            except Exception as exc:  # keep the remaining timeline observable
                errors.append(f"frame_{item.index}: {type(exc).__name__}: {exc}")
                queue.task_done()
                continue
            completed_at = time.perf_counter()
            processing_ms = (completed_at - processing_started) * 1000
            current_session = service.get_session(session_key)
            if current_session is not None:
                current_session.processed_frames += 1
                current_session.last_processing_ms = round(processing_ms)
                current_session.peak_processing_ms = max(
                    current_session.peak_processing_ms,
                    round(processing_ms),
                )
            queue_backlog_ms = queue.qsize() * round(FRAME_SECONDS * 1000)
            frame_metrics.append({
                "audio_offset_seconds": item.audio_offset_seconds,
                "processing_ms": processing_ms,
                "queue_wait_ms": queue_wait_ms,
                "queue_backlog_ms": float(queue_backlog_ms),
                "completion_lag_ms": (
                    completed_at - (started + item.audio_offset_seconds)
                ) * 1000,
            })
            source_text = str(result.get("source_text") or "").strip()
            if source_text:
                last_source_text = source_text
                interim_updates += 1
                if first_interim_ms is None:
                    first_interim_ms = (completed_at - started) * 1000
            detected = str(result.get("detected_language") or "unknown")
            engine = str(result.get("recognition_engine") or "unknown")
            if detected in {"zh", "en"}:
                last_detected_language = detected
            if engine != "unknown":
                last_recognition_engine = engine
            if detected in {"zh", "en"} and first_detected_language_ms is None:
                first_detected_language_ms = (completed_at - started) * 1000
            completed_sentences = list(result.get("completed_sentences") or [])
            if completed_sentences:
                _publish_completed_sentences(
                    meeting_id=meeting_id,
                    seat_id=seat_id,
                    utterance_id=str(result["utterance_id"]),
                    revision=int(result["revision"]),
                    completed_sentences=completed_sentences,
                    source_lang=detected,
                )
            if result.get("vad_should_finalize"):
                boundary_reason = str(result.get("boundary_reason") or "vad_boundary")
                finalized = service.snapshot_auto_finalization(
                    session_key,
                    source_text,
                    boundary_reason,
                )
                new_uid = service.prepare_next_utterance(
                    session_key,
                    meeting_id,
                    seat_id,
                    continuous_rollover=bool(
                        finalized and finalized.get("continuous_rollover")
                    ),
                )
                if new_uid:
                    utterance_ids.add(new_uid)
                rollovers.append({
                    "audio_offset_seconds": round(item.audio_offset_seconds, 2),
                    "reason": boundary_reason,
                    "old_utterance_id": (
                        str(finalized.get("utterance_id")) if finalized else None
                    ),
                    "new_utterance_id": new_uid,
                })
            queue.task_done()

    await asyncio.gather(producer(), consumer())
    await queue.join()
    finalization_started = time.perf_counter()
    finalized = await loop.run_in_executor(None, service.finalize_utterance, session_key)
    finalization_ms = (time.perf_counter() - finalization_started) * 1000
    if finalized:
        final_uid = str(finalized.get("utterance_id") or "")
        utterance_ids.add(final_uid)
        final_text = str(finalized.get("source_text") or last_source_text).strip()
        sentence_result = service.complete_active_sentence(
            session_key,
            final_text,
            "end_hint",
        )
        current_session = service.get_session(session_key)
        _publish_completed_sentences(
            meeting_id=meeting_id,
            seat_id=seat_id,
            utterance_id=final_uid,
            revision=current_session.revision if current_session else 0,
            completed_sentences=list(sentence_result.get("completed_sentences") or []),
            source_lang=str(finalized.get("detected_language") or "unknown"),
        )
    translations_idle = await loop.run_in_executor(
        None,
        sentence_translation_service.wait_for_idle,
        15.0,
    )
    completed_wall = time.perf_counter()
    translation_results = collector.results_for(utterance_ids)
    translation_latencies = [
        float(item["latency_ms"])
        for item in translation_results
        if item.get("latency_ms") is not None
    ]
    service.remove_session(session_key, session_token)

    processing_values = [item["processing_ms"] for item in frame_metrics]
    queue_wait_values = [item["queue_wait_ms"] for item in frame_metrics]
    completion_lag_values = [item["completion_lag_ms"] for item in frame_metrics]
    backlog_values = [item["queue_backlog_ms"] for item in frame_metrics]
    detected_language = (
        str(finalized.get("detected_language") or "unknown")
        if finalized else last_detected_language
    )
    recognition_engine = (
        str(finalized.get("recognition_engine") or "unknown")
        if finalized else last_recognition_engine
    )
    return {
        "audio": session_spec["audio"],
        "language": session_spec["language"],
        "language_mode": language_mode,
        "audio_duration_seconds": round(audio_duration, 3),
        "wall_seconds_until_audio_drained": round(
            frame_metrics[-1]["audio_offset_seconds"]
            + frame_metrics[-1]["completion_lag_ms"] / 1000,
            3,
        ) if frame_metrics else None,
        "total_wall_seconds_including_translation_drain": round(
            completed_wall - started, 3,
        ),
        "end_of_audio_lag_ms": round(completion_lag_values[-1], 2)
        if completion_lag_values else None,
        "first_interim_ms": round(first_interim_ms, 2)
        if first_interim_ms is not None else None,
        "voice_onset_seconds": voice_onset_seconds,
        "first_interim_after_voice_ms": (
            round(first_interim_ms - voice_onset_seconds * 1000, 2)
            if first_interim_ms is not None and voice_onset_seconds is not None
            else None
        ),
        "first_detected_language_ms": round(first_detected_language_ms, 2)
        if first_detected_language_ms is not None else None,
        "detected_language": detected_language,
        "recognition_engine": recognition_engine,
        "interim_update_count": interim_updates,
        "frame_count": len(frame_metrics),
        "slower_than_realtime_frame_count": sum(
            value > 100.0 for value in processing_values
        ),
        "processing": _distribution(processing_values),
        "queue_wait": _distribution(queue_wait_values),
        "completion_lag": _distribution(completion_lag_values),
        "peak_audio_backlog_ms": round(max(backlog_values), 2)
        if backlog_values else None,
        "checkpoints": _checkpoint_rows(frame_metrics, audio_duration),
        "rollovers": rollovers,
        "finalization_ms": round(finalization_ms, 2),
        "translation": {
            "idle_after_timeout": translations_idle,
            "result_count": len(translation_results),
            "ok_count": sum(item["status"] == "ok" for item in translation_results),
            "unavailable_count": sum(
                item["status"] != "ok" for item in translation_results
            ),
            "latency": _distribution(translation_latencies),
        },
        "errors": errors,
    }


def _select_runs(manifest: dict[str, Any], suite: str) -> list[tuple[dict[str, Any], str]]:
    runs: list[tuple[dict[str, Any], str]] = []
    controlled = list(manifest.get("controlled_sessions") or [])
    long_sessions = list(manifest.get("long_stress_sessions") or [])
    if suite in {"smoke", "all"}:
        for language in ("zh", "en"):
            selected = next(item for item in controlled if item["language"] == language)
            runs.append((selected, language))
            runs.append((selected, "auto"))
    if suite in {"long", "all"}:
        for language in ("zh", "en"):
            selected = next(item for item in long_sessions if item["language"] == language)
            runs.append((selected, language))
    return runs


async def benchmark(dataset_root: Path, suite: str) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    manifest = json.loads((dataset_root / "manifest.json").read_text(encoding="utf-8"))
    service = SpeechStreamService()
    print("Preloading speech models...", flush=True)
    preload_started = time.perf_counter()
    service._get_speech_module()
    speech_preload_ms = round((time.perf_counter() - preload_started) * 1000, 2)
    print(f"Speech models ready in {speech_preload_ms:.0f} ms", flush=True)
    translation_model = TranslationModelService.get_instance()
    translation_started = time.perf_counter()
    translation_ready = translation_model.load_all()
    translation_preload_ms = round((time.perf_counter() - translation_started) * 1000, 2)
    print(
        f"Translation models ready={translation_ready} in "
        f"{translation_preload_ms:.0f} ms",
        flush=True,
    )

    collector = TranslationCollector()
    event_bus.subscribe("translation_sentence", collector.handler)
    results: list[dict[str, Any]] = []
    try:
        runs = _select_runs(manifest, suite)
        for index, (session_spec, language_mode) in enumerate(runs, 1):
            print(
                f"[{index}/{len(runs)}] {session_spec['audio']} mode={language_mode} "
                f"duration={session_spec['duration_seconds']:.1f}s",
                flush=True,
            )
            result = await _run_one(
                service=service,
                collector=collector,
                dataset_root=dataset_root,
                session_spec=session_spec,
                language_mode=language_mode,
                run_index=index,
            )
            results.append(result)
            print(
                "  first={first}ms end_lag={lag}ms backlog_max={backlog}ms "
                "proc_p95={p95}ms translation_p95={tp95}ms".format(
                    first=result["first_interim_ms"],
                    lag=result["end_of_audio_lag_ms"],
                    backlog=result["peak_audio_backlog_ms"],
                    p95=result["processing"]["p95_ms"],
                    tp95=result["translation"]["latency"]["p95_ms"],
                ),
                flush=True,
            )
    finally:
        event_bus.unsubscribe("translation_sentence", collector.handler)

    return {
        "report_type": "smartdesk-streaming-speech-latency",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_root),
        "suite": suite,
        "frame_duration_ms": round(FRAME_SECONDS * 1000),
        "queue_capacity_frames": QUEUE_CAPACITY,
        "speech_preload_ms": speech_preload_ms,
        "translation_preload_ms": translation_preload_ms,
        "translation_ready": translation_ready,
        "runs": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("working/speech_latency_dataset/fleurs_zh_en"),
    )
    parser.add_argument("--suite", choices=("smoke", "long", "all"), default="all")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("working/speech_latency_dataset/streaming_latency_report.json"),
    )
    args = parser.parse_args()
    report = asyncio.run(benchmark(args.dataset, args.suite))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Report written to {args.output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
