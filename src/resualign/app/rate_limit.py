"""In-memory rate limiting shared by API state and request dependencies."""

from __future__ import annotations

import threading
import time


class _RateLimiter:
    """Minimal in-memory sliding-window rate limiter per client key."""

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [
                timestamp
                for timestamp in self._hits.get(key, [])
                if now - timestamp < self.window_seconds
            ]
            if len(hits) >= self.max_requests:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
