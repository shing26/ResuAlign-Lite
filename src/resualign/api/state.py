"""Process-wide API state: store singletons, rate limiters, constants.

``resualign.api`` re-exports every name from here (``from .state import *``),
so callers keep using ``api_module._registry`` etc. Tests that replace
``api_module._registry = ...`` swap the attribute on the package module,
which is exactly what routers and services resolve at call time.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from ..batch import BatchAlignStore
from ..cache import ContentCache
from ..config import EnvSettings
from ..job_library import CrawlTaskStore
from ..jobs import JobRegistry, resolve_data_dir
from ..settings_store import SettingsStore
from ..workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)
from .deps import _RateLimiter

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
    "_crawl_tasks",
    "_env_settings",
    "_import_batches",
    "_import_rate_limiter",
    "_jobs",
    "_payloads",
    "_registry",
    "_session_store",
    "_settings_store",
    "_users",
    "_resumes",
]


_env_settings = EnvSettings()


_auth_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)
_analyze_rate_limiter = _RateLimiter(max_requests=60, window_seconds=60)
_import_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)


def _clamp_worker_concurrency(value: int) -> int:
    """Clamp worker concurrency to the safe 1..4 range.

    Analysis jobs are LLM-bound; even modest concurrency (2-3) removes the
    serial queue for batch alignment while SQLite WAL handles the writes.
    Values outside 1..4 (misconfiguration) are clamped, never raised.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(parsed, 4))


_WORKER_CONCURRENCY = _clamp_worker_concurrency(
    _env_settings.resualign_worker_concurrency
)
_WORKER_SEMAPHORE = threading.BoundedSemaphore(_WORKER_CONCURRENCY)
_MAX_IMPORT_ROWS = 200
_MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
_MAX_BODY_BYTES = 8 * 1024 * 1024
_import_batches: dict[str, dict[str, Any]] = {}
_batch_store = BatchAlignStore()
_TIMELINE_FIELDS = ("applied_at", "next_step", "notes", "offer_at", "rejected_at")


_registry = JobRegistry(db_path=_env_settings.resualign_job_db or None)
_users = UserStore(db_path=_env_settings.resualign_job_db or None)
_resumes = MasterResumeStore(db_path=_env_settings.resualign_job_db or None)
_applications = ApplicationStore(
    db_path=_env_settings.resualign_job_db or None
)
_jobs = JobLibraryStore(db_path=_env_settings.resualign_job_db or None)
_crawl_tasks = CrawlTaskStore(db_path=_env_settings.resualign_job_db or None)
_settings_store = SettingsStore(db_path=_env_settings.resualign_job_db or None)
_cache_db = resolve_data_dir() / "content-cache.db"
_cache = ContentCache(db_path=_cache_db)


def _personal_mode_enabled() -> bool:
    value = _env_settings.resualign_personal_mode.strip().lower()
    return value not in {"0", "false", "no"}


_PERSONAL_MODE = _personal_mode_enabled()
_payloads: dict[
    str, tuple[dict[str, Any], Any, Optional[str], Optional[str]]
] = {}

# Imported late: the services package resolves ``resualign.api`` during
# import, so this must run only after the module is registered in sys.modules
# (which ``from .state import *`` guarantees in ``resualign/api/__init__.py``).
from .services import workbench as _workbench_service  # noqa: E402

_session_store = _workbench_service.WorkstationSessionStore()
