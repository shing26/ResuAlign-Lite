"""Mutable application context for process-wide stores and service callbacks.

The API package owns bootstrap order; services read the context at call time
instead of importing the API package. This keeps the service layer independent
from the composition root while preserving the existing test replacement
points through the API package compatibility module.
"""

from __future__ import annotations

import threading
from types import ModuleType
from typing import Any, Optional

from ..batch import BatchAlignStore
from ..cache import ContentCache
from ..config import EnvSettings
from ..jobs import JobRegistry, resolve_data_dir
from ..llm_nodes import LLMNodeStore
from ..llm_usage import LLMUsageStore
from ..observability import log_sample_rate
from ..settings_store import SettingsStore
from ..workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)
from .rate_limit import _RateLimiter


def _clamp_worker_concurrency(value: object) -> int:
    """Validate worker concurrency, failing fast outside the 1..4 range.

    A silently clamped value hides a misconfiguration: an operator who sets
    ``RESUALIGN_WORKER_CONCURRENCY=99`` would otherwise believe 99 workers
    are running while the app quietly uses 4. The error names the variable
    and its legal range so startup logs point straight at the fix.
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "RESUALIGN_WORKER_CONCURRENCY must be an integer in the range "
            f"1..4; got {value!r}"
        ) from exc
    if not 1 <= parsed <= 4:
        raise ValueError(
            "RESUALIGN_WORKER_CONCURRENCY must be in the range 1..4; "
            f"got {parsed}"
        )
    return parsed


class AppContext:
    """Process-wide singletons and late-bound service callbacks."""

    def __init__(self) -> None:
        self._env_settings = EnvSettings()
        # Fail fast on a malformed sampling rate: the request middleware
        # reads it on every call, so a bad env var must surface at startup
        # rather than on the first request.
        log_sample_rate()

        self._auth_rate_limiter = _RateLimiter(
            max_requests=20, window_seconds=60
        )
        self._analyze_rate_limiter = _RateLimiter(
            max_requests=60, window_seconds=60
        )
        self._import_rate_limiter = _RateLimiter(
            max_requests=20, window_seconds=60
        )
        self._WORKER_CONCURRENCY = _clamp_worker_concurrency(
            self._env_settings.resualign_worker_concurrency
        )
        self._WORKER_SEMAPHORE = threading.BoundedSemaphore(
            self._WORKER_CONCURRENCY
        )
        self._MAX_IMPORT_ROWS = 200
        self._MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
        self._MAX_BODY_BYTES = 8 * 1024 * 1024
        self._import_batches: dict[str, dict[str, Any]] = {}
        self._batch_store = BatchAlignStore()
        self._TIMELINE_FIELDS = (
            "applied_at",
            "next_step",
            "notes",
            "offer_at",
            "rejected_at",
            "next_step_due_at",
            "interview_stage",
        )

        self._registry = JobRegistry(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._users = UserStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._resumes = MasterResumeStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._applications = ApplicationStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._jobs = JobLibraryStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._settings_store = SettingsStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._llm_nodes = LLMNodeStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._llm_usage = LLMUsageStore(
            db_path=self._env_settings.resualign_job_db or None
        )
        self._cache_db = resolve_data_dir() / "content-cache.db"
        self._cache = ContentCache(db_path=self._cache_db)
        self._PERSONAL_MODE = self._personal_mode_enabled()
        self._payloads: dict[
            str, tuple[dict[str, Any], Any, Optional[str], Optional[str]]
        ] = {}

        # Bound by ``resualign.api`` after service modules are imported.
        self._session_store: Any = None
        self._jobs_service: ModuleType | None = None
        self._workbench_service: ModuleType | None = None
        self._batch_service: ModuleType | None = None
        self._resumes_service: ModuleType | None = None
        self._resume_optimize_service: ModuleType | None = None
        self._watchdog_service: ModuleType | None = None

    def _personal_mode_enabled(self) -> bool:
        value = self._env_settings.resualign_personal_mode.strip().lower()
        return value not in {"0", "false", "no"}

    def bind_service_layer(
        self,
        *,
        jobs: ModuleType,
        workbench: ModuleType,
        batch: ModuleType,
        resumes: ModuleType,
        resume_optimize: ModuleType,
        watchdog: ModuleType,
    ) -> None:
        """Install service functions after the API bootstrap imports them."""
        self._jobs_service = jobs
        self._workbench_service = workbench
        self._batch_service = batch
        self._resumes_service = resumes
        self._resume_optimize_service = resume_optimize
        self._watchdog_service = watchdog

        self._settings_vocabulary = jobs._settings_vocabulary
        self._classify_job = jobs._classify_job
        self._derive_title = jobs._derive_title
        self._extract_company_location = jobs._extract_company_location
        self._create_job_from_source = jobs._create_job_from_source
        self._deterministic_job_fields = jobs._deterministic_job_fields
        self._local_ingest_job = jobs._local_ingest_job
        self._collect_import_rows = jobs._collect_import_rows
        self._run_import = jobs._run_import
        self._prune_import_batches = jobs._prune_import_batches
        self._queue_job = jobs._queue_job
        self._run_job = jobs._run_job
        self._job_failure_detail = jobs._job_failure_detail
        self._probe_active_llm_quick = jobs._probe_active_llm_quick

        self._report_to_dict = workbench._report_to_dict
        self._build_diagnosis_section = workbench._build_diagnosis_section
        self._gap_match_score = workbench._gap_match_score
        self._read_timeline_extras = workbench._read_timeline_extras
        self._apply_diffs = workbench._apply_diffs
        self._alignment_notice = workbench.alignment_notice
        self._library_dedupe_key = workbench._library_dedupe_key

        self._content_sha256 = resumes._content_sha256
        self._cached_diagnosis = resumes._cached_diagnosis
        self._backfill_diagnosis_snapshots = (
            resumes.backfill_diagnosis_snapshots
        )
        self.extract_resume_profile = resumes.extract_resume_profile

        self._run_resume_optimize = resume_optimize.run_resume_optimize
        self.apply_resume_optimize_items = (
            resume_optimize.apply_resume_optimize_items
        )

        self._queue_batch_align = batch.queue_batch_align
        self._get_batch_align = batch.get_batch_align
        self._cancel_batch_align = batch.cancel_batch_align

        if self._session_store is None:
            self._session_store = workbench.WorkstationSessionStore()

    def bind_names(self, namespace: dict[str, Any]) -> None:
        """Expose API bootstrap callables to services without a reverse import."""
        names = (
            "AnalyzeRequest",
            "FileParseError",
            "JobCreateRequest",
            "JobImportRequest",
            "JobUpdateRequest",
            "LLMResponseError",
            "MasterResumeCreateRequest",
            "MasterResumeRollbackRequest",
            "MasterResumeUpdateRequest",
            "OpenAIClient",
            "Report",
            "SUPPORTED_EXTENSIONS",
            "UserStoreError",
            "_enforce_rate_limit",
            "analyze_gaps",
            "build_config",
            "check_daily_llm_cap",
            "classify_job",
            "compute_match_score",
            "enforce_daily_llm_cap",
            "enforce_llm_task_entry",
            "extract_text",
            "fallback_match_reason",
            "jd_profile_to_dict",
            "job_status",
            "llm_daily_status",
            "proactive_jd_profile",
            "profile_jd",
            "record_daily_llm_usage",
            "rewrite_bullet",
            "run",
            "snapshot_matches",
            "structured_resume_sections",
        )
        for name in names:
            if name in namespace:
                setattr(self, name, namespace[name])


context = AppContext()


def get_context() -> AppContext:
    """Return the process-wide application context."""
    return context
