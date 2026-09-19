"""Raw LLM request/response archive (architecture hardening, 2026-09-19).

Event-level logs already say *that* a call happened, how long it took and how
many tokens it used. They do not preserve *what* was sent, so a disputed run
("the model ignored my JD") cannot be replayed. This module writes the full
exchange as JSONL to ``<RESUALIGN_LOG_DIR>/llm-traces.jsonl`` with the same
10 MB x 5 rotation policy as ``app.log``.

Design constraints:

- **Off by default.** ``RESUALIGN_LLM_TRACE`` defaults to ``0``; callers pass
  ``None`` bodies unless tracing is on, so the disabled path adds no I/O and
  no allocation to an LLM call.
- **Redacted on the way out.** Records pass through
  :func:`resualign.observability.redact_fields`, which masks ``sk-`` tokens
  and truncates oversized ``error`` strings.
- **Never fatal.** A trace write failure logs a warning and returns; the LLM
  call it describes is unaffected.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from ..observability import redact_fields
from ..store_base import resolve_data_dir

TRACE_ENV = "RESUALIGN_LLM_TRACE"
TRACE_FILENAME = "llm-traces.jsonl"
TRACE_MAX_BYTES = 10 * 1024 * 1024
TRACE_BACKUP_COUNT = 5

_LOGGER_NAME = "resualign.llm_trace"
_TRUTHY = {"1", "true", "yes", "on"}

_lock = threading.Lock()
_handler: RotatingFileHandler | None = None
_handler_dir: Path | None = None
_logger = logging.getLogger(_LOGGER_NAME)


def trace_enabled() -> bool:
    """Whether the archive layer is switched on.

    The environment is read per call (not cached) so tests and long-running
    processes can toggle tracing without re-importing the module.
    """
    return os.environ.get(TRACE_ENV, "0").strip().lower() in _TRUTHY


def _log_dir() -> Path:
    return Path(
        os.environ.get("RESUALIGN_LOG_DIR") or (resolve_data_dir() / "logs")
    )


def _get_handler() -> RotatingFileHandler:
    """Return the process-wide trace handler, rebinding if the dir changed."""
    global _handler, _handler_dir
    target_dir = _log_dir()
    with _lock:
        if _handler is not None and _handler_dir == target_dir:
            return _handler
        if _handler is not None:
            _logger.removeHandler(_handler)
            _handler.close()
            _handler = None
        target_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            target_dir / TRACE_FILENAME,
            maxBytes=TRACE_MAX_BYTES,
            backupCount=TRACE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.setLevel(logging.INFO)
        _logger.propagate = False
        _logger.addHandler(handler)
        _handler = handler
        _handler_dir = target_dir
        return handler


def record_llm_trace(record: dict[str, Any]) -> None:
    """Append one redacted JSONL line. No-op when tracing is disabled."""
    if not trace_enabled():
        return
    payload = dict(record)
    payload.setdefault(
        "ts", datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    )
    try:
        _get_handler()
        _logger.info(
            "%s",
            json.dumps(
                redact_fields(payload), ensure_ascii=False, default=str
            ),
        )
    except Exception:  # noqa: BLE001 - archiving must never break a call
        logging.getLogger(__name__).warning(
            "Failed to write LLM trace record", exc_info=True
        )
