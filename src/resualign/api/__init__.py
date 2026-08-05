"""FastAPI frontend for ResuAlign.

Provides:
- POST /api/analyze      - queue an analysis job and return its job id
- GET  /api/jobs/{id}    - poll job status, progress, and result
- /api/jobs              - tenant-scoped Job Library CRUD and batch import
- POST /api/auth/*       - signup, login, logout, and current-user lookup
- /api/master-resumes    - versioned Master Resume CRUD and rollback
- /api/applications      - per-tenant application workspace and reruns
- GET  /health           - liveness check
- /                      - static frontend (index.html)
"""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from ..appraisal import compute_appraisal, resume_profile
from ..batch import BatchAlignStore
from ..cache import ContentCache
from ..classifier import classify_job
from ..config import EnvSettings, build_config
from ..crawler import CrawlError, crawl_jd
from ..engine import run
from ..jd_analysis import jd_profile_to_dict, proactive_jd_profile, profile_and_gaps
from ..jd_profiler import profile_jd
from ..job_library import CrawlTaskStore
from ..jobs import JobRegistry
from ..llm import LLMResponseError, OpenAIClient
from ..models import Report
from ..observability import log_event, log_slow_call, new_request_id
from ..parser import (
    SUPPORTED_EXTENSIONS,
    FileParseError,
    extract_text,
    structured_resume_sections,
)
from ..salary import extract_salary_range
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
    _RateLimiter,
    get_current_user,
)
from .schemas import (
    AnalyzeRequest,
    ApplicationCreateRequest,
    ApplicationUpdateRequest,
    BulkStatusRequest,
    FinalDraftRequest,
    JDParseRequest,
    JobCreateRequest,
    JobImportRequest,
    JobUpdateRequest,
    LoginRequest,
    MasterResumeCreateRequest,
    MasterResumeRollbackRequest,
    MasterResumeUpdateRequest,
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
    "ApplicationCreateRequest",
    "ApplicationUpdateRequest",
    "BatchAlignStore",
    "BulkStatusRequest",
    "ContentCache",
    "CrawlError",
    "CrawlTaskStore",
    "EnvSettings",
    "FileParseError",
    "FinalDraftRequest",
    "JDParseRequest",
    "JobCreateRequest",
    "JobImportRequest",
    "JobLibraryStore",
    "JobRegistry",
    "JobUpdateRequest",
    "LLMResponseError",
    "LoginRequest",
    "MasterResumeCreateRequest",
    "MasterResumeRollbackRequest",
    "MasterResumeStore",
    "MasterResumeUpdateRequest",
    "OpenAIClient",
    "Report",
    "SUPPORTED_EXTENSIONS",
    "SettingsStore",
    "SettingsUpdateRequest",
    "SignupRequest",
    "UserStore",
    "UserStoreError",
    "WorkbenchAcceptRequest",
    "WorkbenchRunRequest",
    "_bearer_token",
    "_cancel_batch_align",
    "_enforce_rate_limit",
    "_get_batch_align",
    "_queue_batch_align",
    "build_config",
    "classify_job",
    "compute_appraisal",
    "crawl_jd",
    "extract_salary_range",
    "extract_text",
    "get_current_user",
    "jd_profile_to_dict",
    "log_event",
    "log_slow_call",
    "new_request_id",
    "proactive_jd_profile",
    "profile_and_gaps",
    "profile_jd",
    "resume_profile",
    "rewrite_bullet",
    "run",
    "structured_resume_sections",
]


logger = logging.getLogger(__name__)
_env_settings = EnvSettings()


_auth_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)
_analyze_rate_limiter = _RateLimiter(max_requests=60, window_seconds=60)
_import_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)
_WORKER_SEMAPHORE = threading.BoundedSemaphore(1)
_MAX_IMPORT_ROWS = 200
_MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
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
_cache_db = (
    Path(_env_settings.resualign_job_db).expanduser()
    if _env_settings.resualign_job_db
    else Path(__file__).resolve().parents[2] / "data" / "content-cache.db"
)
_cache = ContentCache(db_path=_cache_db)


def _personal_mode_enabled() -> bool:
    value = _env_settings.resualign_personal_mode.strip().lower()
    return value not in {"0", "false", "no"}


_PERSONAL_MODE = _personal_mode_enabled()
_payloads: dict[
    str, tuple[dict[str, Any], Any, Optional[str], Optional[str]]
] = {}


from .services import batch as _batch_service
from .services import jobs as _jobs_service
from .services import resumes as _resumes_service
from .services import workbench as _workbench_service

_session_store = _workbench_service.WorkstationSessionStore()

_settings_vocabulary = _jobs_service._settings_vocabulary
_classify_job = _jobs_service._classify_job
_derive_title = _jobs_service._derive_title
_crawl_jd_or_502 = _jobs_service._crawl_jd_or_502
_jd_parse_error_detail = _jobs_service._jd_parse_error_detail
_create_job_from_source = _jobs_service._create_job_from_source
_collect_import_rows = _jobs_service._collect_import_rows
_run_import = _jobs_service._run_import
_prune_import_batches = _jobs_service._prune_import_batches
_queue_job = _jobs_service._queue_job
_run_job = _jobs_service._run_job

_report_to_dict = _workbench_service._report_to_dict
_build_diagnosis_section = _workbench_service._build_diagnosis_section
_gap_match_score = _workbench_service._gap_match_score
_read_timeline_extras = _workbench_service._read_timeline_extras
_apply_diffs = _workbench_service._apply_diffs
_library_dedupe_key = _workbench_service._library_dedupe_key

_content_sha256 = _resumes_service._content_sha256
_cached_diagnosis = _resumes_service._cached_diagnosis

_queue_batch_align = _batch_service.queue_batch_align
_get_batch_align = _batch_service.get_batch_align
_cancel_batch_align = _batch_service.cancel_batch_align


def _recover_pending_jobs() -> None:
    """Requeue queued/running jobs left behind by a previous process."""
    for job_id in _registry.pending_job_ids():
        _registry.requeue_interrupted(job_id)
        logger.info("Recovering interrupted analysis job %s", job_id)
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
    recovered_crawls = _crawl_tasks.recover_interrupted()
    if recovered_crawls:
        logger.info("Recovered %s interrupted crawl tasks", recovered_crawls)


@asynccontextmanager
async def lifespan(_: FastAPI):
    _recover_pending_jobs()
    yield


app = FastAPI(title="ResuAlign API", version="0.3.0", lifespan=lifespan)

# Serve the static frontend (index.html) from the root
_static_dir = Path(__file__).resolve().parents[1] / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.middleware("http")
async def _cache_static_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.middleware("http")
async def _request_id_and_slow_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or new_request_id()
    import time as _time

    start = _time.monotonic()
    response = await call_next(request)
    duration_ms = (_time.monotonic() - start) * 1000
    response.headers["X-Request-Id"] = request_id
    log_event(
        logger,
        "http.request",
        request_id=request_id,
        duration_ms=duration_ms,
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
        },
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


from .routers import (
    analyze as _analyze_router,
)
from .routers import (
    applications as _applications_router,
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
    resumes as _resumes_router,
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
parse_jd_preview = _jobs_router.parse_jd_preview
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
get_workbench_appraisal = _jobs_router.get_workbench_appraisal
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
create_application = _applications_router.create_application
list_applications = _applications_router.list_applications
get_application = _applications_router.get_application
update_application = _applications_router.update_application
delete_application = _applications_router.delete_application
run_application = _applications_router.run_application
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


# ---------------------------------------------------------------------------
# Entry point for ``python -m resualign.api``
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    import uvicorn

    host = os.environ.get("RESUALIGN_HOST", "127.0.0.1")
    port = int(os.environ.get("RESUALIGN_PORT", "8000"))
    uvicorn.run("resualign.api:app", host=host, port=port, reload=True)
