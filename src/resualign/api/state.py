"""Compatibility facade for the process-wide application context."""

# ruff: noqa: F822

from __future__ import annotations

from ..app.context import _clamp_worker_concurrency
from ..app.context import context as _context

__all__ = [
    "_PERSONAL_MODE",
    "_WORKER_CONCURRENCY",
    "_WORKER_SEMAPHORE",
    "_MAX_BODY_BYTES",
    "_MAX_IMPORT_ROWS",
    "_MAX_RESUME_UPLOAD_BYTES",
    "_TIMELINE_FIELDS",
    "_analyze_rate_limiter",
    "_applications",
    "_auth_rate_limiter",
    "_batch_store",
    "_cache",
    "_cache_db",
    "_env_settings",
    "_import_batches",
    "_import_rate_limiter",
    "_jobs",
    "_llm_nodes",
    "_llm_usage",
    "_payloads",
    "_preanalyze_batches",
    "_registry",
    "_session_store",
    "_settings_store",
    "_users",
    "_resumes",
    "_clamp_worker_concurrency",
]


def __getattr__(name: str):
    return getattr(_context, name)
