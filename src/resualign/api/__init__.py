"""FastAPI frontend for ResuAlign.

Provides:
- POST /api/analyze      - queue an analysis job and return its job id
- GET  /api/jobs/{id}    - poll job status, progress, and result
- /api/jobs              - tenant-scoped Job Library CRUD and batch import
- POST /api/auth/*       - signup, login, logout, and current-user lookup
- /api/master-resumes    - versioned Master Resume CRUD and rollback
- /api/applications      - dormant per-tenant application records and reruns
- GET  /health           - liveness check
- /                      - static frontend (index.html)
"""

from __future__ import annotations

import logging
import logging.config
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from ..alignment_lifecycle import transition_alignment
from ..batch import BatchAlignStore
from ..cache import ContentCache
from ..classifier import classify_job
from ..config import EnvSettings, build_config
from ..engine import run
from ..gap_analyzer import analyze_gaps
from ..jd_analysis import jd_profile_to_dict, proactive_jd_profile
from ..jd_profiler import profile_jd
from ..jobs import JobRegistry, resolve_data_dir
from ..llm import LLMResponseError, OpenAIClient, register_daily_usage_recorder
from ..match_scorer import compute_match_score, fallback_match_reason, snapshot_matches
from ..models import Report
from ..observability import (
    RedactingFilter,
    log_event,
    log_sample_rate,
    log_slow_call,
    new_request_id,
    should_sample,
)
from ..parser import (
    SUPPORTED_EXTENSIONS,
    FileParseError,
    extract_text,
    structured_resume_sections,
)
from ..settings_store import SettingsStore
from ..tailor import rewrite_bullet
from ..workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
    UserStoreError,
)
from .deps import (
    _bearer_token,
    _enforce_rate_limit,
    get_current_user,
)
from .schemas import (
    AnalyzeRequest,
    AutomationRuleCreateRequest,
    AutomationRuleUpdateRequest,
    BulkStatusRequest,
    FinalDraftRequest,
    JobCreateRequest,
    JobImportRequest,
    JobUpdateRequest,
    LocalIngestRequest,
    LoginRequest,
    MasterResumeCreateRequest,
    MasterResumeRollbackRequest,
    MasterResumeUpdateRequest,
    OptimizeApplyItem,
    OptimizeApplyRequest,
    OptimizeRequest,
    SettingsUpdateRequest,
    SignupRequest,
    WorkbenchAcceptRequest,
    WorkbenchRunRequest,
)

# Re-exported names: routers/services access these as `resualign.api.X`
# (`import resualign.api as api_module`), so they must stay importable here.
__all__ = [
    "ApplicationStore",
    "AnalyzeRequest",
    "AutomationRuleCreateRequest",
    "AutomationRuleUpdateRequest",
    "BatchAlignStore",
    "BulkStatusRequest",
    "ContentCache",
    "EnvSettings",
    "FileParseError",
    "FinalDraftRequest",
    "JobCreateRequest",
    "JobImportRequest",
    "JobLibraryStore",
    "JobRegistry",
    "JobUpdateRequest",
    "LocalIngestRequest",
    "LLMResponseError",
    "compute_match_score",
    "fallback_match_reason",
    "LoginRequest",
    "MasterResumeCreateRequest",
    "MasterResumeRollbackRequest",
    "MasterResumeStore",
    "MasterResumeUpdateRequest",
    "OpenAIClient",
    "OptimizeApplyItem",
    "OptimizeApplyRequest",
    "OptimizeRequest",
    "Report",
    "RuleFilterEngine",
    "RuleVerdict",
    "SUPPORTED_EXTENSIONS",
    "SettingsStore",
    "SettingsUpdateRequest",
    "SignupRequest",
    "snapshot_matches",
    "UserStore",
    "UserStoreError",
    "WorkbenchAcceptRequest",
    "WorkbenchRunRequest",
    "_bearer_token",
    "_cancel_batch_align",
    "_enforce_rate_limit",
    "_get_batch_align",
    "_queue_batch_align",
    "_run_resume_optimize",
    "apply_resume_optimize_items",
    "build_config",
    "classify_job",
    "enforce_daily_llm_cap",
    "enforce_llm_task_entry",
    "extract_text",
    "get_current_user",
    "jd_profile_to_dict",
    "llm_daily_status",
    "log_event",
    "log_slow_call",
    "new_request_id",
    "proactive_jd_profile",
    "profile_jd",
    "analyze_gaps",
    "rewrite_bullet",
    "run",
    "structured_resume_sections",
]


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Logging configuration (Ticket #13)
# ---------------------------------------------------------------------------
# Process-wide dictConfig applied exactly once at import time (NOT in the
# lifespan, which tests trigger repeatedly). Root logger gets a console
# handler (INFO) and a UTF-8 rotating file handler at
# ``<RESUALIGN_LOG_DIR>/app.log`` (10 MB x 5 backups, default
# ``<data dir>/logs``). Every structured ``log_event`` line passes through a
# redacting filter before it is emitted, and http.request events are sampled
# per request via RESUALIGN_LOG_SAMPLE_RATE (see ``_request_id_and_slow_log``).

_LOGGING_CONFIGURED = False
_APP_LOG_MAX_BYTES = 10 * 1024 * 1024
_APP_LOG_BACKUP_COUNT = 5


def _configure_logging() -> None:
    """Configure process-wide logging, idempotently (runs once per process).

    Re-entry safe: repeated calls and repeated module imports never stack
    extra handlers. The log directory is created on demand.
    """
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    _LOGGING_CONFIGURED = True
    log_dir = Path(
        os.environ.get("RESUALIGN_LOG_DIR") or (resolve_data_dir() / "logs")
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                },
            },
            "filters": {
                "redact": {"()": RedactingFilter},
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "default",
                    "filters": ["redact"],
                },
                "app_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "level": "INFO",
                    "formatter": "default",
                    "filters": ["redact"],
                    "filename": str(log_file),
                    "maxBytes": _APP_LOG_MAX_BYTES,
                    "backupCount": _APP_LOG_BACKUP_COUNT,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["console", "app_file"],
            },
        }
    )


_configure_logging()

# Process-wide state (store singletons, rate limiters, constants) lives in
# state.py and is re-exported here so `api_module._registry` and friends keep
# working, and tests can swap attributes on this package module directly.
# I001: state must be imported before the services package, whose modules
# resolve ``resualign.api`` during import.
from .state import *  # noqa: E402, F401, F403, I001
from .state import (  # noqa: F401, I001  (explicit bindings used below)
    _PERSONAL_MODE,
    _MAX_BODY_BYTES,
    _WORKER_CONCURRENCY,
    _WORKER_SEMAPHORE,
    _cache,
    _jobs,
    _registry,
    _settings_store,
)


from .services import batch as _batch_service
from .services import jobs as _jobs_service
from .services import resumes as _resumes_service
from .services import resume_optimize as _resume_optimize_service
from .services import workbench as _workbench_service
from .services.cost_guard import (
    enforce_daily_llm_cap,
    enforce_llm_task_entry,
    llm_daily_status,
    record_daily_llm_usage,
)

from ..rules import RuleFilterEngine, RuleVerdict  # noqa: E402

_settings_vocabulary = _jobs_service._settings_vocabulary
_classify_job = _jobs_service._classify_job
_derive_title = _jobs_service._derive_title
_extract_company_location = _jobs_service._extract_company_location
_create_job_from_source = _jobs_service._create_job_from_source
_deterministic_job_fields = _jobs_service._deterministic_job_fields
_local_ingest_job = _jobs_service._local_ingest_job
_collect_import_rows = _jobs_service._collect_import_rows
_run_import = _jobs_service._run_import
_prune_import_batches = _jobs_service._prune_import_batches
_queue_job = _jobs_service._queue_job
_run_job = _jobs_service._run_job
_job_failure_detail = _jobs_service._job_failure_detail
_probe_active_llm_quick = _jobs_service._probe_active_llm_quick

_report_to_dict = _workbench_service._report_to_dict
_build_diagnosis_section = _workbench_service._build_diagnosis_section
_gap_match_score = _workbench_service._gap_match_score
_read_timeline_extras = _workbench_service._read_timeline_extras
_apply_diffs = _workbench_service._apply_diffs
_alignment_notice = _workbench_service.alignment_notice
_library_dedupe_key = _workbench_service._library_dedupe_key

_content_sha256 = _resumes_service._content_sha256
_cached_diagnosis = _resumes_service._cached_diagnosis
_backfill_diagnosis_snapshots = _resumes_service.backfill_diagnosis_snapshots

_run_resume_optimize = _resume_optimize_service.run_resume_optimize
apply_resume_optimize_items = _resume_optimize_service.apply_resume_optimize_items

_queue_batch_align = _batch_service.queue_batch_align
_get_batch_align = _batch_service.get_batch_align
_cancel_batch_align = _batch_service.cancel_batch_align


def _recover_stale_alignments() -> None:
    """Flag library jobs whose analysis job reached a terminal state without
    a persisted alignment product (crash between save_alignment and the
    registry transition, or a failed save in the old commit order).

    Alignment fields are preserved so the UI keeps the last product while
    marking the job rerunnable.
    """
    for job in _jobs.list_alignment_pending():
        workbench_job_id = job.get('workbench_job_id')
        if workbench_job_id:
            registry_job = _registry.get(workbench_job_id)
            if registry_job is not None and registry_job.status in (
                'queued',
                'running',
            ):
                # Still in flight; the requeue path below owns it.
                continue
        transition_alignment(
            _jobs,
            job['tenant_id'],
            job['job_id'],
            'failed',
        )
        logger.info(
            'Marked library job %s alignment failed: registry job %s is '
            'terminal/missing while alignment_status was %s; user can rerun',
            job['job_id'],
            workbench_job_id,
            job.get('alignment_status'),
        )


def _recover_pending_jobs() -> None:
    """Requeue queued/running jobs left behind by a previous process."""
    _recover_stale_alignments()
    for job_id in _registry.pending_job_ids():
        _registry.requeue_interrupted(job_id)
        logger.info("Recovering interrupted analysis job %s", job_id)
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "Runtime data directory: %s (job db: %s, cache db: %s)",
        resolve_data_dir(),
        _registry.db_path,
        _cache.db_path,
    )
    logger.info(
        "Analysis worker concurrency: %s (RESUALIGN_WORKER_CONCURRENCY=1 means serial)",
        _WORKER_CONCURRENCY,
    )
    if _PERSONAL_MODE:
        _settings_store.get_or_create_local_ingest_token("local")
    register_daily_usage_recorder(record_daily_llm_usage)
    _backfill_diagnosis_snapshots()
    _recover_pending_jobs()
    try:
        yield
    finally:
        pass


app = FastAPI(title="ResuAlign API", version="0.3.0", lifespan=lifespan)

# Serve the static frontend (index.html) from the root
_static_dir = Path(__file__).resolve().parents[1] / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.middleware("http")
async def _cache_static_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        path = request.url.path
        if path in ("/static/index.html",) or path.startswith("/static/app/"):
            # ESM entry and modules have no build-time hash; force
            # revalidation so a new deploy never mixes old/new modules.
            response.headers["Cache-Control"] = "no-cache"
        else:
            response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.middleware("http")
async def _limit_request_body_size(request: Request, call_next):
    """Reject oversized request bodies before routing (A9 input caps).

    Uses the Content-Length header when present; chunked/unknown sizes are
    left to the route-level Pydantic field limits.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_BODY_BYTES:
                from fastapi.responses import JSONResponse

                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            "Request body too large (max "
                            f"{_MAX_BODY_BYTES} bytes)"
                        )
                    },
                )
        except ValueError:
            pass
    return await call_next(request)


@app.middleware("http")
async def _request_id_and_slow_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or new_request_id()
    import time as _time

    start = _time.monotonic()
    response = await call_next(request)
    duration_ms = (_time.monotonic() - start) * 1000
    response.headers["X-Request-Id"] = request_id
    extra = {
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
    }
    # http.request is sampled (default 1%) to keep log volume bounded;
    # http.slow is always recorded so slow requests are never lost.
    if should_sample(log_sample_rate()):
        log_event(
            logger,
            "http.request",
            request_id=request_id,
            duration_ms=duration_ms,
            extra=extra,
        )
    log_slow_call(
        logger,
        "http.slow",
        duration_ms,
        threshold_ms=3000,
        request_id=request_id,
        extra={"method": request.method, "path": request.url.path},
    )
    return response


from .routers import router as api_router

app.include_router(api_router)

from .routers import batch as _batch_router

app.include_router(_batch_router.router)


from .routers import dashboard as _dashboard_router

app.include_router(_dashboard_router.router)


from .routers import ops as _ops_router

app.include_router(_ops_router.router)


from .routers import (
    analyze as _analyze_router,
)
from .routers import (
    auth as _auth_router,
)
from .routers import (
    batch as _batch_router_alias,
)
from .routers import (
    health as _health_router,
)
from .routers import (
    jobs as _jobs_router,
)
from .routers import (
    kanban as _kanban_router,
)
from .routers import (
    nodes as _nodes_router,
)
from .routers import (
    optimize as _optimize_router,
)
from .routers import (
    resumes as _resumes_router,
)
from .routers import (
    rules as _rules_router,
)
from .routers import (
    settings as _settings_router,
)
from .routers import (
    workspace as _workspace_router,
)

index = _health_router.index
health = _health_router.health
analyze = _analyze_router.analyze
create_library_job = _jobs_router.create_library_job
import_library_jobs = _jobs_router.import_library_jobs
import_status = _jobs_router.import_status
list_library_jobs = _jobs_router.list_library_jobs
get_library_job = _jobs_router.get_library_job
cancel_analysis_job = _jobs_router.cancel_analysis_job
reclassify_library_job = _jobs_router.reclassify_library_job
save_final_draft = _jobs_router.save_final_draft
update_library_job = _jobs_router.update_library_job
bulk_update_job_status = _jobs_router.bulk_update_job_status
delete_library_job = _jobs_router.delete_library_job
run_workbench = _jobs_router.run_workbench
accept_workbench_diffs = _jobs_router.accept_workbench_diffs
preanalyze_library_job = _jobs_router.preanalyze_library_job
rewrite_workbench_bullet = _jobs_router.rewrite_workbench_bullet
job_status = _jobs_router.job_status
signup = _auth_router.signup
login = _auth_router.login
logout = _auth_router.logout
me = _auth_router.me
create_master_resume = _resumes_router.create_master_resume
parse_resume_upload = _resumes_router.parse_resume_upload
list_master_resumes = _resumes_router.list_master_resumes
get_master_resume = _resumes_router.get_master_resume
diagnose_master_resume = _resumes_router.diagnose_master_resume
update_master_resume = _resumes_router.update_master_resume
rollback_master_resume = _resumes_router.rollback_master_resume
delete_master_resume = _resumes_router.delete_master_resume
get_settings = _settings_router.get_settings
update_settings = _settings_router.update_settings
create_batch_align = _batch_router_alias.create_batch_align
get_batch_align_status = _batch_router_alias.get_batch_align_status
cancel_batch_align = _batch_router_alias.cancel_batch_align
init_workbench_session = _workspace_router.init_workbench_session
get_workbench_session = _workspace_router.get_workbench_session
get_workspace_session = _workspace_router.get_workspace_session
stream_workbench_events = _workspace_router.stream_workbench_events
bulk_update_kanban_status = _kanban_router.bulk_update_kanban_status
list_automation_rules = _rules_router.list_automation_rules
create_automation_rule = _rules_router.create_automation_rule
update_automation_rule = _rules_router.update_automation_rule
delete_automation_rule = _rules_router.delete_automation_rule
list_llm_nodes = _nodes_router.list_llm_nodes
create_llm_node = _nodes_router.create_llm_node
update_llm_node = _nodes_router.update_llm_node
delete_llm_node = _nodes_router.delete_llm_node
activate_llm_node = _nodes_router.activate_llm_node
test_llm_node = _nodes_router.test_llm_node
optimize_master_resume = _optimize_router.optimize_master_resume
apply_resume_optimize = _optimize_router.apply_resume_optimize


# ---------------------------------------------------------------------------
# Entry point for ``python -m resualign.api``
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    import uvicorn

    host = os.environ.get("RESUALIGN_HOST", "127.0.0.1")
    port = int(os.environ.get("RESUALIGN_PORT", "8000"))
    uvicorn.run("resualign.api:app", host=host, port=port, reload=True)
