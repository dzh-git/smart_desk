"""Small bounded in-process rate limiter for device-facing endpoints."""
from __future__ import annotations

import math
import os
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int = 0


def bounded_env_int(
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Read an integer setting and fall back safely on invalid input."""
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


class SlidingWindowRateLimiter:
    """Thread-safe sliding window with bounded caller-key memory."""

    def __init__(self, *, max_keys: int = 2048) -> None:
        self._max_keys = max(1, max_keys)
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def check(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> RateLimitDecision:
        current = time.monotonic() if now is None else now
        safe_limit = max(1, limit)
        safe_window = max(0.001, window_seconds)
        cutoff = current - safe_window
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._evict_if_full()
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= safe_limit:
                retry_after = max(
                    1,
                    math.ceil(bucket[0] + safe_window - current),
                )
                return RateLimitDecision(False, retry_after)
            bucket.append(current)
            return RateLimitDecision(True)

    def clear(self) -> None:
        """Clear counters; intended for deterministic tests."""
        with self._lock:
            self._buckets.clear()

    @property
    def key_count(self) -> int:
        with self._lock:
            return len(self._buckets)

    def _evict_if_full(self) -> None:
        while len(self._buckets) >= self._max_keys:
            self._buckets.popitem(last=False)


__all__ = [
    "RateLimitDecision",
    "SlidingWindowRateLimiter",
    "bounded_env_int",
]
