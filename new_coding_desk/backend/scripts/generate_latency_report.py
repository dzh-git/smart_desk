"""
Generate speech-first-token-latency-report.json — first-token latency analysis.

Task 128A (rework): supports merging frontend + backend trace data.
Task 128E: supports --backend-trace (file), --output, missing_fields.

Usage:
    # Backend-only (no frontend trace available)
    python -m backend.scripts.generate_latency_report

    # With frontend trace + backend trace files
    python -m backend.scripts.generate_latency_report \
        --frontend-trace path/to/speech-trace.json \
        --backend-trace path/to/backend-trace.json \
        --output working/speech-browser-merged-latency-report.json

Frontend trace export (in browser DevTools):
    window.__SMARTDESK_SPEECH_TRACE__.downloadTraceFile();

Backend trace export (after recording with SMART_DESK_ENABLE_SPEECH_TRACE=true):
    python -c "
    from backend.websocket.speech_trace import export_trace_to_file;
    r = export_trace_to_file('working/backend-trace.json');
    print(r)
    "
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "working"
    / "speech-browser-merged-latency-report.json"
)


# ── Category constants ──────────────────────────────────────────────────────

CAT_FRONTEND = "frontend-only"
CAT_BACKEND = "backend-only"
CAT_CROSS_BOUNDARY = "cross-boundary"
CAT_END_TO_END = "end-to-end"
CAT_UNAVAILABLE = "unavailable"

# ── All known trace events (used for missing_fields check) ───────────────────


def _all_trace_event_names() -> list[str]:
    """Return the canonical list of all trace point event names."""
    return [tp["name"] for tp in _trace_points()]


# ── Trace point definitions ──────────────────────────────────────────────────


def _trace_points() -> list[dict]:
    """Return the canonical list of trace points and their locations."""
    return [
        # ── Frontend ──────────────────────────────────────────────────────
        {
            "name": "start_clicked_at",
            "location": "useSpeechStream.ts:start()",
            "description": "User clicked the Start button",
            "side": "frontend",
        },
        {
            "name": "microphone_start_requested_at",
            "location": "useSpeechStream.ts:start() before mic.start()",
            "description": "Microphone capture start requested",
            "side": "frontend",
        },
        {
            "name": "microphone_started_at",
            "location": "microphone.ts:start() after AudioContext connected",
            "description": "Microphone AudioContext graph fully set up",
            "side": "frontend",
        },
        {
            "name": "speech_ws_connect_start_at",
            "location": "speechWsClient.ts:connect()",
            "description": "WebSocket connection initiation started",
            "side": "frontend",
        },
        {
            "name": "ws_connected_at",
            "location": "speechWsClient.ts:ws.onopen()",
            "description": "WebSocket connection established",
            "side": "frontend",
        },
        {
            "name": "ws_started_received_at",
            "location": "speechWsClient.ts:ws.onmessage type='started'",
            "description": "Backend acknowledged start, sent utterance_id",
            "side": "frontend",
        },
        {
            "name": "frontend_pcm_created_at",
            "location": "microphone.ts:processAudioInput()",
            "description": "A 100ms PCM16 frame was created from mic input",
            "side": "frontend",
        },
        {
            "name": "frontend_pcm_sent_at",
            "location": "useSpeechStream.ts:onFrame() callback",
            "description": "PCM frame sent via WebSocket sendAudio()",
            "side": "frontend",
        },
        {
            "name": "frontend_interim_received_at",
            "location": "useSeatData.ts:handleWSEvent() translation_interim",
            "description": "Frontend WebSocket received translation_interim event",
            "side": "frontend",
        },
        {
            "name": "frontend_interim_rendered_at",
            "location": "useSeatData.ts:after setInterimMap()",
            "description": "React state updated — render queued",
            "side": "frontend",
        },
        # ── Backend ───────────────────────────────────────────────────────
        {
            "name": "backend_pcm_received_at",
            "location": "speech_ws.py:_handle_binary_message()",
            "description": "Backend WebSocket received PCM binary frame",
            "side": "backend",
        },
        {
            "name": "backend_process_pcm_start_at",
            "location": "speech_ws.py:_handle_binary_message() before process_pcm_frame()",
            "description": "Backend about to enter process_pcm_frame (WS-layer dispatch)",
            "side": "backend",
        },
        {
            "name": "asr_streaming_start_at",
            "location": "speech_stream_service.py:process_pcm_frame()",
            "description": "Streaming ASR inference started (process_interim_array call)",
            "side": "backend",
        },
        {
            "name": "asr_streaming_end_at",
            "location": "speech_stream_service.py:process_pcm_frame() after ASR",
            "description": "Streaming ASR returned text (only traces when raw_text is truthy)",
            "side": "backend",
        },
        {
            "name": "interim_event_created_at",
            "location": "speech_ws.py:_handle_binary_message() before event_bus.publish",
            "description": "TranslationInterimEvent payload built, about to publish",
            "side": "backend",
        },
        {
            "name": "interim_event_broadcast_at",
            "location": "speech_ws.py:_handle_binary_message() after event_bus.publish",
            "description": "TranslationInterimEvent published to EventBus",
            "side": "backend",
        },
        {
            "name": "utterance_started_at",
            "location": "speech_ws.py:_handle_text_message() type='start'",
            "description": "Utterance started — backend generated utterance_id",
            "side": "backend",
        },
        {
            "name": "end_hint_received_at",
            "location": "speech_ws.py:_handle_text_message() type='end_hint'",
            "description": "End hint received from frontend",
            "side": "backend",
        },
        {
            "name": "finalization_start_at",
            "location": "translation_service.py:process_final_array()",
            "description": "Offline ASR finalization started",
            "side": "backend",
        },
        {
            "name": "offline_rescore_complete_at",
            "location": "translation_service.py:process_final_array() after persist",
            "description": "Offline ASR rescore + translation + persist complete",
            "side": "backend",
        },
    ]


# ── Metric definitions ──────────────────────────────────────────────────────


def _metric_definitions() -> list[dict]:
    """Return the canonical definition of every derived latency metric."""
    return [
        {
            "name": "start_to_mic_ready_ms",
            "category": CAT_FRONTEND,
            "formula": "microphone_started_at - start_clicked_at",
            "description": "Time from user click to microphone fully ready (getUserMedia + AudioContext)",
            "likely_bottleneck": "browser getUserMedia permission dialog, AudioContext creation",
            "requires_events": ["start_clicked_at", "microphone_started_at"],
        },
        {
            "name": "mic_ready_to_first_pcm_ms",
            "category": CAT_FRONTEND,
            "formula": "first frontend_pcm_created_at - microphone_started_at",
            "description": "Time from mic ready to first PCM frame created",
            "likely_bottleneck": "ScriptProcessorNode buffer fill latency (~4096 samples @ 16kHz = 256ms)",
            "requires_events": ["microphone_started_at", "frontend_pcm_created_at"],
        },
        {
            "name": "first_pcm_created_to_sent_ms",
            "category": CAT_FRONTEND,
            "formula": "first frontend_pcm_sent_at - first frontend_pcm_created_at",
            "description": "Time from frame creation to WebSocket send (same-side, frontend monotonic)",
            "likely_bottleneck": "JS event loop scheduling, ArrayBuffer transfer",
            "requires_events": ["frontend_pcm_created_at", "frontend_pcm_sent_at"],
        },
        {
            "name": "first_pcm_sent_to_backend_received_ms",
            "category": CAT_CROSS_BOUNDARY,
            "formula": "backend_pcm_received_at (wall) - frontend_pcm_sent_at (wall)",
            "description": "Network transit time frontend to backend (approximate, wall-clock based)",
            "likely_bottleneck": "WebSocket frame serialization, network latency, backend event loop",
            "requires_events": ["frontend_pcm_sent_at", "backend_pcm_received_at"],
        },
        {
            "name": "backend_received_to_asr_start_ms",
            "category": CAT_BACKEND,
            "formula": "asr_streaming_start_at - backend_pcm_received_at",
            "description": "Backend processing before ASR inference starts (PCM to float32, session lookup, SpeechModule lazy-load)",
            "likely_bottleneck": "PCM16 to float32 conversion, session lookup, SpeechModule lazy-load",
            "requires_events": ["backend_pcm_received_at", "asr_streaming_start_at"],
        },
        {
            "name": "asr_infer_ms",
            "category": CAT_BACKEND,
            "formula": "asr_streaming_end_at - asr_streaming_start_at (or asr_infer_ms extra field)",
            "description": "Time spent in process_interim_array() — the actual ASR inference",
            "likely_bottleneck": "Model inference on CPU, model size, audio frame duration (100ms)",
            "requires_events": ["asr_streaming_start_at", "asr_streaming_end_at"],
        },
        {
            "name": "asr_end_to_interim_broadcast_ms",
            "category": CAT_BACKEND,
            "formula": "interim_event_broadcast_at - asr_streaming_end_at",
            "description": "Time from ASR result to EventBus publish (caption formatter, VAD, payload)",
            "likely_bottleneck": "CaptionFormatter processing, revision bump, VAD check, payload serialization",
            "requires_events": ["asr_streaming_end_at", "interim_event_broadcast_at"],
        },
        {
            "name": "interim_broadcast_to_frontend_received_ms",
            "category": CAT_CROSS_BOUNDARY,
            "formula": "frontend_interim_received_at (wall) - interim_event_broadcast_at (wall)",
            "description": "EventBus to WS broadcast to frontend receives (approximate, wall-clock based)",
            "likely_bottleneck": "EventBus subscriber dispatch, WebSocket serialization, network",
            "requires_events": ["interim_event_broadcast_at", "frontend_interim_received_at"],
        },
        {
            "name": "frontend_received_to_rendered_ms",
            "category": CAT_FRONTEND,
            "formula": "frontend_interim_rendered_at - frontend_interim_received_at",
            "description": "Time from frontend WS receive to React state update (same-side, frontend monotonic)",
            "likely_bottleneck": "React reconciliation, component re-render",
            "requires_events": ["frontend_interim_received_at", "frontend_interim_rendered_at"],
        },
        {
            "name": "first_pcm_to_first_interim_ms",
            "category": CAT_END_TO_END,
            "formula": "first frontend_interim_rendered_at (wall) - first frontend_pcm_created_at (wall)",
            "description": "End-to-end audio processing latency (PCM created to interim displayed). Requires merged frontend+backend traces.",
            "likely_bottleneck": "Sum of all pipeline steps — the critical overall metric",
            "requires_events": ["frontend_pcm_created_at", "frontend_interim_rendered_at"],
        },
        {
            "name": "start_to_first_interim_ms",
            "category": CAT_END_TO_END,
            "formula": "first frontend_interim_rendered_at (wall) - start_clicked_at (wall)",
            "description": "Total first-token latency from user click to first displayed interim. Requires merged frontend+backend traces.",
            "likely_bottleneck": "The user-visible latency — what matters most",
            "requires_events": ["start_clicked_at", "frontend_interim_rendered_at"],
        },
    ]


# ── Missing fields analysis ─────────────────────────────────────────────────


def _compute_missing_fields(
    frontend_events: list[dict],
    backend_events: list[dict],
) -> dict[str, Any]:
    """Analyze which trace point events are present vs missing.

    Returns a dict with keys:
        all_events (list), present_frontend (list), missing_frontend (list),
        present_backend (list), missing_backend (list), summary (str).
    """
    all_events = _all_trace_event_names()
    fe_names = {e.get("event", "") for e in frontend_events}
    bk_names = {e.get("event", "") for e in backend_events}

    present_frontend = [n for n in all_events if n in fe_names]
    missing_frontend = [n for n in all_events if n not in fe_names]
    present_backend = [n for n in all_events if n in bk_names]
    missing_backend = [n for n in all_events if n not in bk_names]

    lines = []
    if present_frontend:
        lines.append(f"Frontend: {len(present_frontend)}/{len(all_events)} trace points present")
    if missing_frontend:
        lines.append(f"Frontend missing: {', '.join(missing_frontend)}")
    if present_backend:
        lines.append(f"Backend: {len(present_backend)}/{len(all_events)} trace points present")
    if missing_backend:
        lines.append(f"Backend missing: {', '.join(missing_backend)}")

    return {
        "all_expected_trace_points": all_events,
        "present_frontend": present_frontend,
        "missing_frontend": missing_frontend,
        "present_backend": present_backend,
        "missing_backend": missing_backend,
        "summary": "; ".join(lines) if lines else "No trace data available",
    }


# ── Data loading ────────────────────────────────────────────────────────────


def _load_frontend_trace(path: str | None) -> dict:
    """Load frontend trace from a JSON file exported via speechTrace.ts.

    Returns dict with keys:
        available (bool), note (str), events (list), wall_clock_offset_ms (int|None).
    """
    result: dict = {
        "available": False,
        "note": None,
        "events": [],
        "wall_clock_offset_ms": None,
        "file_path": None,
    }

    if not path:
        result["note"] = (
            "No frontend trace file provided. Set --frontend-trace or "
            "FRONTEND_SPEECH_TRACE_PATH env var, or export one from the "
            "browser DevTools via:\n"
            "  window.__SMARTDESK_SPEECH_TRACE__.downloadTraceFile();"
        )
        return result

    path_obj = Path(path)
    if not path_obj.exists():
        result["note"] = f"Frontend trace file not found: {path}"
        return result

    try:
        with open(path_obj, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        result["note"] = f"Failed to read frontend trace file: {exc}"
        return result

    events_raw = raw.get("events", [])
    wall_offset = raw.get("wall_clock_offset_ms")

    # Normalize each event: add estimated_wall_ms if wall_offset is available
    events: list[dict] = []
    for ev in events_raw:
        ts = ev.get("timestamp", 0)
        normalized = {
            "event": ev.get("event", "unknown"),
            "timestamp": ts,
            "data": ev.get("data", {}),
        }
        if wall_offset is not None:
            normalized["estimated_wall_ms"] = int(wall_offset + ts)
        events.append(normalized)

    result["available"] = True
    result["events"] = events
    result["event_count"] = len(events)
    result["wall_clock_offset_ms"] = wall_offset
    result["file_path"] = str(path_obj)
    result["note"] = (
        f"Frontend trace loaded from {path_obj.name}: {len(events)} events, "
        f"wall_clock_offset_ms={wall_offset}"
    )
    return result


def _load_backend_trace(backend_trace_path: str | None = None) -> dict:
    """Load backend trace data.

    Priority:
        1. If backend_trace_path is provided, load from that JSON file.
        2. Otherwise try the in-process ring buffer (from speech_trace module).

    Returns dict with keys:
        available (bool), note (str), events (list), enabled (bool),
        source (str).
    """
    result: dict = {
        "available": False,
        "note": None,
        "events": [],
        "enabled": False,
        "source": "none",
    }

    # Priority 1: File-based backend trace
    if backend_trace_path:
        path_obj = Path(backend_trace_path)
        if not path_obj.exists():
            result["note"] = f"Backend trace file not found: {backend_trace_path}"
            return result
        try:
            with open(path_obj, "r", encoding="utf-8") as f:
                raw = json.load(f)
            raw_events = raw.get("events", [])
            result["available"] = bool(raw_events)
            result["events"] = raw_events
            result["event_count"] = len(raw_events)
            result["source"] = "file"
            result["enabled"] = raw.get("trace_enabled", False)
            result["note"] = (
                f"Backend trace loaded from file: {len(raw_events)} events"
            )
            return result
        except (json.JSONDecodeError, OSError) as exc:
            result["note"] = f"Failed to read backend trace file: {exc}"
            return result

    # Priority 2: In-process ring buffer
    try:
        from backend.websocket.speech_trace import get_trace, is_trace_enabled

        enabled = is_trace_enabled()
        result["enabled"] = enabled

        if not enabled:
            result["note"] = (
                "Backend speech trace is DISABLED. "
                "Set SMART_DESK_ENABLE_SPEECH_TRACE=true then re-record."
            )
            return result

        events = get_trace()
        if not events:
            result["note"] = (
                "Backend trace is enabled but the ring buffer is empty. "
                "Record audio with the speech pipeline first."
            )
            return result

        result["available"] = True
        result["events"] = events
        result["event_count"] = len(events)
        result["source"] = "ring_buffer"
        result["note"] = f"Backend trace loaded from ring buffer: {len(events)} events"

    except ImportError as exc:
        result["note"] = f"Backend speech_trace module not importable: {exc}"
    except Exception as exc:
        result["note"] = f"Error reading backend trace data: {exc}"

    return result


# ── Metrics computation ─────────────────────────────────────────────────────


def _first_by_name(
    events: list[dict], name_key: str = "event",
) -> dict[str, dict]:
    """Index events by name, keeping only the first occurrence of each."""
    index: dict[str, dict] = {}
    for ev in events:
        name = ev.get(name_key, "")
        if name and name not in index:
            index[name] = ev
    return index


def _compute_metrics(
    backend_events: list[dict],
    frontend_events: list[dict],
    frontend_wall_offset: int | None,
) -> dict[str, dict]:
    """Compute all latency metrics from merged trace data.

    Returns a dict keyed by metric name. Each value contains:
        category (str), computed (bool), value_ms (int|None),
        note (str), start_event (str), end_event (str).

    Same-side metrics use monotonic timestamps (accurate).
    Cross-boundary metrics use estimated wall-clock (approximate).
    Missing trace events result in ``unavailable`` metrics.
    """
    metrics: dict[str, dict] = {}
    definitions = _metric_definitions()

    # Index both sides
    bk_first = _first_by_name(backend_events, "event")
    fe_first = _first_by_name(frontend_events, "event")

    # Pre-extract the computed asr_infer_ms from backend trace
    asr_infer_inline: int | None = None
    for ev in backend_events:
        if ev.get("event") == "asr_streaming_end_at":
            val = ev.get("asr_infer_ms")
            if val is not None:
                asr_infer_inline = int(val)
                break

    for meta in definitions:
        name = meta["name"]
        req = meta["requires_events"]
        cat = meta["category"]
        result: dict = {
            "name": name,
            "category": cat,
            "computed": False,
            "value_ms": None,
            "start_event": req[0] if len(req) >= 1 else None,
            "end_event": req[1] if len(req) >= 2 else None,
            "note": None,
        }

        # Determine which side provides each required event
        fe_start = fe_first.get(req[0])
        fe_end = fe_first.get(req[1])
        bk_start = bk_first.get(req[0])
        bk_end = bk_first.get(req[1])

        if cat == CAT_FRONTEND:
            # Both events must be on the frontend side
            if not fe_start or not fe_end:
                result["note"] = (
                    f"Missing frontend event(s): "
                    f"{' / '.join(e for e in req if e not in fe_first)}"
                )
                metrics[name] = result
                continue

        if cat == CAT_BACKEND:
            # Both events must be on the backend side
            if not bk_start or not bk_end:
                result["note"] = (
                    f"Missing backend event(s): "
                    f"{' / '.join(e for e in req if e not in bk_first)}"
                )
                metrics[name] = result
                continue

        if cat == CAT_END_TO_END:
            # Each required event must exist on at least one side
            missing = [e for e in req if e not in fe_first and e not in bk_first]
            if missing:
                result["note"] = (
                    f"Missing event(s): {missing}"
                )
                metrics[name] = result
                continue

        if cat == CAT_FRONTEND:
            # Both events on frontend — use frontend monotonic timestamps
            ts_start = fe_start.get("timestamp", 0)
            ts_end = fe_end.get("timestamp", 0)
            delta = ts_end - ts_start
            if delta < 0:
                result["note"] = f"Negative delta ({delta}ms) — timestamps may be out of order"
                metrics[name] = result
            else:
                result["computed"] = True
                result["value_ms"] = delta
                result["note"] = "frontend monotonic (performance.now)"

        elif cat == CAT_BACKEND:
            # Both events on backend — use backend monotonic timestamps
            ts_start = bk_start.get("timestamp_monotonic_ms", 0)
            ts_end = bk_end.get("timestamp_monotonic_ms", 0)
            delta = ts_end - ts_start
            if delta < 0:
                result["note"] = f"Negative delta ({delta}ms) — timestamps may be out of order"
                metrics[name] = result
            else:
                result["computed"] = True
                result["value_ms"] = delta
                result["note"] = "backend monotonic (time.monotonic_ns)"

        elif cat == CAT_CROSS_BOUNDARY:
            # Need wall-clock alignment on both sides
            if frontend_wall_offset is None:
                result["note"] = (
                    "Cross-boundary metric unavailable: frontend "
                    "wall_clock_offset_ms is missing from trace export."
                )
                metrics[name] = result
                continue

            if req[0] in fe_first and req[1] in bk_first:
                # frontend to backend direction
                fe_ev = fe_first[req[0]]
                bk_ev = bk_first[req[1]]
                fe_wall = fe_ev.get("estimated_wall_ms") or (
                    frontend_wall_offset + fe_ev.get("timestamp", 0)
                )
                bk_wall = bk_ev.get("timestamp_wall_ms", 0)
                if fe_wall and bk_wall:
                    delta = bk_wall - fe_wall
                    result["computed"] = True
                    result["value_ms"] = delta
                    result["note"] = "approximate (wall-clock, cross-boundary)"
                else:
                    result["note"] = "Missing wall timestamp for cross-boundary computation"

            elif req[0] in bk_first and req[1] in fe_first:
                # backend to frontend direction
                bk_ev = bk_first[req[0]]
                fe_ev = fe_first[req[1]]
                bk_wall = bk_ev.get("timestamp_wall_ms", 0)
                fe_wall = fe_ev.get("estimated_wall_ms") or (
                    frontend_wall_offset + fe_ev.get("timestamp", 0)
                )
                if bk_wall and fe_wall:
                    delta = fe_wall - bk_wall
                    result["computed"] = True
                    result["value_ms"] = delta
                    result["note"] = "approximate (wall-clock, cross-boundary)"
                else:
                    result["note"] = "Missing wall timestamp for cross-boundary computation"
            else:
                missing = [e for e in req if e not in bk_first and e not in fe_first]
                result["note"] = f"Missing events for cross-boundary metric: {missing}"

        elif cat == CAT_END_TO_END:
            # End-to-end: start is frontend, end is frontend,
            # but the end event (frontend_interim_rendered_at) depends on backend
            # processing. We use wall-clock on both sides.

            # Check we have all required events somewhere
            start_ok = req[0] in fe_first
            end_ok = req[1] in fe_first

            if not start_ok:
                result["note"] = f"Missing start event '{req[0]}'"
                metrics[name] = result
                continue
            if not end_ok:
                result["note"] = f"Missing end event '{req[1]}'"
                metrics[name] = result
                continue

            if frontend_wall_offset is None:
                result["note"] = (
                    "End-to-end metric unavailable: frontend "
                    "wall_clock_offset_ms is missing from trace export."
                )
                metrics[name] = result
                continue

            fe_start_ev = fe_first[req[0]]
            fe_end_ev = fe_first[req[1]]

            fe_start_wall = fe_start_ev.get("estimated_wall_ms") or (
                frontend_wall_offset + fe_start_ev.get("timestamp", 0)
            )
            fe_end_wall = fe_end_ev.get("estimated_wall_ms") or (
                frontend_wall_offset + fe_end_ev.get("timestamp", 0)
            )

            if fe_start_wall and fe_end_wall:
                delta = fe_end_wall - fe_start_wall
                if delta < 0:
                    result["note"] = f"Negative delta ({delta}ms) — timestamps may be out of order"
                else:
                    result["computed"] = True
                    result["value_ms"] = delta
                    result["note"] = "approximate (wall-clock, end-to-end via frontend export)"
            else:
                result["note"] = "Missing wall timestamp for end-to-end computation"

        else:
            result["note"] = f"Unknown category: {cat}"

        metrics[name] = result

    # Special override: asr_infer_ms from the backend's perf_counter extra field
    if asr_infer_inline is not None and "asr_infer_ms" in metrics:
        m = metrics["asr_infer_ms"]
        m["value_ms"] = asr_infer_inline
        m["computed"] = True
        m["note"] = "precise (perf_counter from asr_streaming_end_at extra field)"

    return metrics


# ── Bottleneck assessment ──────────────────────────────────────────────────


def _assess_bottleneck(metrics: dict[str, dict]) -> dict:
    """Identify the slowest segment among computed metrics."""
    computed_segments = []
    for name, m in metrics.items():
        if m.get("computed") and m.get("value_ms") is not None:
            computed_segments.append({
                "metric": name,
                "category": m.get("category", "unknown"),
                "value_ms": m["value_ms"],
                "note": m.get("note", ""),
            })

    # Sort slowest first
    computed_segments.sort(key=lambda s: s["value_ms"], reverse=True)

    # Check if any e2e metrics are computed
    any_e2e = any(
        s["category"] == CAT_END_TO_END for s in computed_segments
    )
    any_backend = any(
        s["category"] == CAT_BACKEND for s in computed_segments
    )
    any_frontend = any(
        s["category"] == CAT_FRONTEND for s in computed_segments
    )

    if not computed_segments:
        return {
            "assessment": "insufficient_data",
            "message": (
                "No latency metrics could be computed. "
                "Check the individual metric notes for details."
            ),
            "computed_segments": [],
        }

    result: dict = {
        "assessment": "partial_data" if not any_e2e else "complete",
        "computed_segments": computed_segments,
        "has_e2e": any_e2e,
        "has_backend": any_backend,
        "has_frontend": any_frontend,
    }

    if computed_segments:
        result["likely_bottleneck"] = computed_segments[0]

    if not any_e2e:
        result["message"] = (
            "End-to-end metrics are not available because frontend trace data "
            "is missing or incomplete. Only backend-only and frontend-only "
            "segments were computed. Export a frontend trace file to enable "
            "end-to-end latency analysis."
        )
    else:
        result["message"] = (
            "End-to-end metrics computed. See segments below. "
            "IMPORTANT: These are estimates based on frontend wall-clock "
            "alignment (performance.now + wall_clock_offset_ms), not precise "
            "hardware timestamps."
        )

    return result


# ── Report generation ─────────────────────────────────────────────────────


def generate_report(
    frontend_trace_path: str | None = None,
    backend_trace_path: str | None = None,
) -> dict:
    """Generate the complete merged latency report.

    Args:
        frontend_trace_path: Optional path to a frontend trace JSON file
                             exported from speechTrace.ts.
        backend_trace_path: Optional path to a backend trace JSON file
                            exported from speech_trace.export_trace_to_file().
    """
    # 1. Load data
    frontend_trace = _load_frontend_trace(frontend_trace_path)
    backend_trace = _load_backend_trace(backend_trace_path)

    # 2. Compute missing fields
    missing_fields = _compute_missing_fields(
        frontend_events=frontend_trace.get("events", []),
        backend_events=backend_trace.get("events", []),
    )

    # 3. Compute metrics
    metrics = _compute_metrics(
        backend_events=backend_trace.get("events", []),
        frontend_events=frontend_trace.get("events", []),
        frontend_wall_offset=frontend_trace.get("wall_clock_offset_ms"),
    )

    # 4. Categorize metrics
    categorized: dict[str, dict] = {}
    for cat in (CAT_FRONTEND, CAT_BACKEND, CAT_CROSS_BOUNDARY, CAT_END_TO_END, CAT_UNAVAILABLE):
        categorized[cat] = {}

    for name, m in metrics.items():
        cat = m.get("category", CAT_UNAVAILABLE)
        categorized[cat][name] = m

    # 5. Bottleneck assessment
    assessment = _assess_bottleneck(metrics)

    # 6. Build report
    trace_points = _trace_points()
    metric_defs = _metric_definitions()

    report = {
        "report_type": "speech-browser-merged-latency-report",
        "task": "128E",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # ── Trace data sources ──────────────────────────────────────────
        "trace_sources": {
            "frontend": {
                "available": frontend_trace.get("available", False),
                "file_path": frontend_trace.get("file_path"),
                "event_count": frontend_trace.get("event_count", 0),
                "wall_clock_offset_ms": frontend_trace.get("wall_clock_offset_ms"),
                "note": frontend_trace.get("note"),
            },
            "backend": {
                "available": backend_trace.get("available", False),
                "source": backend_trace.get("source", "none"),
                "enabled": backend_trace.get("enabled", False),
                "event_count": backend_trace.get("event_count", 0),
                "note": backend_trace.get("note"),
            },
        },
        # ── Missing fields analysis ────────────────────────────────────
        "missing_fields": missing_fields,
        # ── Trace point catalog ────────────────────────────────────────
        "trace_points": trace_points,
        "trace_point_count": len(trace_points),
        # ── Metric definitions ─────────────────────────────────────────
        "latency_metrics_defined": metric_defs,
        "latency_metrics_count": len(metric_defs),
        # ── Computed metrics ───────────────────────────────────────────
        "metrics_computed": {
            "frontend_only": categorized[CAT_FRONTEND],
            "backend_only": categorized[CAT_BACKEND],
            "cross_boundary": categorized[CAT_CROSS_BOUNDARY],
            "end_to_end": categorized[CAT_END_TO_END],
            "unavailable": categorized[CAT_UNAVAILABLE],
        },
        # ── Bottleneck assessment ──────────────────────────────────────
        "bottleneck_assessment": assessment,
        # ── Sampling guidance ──────────────────────────────────────────
        "sampling_instructions": {
            "how_to_sample": (
                "=== Prerequisites ===\n"
                "1. Set SMART_DESK_ENABLE_SPEECH_TRACE=true in backend .env\n"
                "2. Set VITE_ENABLE_SPEECH_TRACE=true in frontend .env\n"
                "3. Start backend: uvicorn backend.main:app\n"
                "4. Start frontend: npm run dev\n"
                "5. Open a meeting with a seat available\n\n"
                "=== Recording ===\n"
                "6. Open http://localhost:5173/seat/1\n"
                "7. Occupy the seat, check in\n"
                "8. Admin sets seat 1 as speaker\n"
                "9. Click Start Speech\n"
                "10. Speak a short phrase (2-3 seconds)\n"
                "11. Click Stop\n\n"
                "=== Export Frontend Trace ===\n"
                "12. Open browser DevTools (F12)\n"
                "13. In console, run:\n"
                '    window.__SMARTDESK_SPEECH_TRACE__.downloadTraceFile();\n'
                "14. This downloads speech-trace.json to your downloads folder\n"
                "15. Copy to working/speech-browser-trace-frontend.json\n\n"
                "=== Export Backend Trace ===\n"
                "16. While the backend process is still running, run:\n"
                '    python -c "from backend.websocket.speech_trace import export_trace_to_file; export_trace_to_file(\'working/speech-browser-trace-backend.json\')"\n'
                "17. Or stop backend and run with --backend-trace file\n\n"
                "=== Generate Report ===\n"
                "18. Run:\n"
                "    python -m backend.scripts.generate_latency_report \\\n"
                "      --frontend-trace working/speech-browser-trace-frontend.json \\\n"
                "      --backend-trace working/speech-browser-trace-backend.json \\\n"
                "      --output working/speech-browser-merged-latency-report.json"
            ),
            "frontend_export_methods": [
                "Browser console: window.__SMARTDESK_SPEECH_TRACE__.downloadTraceFile()",
                "Browser console: copy(window.__SMARTDESK_SPEECH_TRACE__.serializeTrace())",
                "Programmatic: import { downloadTraceFile, serializeTrace } from '../audio/speechTrace'",
            ],
            "backend_export_methods": [
                "Inline: python -c \"from backend.websocket.speech_trace import export_trace_to_file; export_trace_to_file('working/backend-trace.json')\"",
                "Programmatic: from backend.websocket.speech_trace import export_trace_to_file",
            ],
        },
        # ── Code-level assessment (without live data, for comparison) ──
        "code_level_bottleneck_assessment": {
            "summary": (
                "Without live browser trace data, this assessment uses the "
                "real-dataset benchmark (Task 128B) as a proxy. The benchmark "
                "measures offline replay of pre-recorded files, which excludes "
                "getUserMedia latency, WebSocket handshake, and React render delay. "
                "It is NOT a substitute for real browser trace data."
            ),
            "reasons": [
                "All speech module warmup functions hardcode device='cpu' — no CUDA auto-detection.",
                "Streaming ASR (Paraformer) runs synchronously in the WebSocket handler's event loop.",
                "PCM frames are 100ms each; ScriptProcessorNode adds ~256ms buffer latency.",
                "getUserMedia requires user permission dialog — adds 200-2000ms on first call.",
                "WebSocket frame serialization and network latency are typically <10ms locally.",
            ],
            "estimated_first_interim_breakdown": {
                "mic_setup_ms": "200-2000 (getUserMedia, first call only)",
                "first_chunk_collection_ms": "~256ms (ScriptProcessorNode buffer)",
                "first_chunk_network_ms": "<10ms (localhost WebSocket)",
                "backend_dispatch_ms": "<5ms (PCM to float32, session lookup)",
                "asr_inference_ms": "~100ms (Paraformer streaming on CPU, first chunk includes warmup)",
                "chunk_accumulation_window_ms": "~1600ms (CIF encoder ~16 chunks)",
                "broadcast_ms": "<5ms (EventBus + WS to frontend)",
                "frontend_render_ms": "<20ms (React state update + reconciliation)",
            },
            "recommended_next_steps": (
                "Collect live browser trace data first. Compare the measured "
                "end-to-end latency against the breakdown above. If ASR inference "
                "(asr_infer_ms) dominates (>200ms per 100ms frame), consider "
                "Task 127B (ASR worker queue). If chunk accumulation window is "
                "the dominant factor, try ultra_low_latency preset. If mic setup "
                "dominates, the bottleneck is getUserMedia, not ASR."
            ),
        },
        # ── Known limitations ──────────────────────────────────────────
        "known_limitations": [
            "Frontend timestamps use performance.now() which is relative, not wall-clock.",
            "Cross-boundary metrics use performance.now + wall_clock_offset_ms (estimated, not precise).",
            "getUserMedia permission dialog latency varies by browser (first call vs subsequent).",
            "The frontend rendering trace point fires before React commits the DOM update.",
            "Backend timestamps use time.monotonic_ns (precise) + time.time() (wall-clock estimate).",
            "If frontend and backend clocks are not synchronized, cross-boundary metrics are approximate.",
            "Automated microphone capture is not supported by Playwright — requires manual browser interaction.",
        ],
    }

    return report


# ── CLI ────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate merged frontend+backend speech latency report",
    )
    parser.add_argument(
        "--frontend-trace",
        default=None,
        help="Path to frontend trace JSON file (exported from browser)",
    )
    parser.add_argument(
        "--backend-trace",
        default=None,
        help="Path to backend trace JSON file (exported via export_trace_to_file)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for the merged JSON report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # Prefer CLI arg; fall back to env var
    frontend_path = args.frontend_trace or os.environ.get(
        "FRONTEND_SPEECH_TRACE_PATH",
    )
    backend_path = args.backend_trace or os.environ.get(
        "BACKEND_SPEECH_TRACE_PATH",
    )
    output_path = args.output

    report = generate_report(
        frontend_trace_path=frontend_path,
        backend_trace_path=backend_path,
    )

    # Determine output path
    if output_path:
        out = Path(output_path)
    else:
        out = REPORT_PATH

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"[Task 128E] Merged latency report written to {out}")

    # Print summary to stdout
    frontend_avail = report["trace_sources"]["frontend"]["available"]
    backend_avail = report["trace_sources"]["backend"]["available"]
    fe_count = report["trace_sources"]["frontend"].get("event_count", 0)
    bk_count = report["trace_sources"]["backend"].get("event_count", 0)
    missing_front = report["missing_fields"]["missing_frontend"]
    missing_back = report["missing_fields"]["missing_backend"]

    print(f"  Frontend trace: {'YES' if frontend_avail else 'NO'} "
          f"({fe_count} events)")
    print(f"  Backend trace:  {'YES' if backend_avail else 'NO'} "
          f"({bk_count} events)")
    print(f"  Missing frontend events: {len(missing_front)}")
    print(f"  Missing backend events:  {len(missing_back)}")

    computed = report["metrics_computed"]
    for cat, cat_data in computed.items():
        computed_count = sum(
            1 for m in cat_data.values() if m.get("computed")
        )
        total = len(cat_data)
        if computed_count > 0:
            print(f"  {cat}: {computed_count}/{total} computed")
            for name, m in cat_data.items():
                if m.get("computed"):
                    print(f"    {name}: {m['value_ms']}ms ({m.get('note', '')})")

    assessment = report.get("bottleneck_assessment", {})
    print(f"  Assessment: {assessment.get('assessment', 'unknown')}")
    if assessment.get("likely_bottleneck"):
        lb = assessment["likely_bottleneck"]
        print(f"  Likely bottleneck: {lb.get('metric', '?')} "
              f"({lb.get('value_ms', '?')}ms)")

    if not frontend_avail or not backend_avail:
        print()
        print("  [WARNING] One or both trace sources are missing.")
        print("  See sampling_instructions.how_to_sample for capture steps.")

    print(f"\n[Task 128E] Done.")


if __name__ == "__main__":
    main()
