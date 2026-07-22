"""Shared CPU budget and priority gates for the local speech pipeline."""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from backend.websocket.speech_trace import trace


DEFAULT_TORCH_THREADS = 4
DEFAULT_TORCH_INTEROP_THREADS = 1
MEDIUM_BACKLOG_LIMIT_MS = 200
FINAL_IDLE_GRACE_S = 1.5


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def configure_speech_cpu_runtime() -> dict[str, int]:
    """Apply bounded CPU thread settings before speech models warm up."""
    intra = _positive_env("SMART_DESK_TORCH_THREADS", DEFAULT_TORCH_THREADS)
    interop = _positive_env(
        "SMART_DESK_TORCH_INTEROP_THREADS", DEFAULT_TORCH_INTEROP_THREADS,
    )
    os.environ.setdefault("OMP_NUM_THREADS", str(intra))
    os.environ.setdefault("MKL_NUM_THREADS", str(intra))
    try:
        import torch

        torch.set_num_threads(intra)
        # PyTorch only permits setting inter-op threads before parallel work.
        try:
            torch.set_num_interop_threads(interop)
        except RuntimeError:
            interop = torch.get_num_interop_threads()
    except Exception:
        pass
    return {
        "torch_threads": intra,
        "torch_interop_threads": interop,
        "omp_threads": _positive_env("OMP_NUM_THREADS", intra),
        "mkl_threads": _positive_env("MKL_NUM_THREADS", intra),
    }


@dataclass
class _StreamState:
    voice_active: bool = False
    backlog_ms: int = 0
    updated_at: float = 0.0


class SpeechInferenceRuntime:
    """Coordinates medium/final work around latency-critical live ASR."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._streams: dict[str, _StreamState] = {}
        self._settings = configure_speech_cpu_runtime()
        self._deferred_medium = 0
        self._deferred_final = 0

    def update_stream(
        self, session_key: str, *, voice_active: bool, backlog_ms: int,
    ) -> None:
        with self._condition:
            self._streams[session_key] = _StreamState(
                voice_active=voice_active,
                backlog_ms=max(0, int(backlog_ms)),
                updated_at=time.perf_counter(),
            )
            self._condition.notify_all()

    def remove_stream(self, session_key: str) -> None:
        with self._condition:
            self._streams.pop(session_key, None)
            self._condition.notify_all()

    def max_backlog_ms(self) -> int:
        with self._condition:
            return max((item.backlog_ms for item in self._streams.values()), default=0)

    def wait_for_medium(self, *, timeout: float = 3.0, trace_fields=None) -> bool:
        """Wait briefly for live PCM backlog to return below 200 ms."""
        deadline = time.monotonic() + max(0.0, timeout)
        traced = False
        with self._condition:
            while self.max_backlog_ms() > MEDIUM_BACKLOG_LIMIT_MS:
                if not traced:
                    self._deferred_medium += 1
                    trace("medium_inference_deferred_at", **(trace_fields or {}),
                          audio_backlog_ms=self.max_backlog_ms())
                    traced = True
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(0.1, remaining))
        return True

    def wait_for_final(self, *, boundary_reason: str, trace_fields=None) -> None:
        """Defer automatic final work until live speech has a real idle gap."""
        if boundary_reason == "end_hint":
            return
        idle_since: float | None = None
        traced = False
        with self._condition:
            while True:
                busy = any(
                    state.voice_active or state.backlog_ms > 0
                    for state in self._streams.values()
                )
                now = time.monotonic()
                if not busy:
                    idle_since = idle_since or now
                    if now - idle_since >= FINAL_IDLE_GRACE_S:
                        return
                else:
                    idle_since = None
                    if not traced:
                        self._deferred_final += 1
                        trace("final_inference_deferred_at", **(trace_fields or {}),
                              audio_backlog_ms=self.max_backlog_ms())
                        traced = True
                self._condition.wait(0.1)

    def diagnostics(self) -> dict[str, object]:
        with self._condition:
            return {
                **self._settings,
                "medium_backlog_limit_ms": MEDIUM_BACKLOG_LIMIT_MS,
                "final_idle_grace_ms": round(FINAL_IDLE_GRACE_S * 1000),
                "max_audio_backlog_ms": self.max_backlog_ms(),
                "deferred_medium_count": self._deferred_medium,
                "deferred_final_count": self._deferred_final,
            }


inference_runtime = SpeechInferenceRuntime()
