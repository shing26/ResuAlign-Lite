"""Small shared observability helpers for crawl and pipeline requests."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

_request_id_context: ContextVar[str | None] = ContextVar(
    "resualign_request_id", default=None
)


def new_request_id() -> str:
    """Return a compact, collision-resistant request id."""
    return uuid.uuid4().hex[:12]


def current_request_id() -> str | None:
    """Return the request id bound to the current context, if any."""
    return _request_id_context.get()


def set_request_id(request_id: str | None) -> Any:
    """Bind a request id and return the token needed to reset it."""
    return _request_id_context.set(request_id)


def reset_request_id(token: Any) -> None:
    """Reset a request id bound with :func:`set_request_id`."""
    _request_id_context.reset(token)


@contextmanager
def request_context(request_id: str | None = None):
    """Set a request id for the duration of a block."""
    token = set_request_id(request_id)
    try:
        yield
    finally:
        reset_request_id(token)


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: str = "info",
    request_id: str | None = None,
    duration_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a one-line JSON structured log record."""
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    if duration_ms is not None:
        payload["duration_ms"] = round(float(duration_ms), 3)
    if extra:
        payload["extra"] = extra
    getattr(logger, level)(
        json.dumps(payload, ensure_ascii=False, default=str)
    )


def log_slow_call(
    logger: logging.Logger,
    event: str,
    duration_ms: float,
    threshold_ms: float,
    *,
    request_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Log a warning when a call exceeds the configured threshold."""
    if duration_ms < threshold_ms:
        return False
    details = dict(extra or {})
    details.setdefault("threshold_ms", threshold_ms)
    log_event(
        logger,
        event,
        level="warning",
        request_id=request_id,
        duration_ms=duration_ms,
        extra=details,
    )
    return True


class CacheHitCounter:
    """Tiny thread-safe in-memory cache hit/miss counter."""

    def __init__(self) -> None:
        self._hits = 0
        self._misses = 0
        self._lock = threading.Lock()

    def hit(self, count: int = 1) -> None:
        with self._lock:
            self._hits += max(0, count)

    def miss(self, count: int = 1) -> None:
        with self._lock:
            self._misses += max(0, count)

    def hit_rate(self) -> float | None:
        with self._lock:
            total = self._hits + self._misses
            if total == 0:
                return None
            return self._hits / total

    def snapshot(self) -> dict[str, int | float | None]:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "total": total,
                "hit_rate": (self._hits / total) if total else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._hits = 0
            self._misses = 0
