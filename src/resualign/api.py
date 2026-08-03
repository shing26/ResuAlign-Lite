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

import csv
import hashlib
import io
import logging
import re
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import EnvSettings, build_config
from .appraisal import compute_appraisal, resume_profile
from .classifier import classify_job
from .crawler import CrawlError, crawl_jd
from .engine import run
from .jobs import JobRegistry
from .llm import LLMResponseError, OpenAIClient
from .models import Report
from .parser import SUPPORTED_EXTENSIONS, FileParseError, extract_text
from .salary import extract_salary_range
from .settings_store import SettingsStore
from .workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
    UserStoreError,
)


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    resume_text: str
    jd_text: str | None = None
    jd_url: str | None = None
    run_eval: bool = False
    granularity: Literal["fine", "medium", "coarse"] = "medium"
    prompt_focus: Literal["balanced", "quantified", "skills"] = "balanced"


def _report_to_dict(report: Report) -> dict:
    """Convert the Report dataclass tree to a plain JSON-safe dict."""
    from dataclasses import asdict
    return asdict(report)


def _build_diagnosis_section(result: dict[str, Any]) -> dict[str, Any]:
    """Expose the no-JD diagnosis as a dedicated, self-contained section.

    engine.run() only returns score/skills/issues, so the suggestion list is
    derived from the same issues to keep the diagnosis card complete without
    changing the LLM prompt or report model.
    """
    issues = result.get("issues") or []
    return {
        "score": result.get("score", 0),
        "skills": result.get("skills") or [],
        "issues": issues,
        "suggestions": [f"建议：{issue}" for issue in issues],
        "model": result.get("model", ""),
        "elapsed_seconds": result.get("elapsed_seconds", 0),
    }


def _gap_match_score(result: dict[str, Any]) -> Optional[float]:
    """Derive a JD-specific match score from gap analysis when no eval ran."""
    gap = result.get("gap_report") or {}
    missing = len(gap.get("missing_keywords") or [])
    if not missing:
        return 90.0
    return max(30.0, 100.0 - missing * 15.0)


def _content_sha256(text: str) -> str:
    """Return a stable content fingerprint for the diagnosis cache."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _cached_diagnosis(
    resume: dict[str, Any],
    config: Any,
    tenant_id: str,
) -> Optional[dict[str, Any]]:
    """Reuse a previous diagnosis when resume content and model match."""
    latest_job_id = resume.get("latest_diagnosis_job_id")
    if not latest_job_id:
        return None
    snapshot = _registry.snapshot(latest_job_id, tenant_id=tenant_id)
    if snapshot is None or snapshot.get("status") != "succeeded":
        return None
    result = snapshot.get("result") or {}
    if result.get("diagnosis_source_hash") != _content_sha256(
        resume.get("content") or ""
    ):
        return None
    diag = result.get("diagnosis") or {}
    if diag.get("model") != config.model:
        return None
    return {
        "score": diag.get("score", 0),
        "skills": diag.get("skills") or [],
        "issues": diag.get("issues") or [],
    }


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
_env_settings = EnvSettings()


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


_auth_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)
_analyze_rate_limiter = _RateLimiter(max_requests=60, window_seconds=60)
_import_rate_limiter = _RateLimiter(max_requests=20, window_seconds=60)
_WORKER_SEMAPHORE = threading.BoundedSemaphore(2)
_MAX_IMPORT_ROWS = 200
_MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
_import_batches: dict[str, dict[str, Any]] = {}


def _recover_pending_jobs() -> None:
    """Requeue queued/running jobs left behind by a previous process."""
    for job_id in _registry.pending_job_ids():
        logger.info("Recovering interrupted analysis job %s", job_id)
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    _recover_pending_jobs()
    yield


app = FastAPI(title="ResuAlign API", version="0.3.0", lifespan=lifespan)

# Serve the static frontend (index.html) from the root
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.middleware("http")
async def _cache_static_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


_registry = JobRegistry(db_path=_env_settings.resualign_job_db or None)
_users = UserStore(db_path=_env_settings.resualign_job_db or None)
_resumes = MasterResumeStore(db_path=_env_settings.resualign_job_db or None)
_applications = ApplicationStore(
    db_path=_env_settings.resualign_job_db or None
)
_jobs = JobLibraryStore(db_path=_env_settings.resualign_job_db or None)
_settings_store = SettingsStore(db_path=_env_settings.resualign_job_db or None)


def _personal_mode_enabled() -> bool:
    value = _env_settings.resualign_personal_mode.strip().lower()
    return value not in {"0", "false", "no"}


_PERSONAL_MODE = _personal_mode_enabled()
_payloads: dict[
    str, tuple[dict[str, Any], Any, Optional[str], Optional[str]]
] = {}


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class MasterResumeCreateRequest(BaseModel):
    title: str
    content: str


class MasterResumeUpdateRequest(BaseModel):
    content: str


class MasterResumeRollbackRequest(BaseModel):
    version: int


class ApplicationCreateRequest(BaseModel):
    title: str
    master_resume_id: str
    jd_text: str | None = None
    jd_url: str | None = None


class ApplicationUpdateRequest(BaseModel):
    title: str | None = None
    jd_text: str | None = None
    jd_url: str | None = None
    status: str | None = None


class JobCreateRequest(BaseModel):
    title: str | None = None
    jd_text: str | None = None
    jd_url: str | None = None
    company: str | None = None
    location: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    job_function: str | None = None
    seniority: str | None = None
    tech_tags: list[str] | None = None
    status: str | None = None
    posting_date: str | None = None


class JDParseRequest(BaseModel):
    jd_url: str


class JobUpdateRequest(BaseModel):
    title: str | None = None
    jd_text: str | None = None
    company: str | None = None
    location: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    source_type: str | None = None
    source_url: str | None = None
    job_function: str | None = None
    seniority: str | None = None
    tech_tags: list[str] | None = None
    status: str | None = None
    posting_date: str | None = None
    tailor_granularity: Literal["fine", "medium", "coarse"] | None = None
    tailor_focus: Literal["balanced", "quantified", "skills"] | None = None
    custom_prompt: str | None = None


class JobImportRequest(BaseModel):
    jobs: list[dict[str, Any]] | None = None
    csv_text: str | None = None


class SettingsUpdateRequest(BaseModel):
    salary_reference: list[dict[str, Any]] | None = None
    appraisal_weights: dict[str, float] | None = None
    classification_vocabulary: dict[str, list[str]] | None = None


class WorkbenchRunRequest(BaseModel):
    master_resume_id: str
    granularity: Literal["fine", "medium", "coarse"] = "medium"
    prompt_focus: Literal["balanced", "quantified", "skills"] = "balanced"
    custom_prompt: str | None = None


class WorkbenchAcceptRequest(BaseModel):
    job_id: str
    accepted_indices: list[int] = []


class FinalDraftRequest(BaseModel):
    draft: str


def _bearer_token(authorization: str = Header(default="")) -> Optional[str]:
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    return token or None


def _enforce_rate_limit(request: Request, limiter: _RateLimiter) -> None:
    """Reject requests that exceed the limiter's per-client budget."""
    key = request.client.host if request.client else "unknown"
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="Too many requests, please try again later",
        )


def get_current_user(
    token: Optional[str] = Depends(_bearer_token),
) -> dict[str, Any]:
    """Resolve the bearer token to a user, raising 401 when invalid."""
    if token is not None:
        user = _users.user_for_token(token)
        if user is not None:
            return user
    elif _PERSONAL_MODE:
        return _users.get_or_create_personal_user()
    else:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raise HTTPException(
        status_code=401,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.get("/", response_class=HTMLResponse)
def index():
    """Serve the frontend HTML."""
    if not _static_dir.is_dir():
        return HTMLResponse(
            "<h1>ResuAlign API</h1><p>Frontend not available.</p>"
        )
    return HTMLResponse(
        (_static_dir / "index.html").read_text(encoding="utf-8")
    )


@app.get("/health")
def health():
    """Liveness probe."""
    return {"status": "ok"}


def _settings_vocabulary(user_id: str) -> tuple[list[str], list[str]]:
    """Return the tenant's editable classification vocabulary."""
    vocabulary = _settings_store.get_settings(user_id)[
        "classification_vocabulary"
    ]
    return (
        [str(item) for item in (vocabulary.get("job_functions") or [])],
        [str(item) for item in (vocabulary.get("seniorities") or [])],
    )


def _classify_job(
    jd_text: str,
    job_functions: list[str] | None = None,
    seniorities: list[str] | None = None,
) -> dict[str, Any]:
    """Classify a JD using the configured LLM client."""
    config = build_config()
    with OpenAIClient(config, timeout=45.0) as client:
        return classify_job(
            client,
            jd_text,
            job_functions=job_functions,
            seniorities=seniorities,
        )


def _derive_title(jd_text: str) -> str:
    """Derive a job title from the first non-empty JD line."""
    for line in (jd_text or "").splitlines():
        candidate = line.strip().lstrip("#-*·• ").strip()
        if candidate:
            return candidate[:120]
    return "未命名岗位"


def _crawl_jd_or_502(
    jd_url: str, meta: dict[str, Any] | None = None
) -> str:
    """Crawl a JD URL, mapping crawler failures to a stable 502 response."""
    try:
        return crawl_jd(jd_url, meta=meta)
    except CrawlError as exc:
        logger.warning("JD crawl failed for %s: %s", jd_url, exc)
        raise HTTPException(
            status_code=502,
            detail=_jd_parse_error_detail(exc),
        ) from exc


def _jd_parse_error_detail(exc: CrawlError) -> dict[str, str]:
    """Map a crawl failure to a user-actionable, non-leaking classification."""
    message = str(exc.args[0]) if exc.args else str(exc)
    lowered = message.lower()
    if exc.category == "url":
        if "private or local" in lowered or "not globally routable" in lowered:
            return {
                "code": "blocked_by_policy",
                "reason": "该链接被安全策略拦截，可能是内网地址或非公开招聘页",
                "action": "请确认链接为公开职位页，或改用粘贴 JD",
            }
        return {
            "code": "invalid_url",
            "reason": "链接格式无效，请输入有效的 https:// 招聘链接",
            "action": "请检查链接后重试，或改用粘贴 JD",
        }
    if exc.category == "dns":
        return {
            "code": "network_error",
            "reason": "无法解析目标站点，可能是网络问题或链接已失效",
            "action": "请确认链接可访问，或改用粘贴 JD",
        }
    if exc.category in ("empty", "selector"):
        return {
            "code": "no_content",
            "reason": "该站点无法直接读取正文，可能需要登录或动态加载",
            "action": "请改用粘贴 JD 或更换链接重试",
        }
    if exc.category == "fetch":
        if "timeout" in lowered or "timed out" in lowered:
            return {
                "code": "timeout",
                "reason": "链接解析超时，站点可能暂时不可用",
                "action": "请改用粘贴 JD 或稍后重试",
            }
        return {
            "code": "network_error",
            "reason": "无法连接到目标站点，可能是网络问题或站点暂时不可用",
            "action": "请改用粘贴 JD 或稍后重试",
        }
    if exc.category == "http":
        if "too many redirects" in lowered:
            return {
                "code": "site_error",
                "reason": "站点重定向异常，无法完成解析",
                "action": "请改用粘贴 JD 或更换链接重试",
            }
        status_match = re.search(r"HTTP (\d{3})", message)
        status = int(status_match.group(1)) if status_match else None
        if status in (401, 403):
            return {
                "code": "login_required",
                "reason": "该站点需要登录或权限，无法直接读取正文",
                "action": "请改用粘贴 JD 或更换链接重试",
            }
        return {
            "code": "site_error",
            "reason": "目标站点返回错误，暂时无法解析正文",
            "action": "请改用粘贴 JD 或稍后重试",
        }
    return {
        "code": "site_error",
        "reason": "未能解析该岗位链接",
        "action": "请改用粘贴 JD 或稍后重试",
    }


def _create_job_from_source(
    user: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Crawl/derive/extract/classify one job and store it in the library."""
    jd_text = (payload.get("jd_text") or "").strip()
    jd_url = (payload.get("jd_url") or "").strip()
    if jd_url and not jd_text:
        jd_text = crawl_jd(jd_url)
    if not jd_text:
        raise UserStoreError("Job description text is required")

    title = (payload.get("title") or "").strip() or _derive_title(jd_text)
    salary_min = payload.get("salary_min")
    salary_max = payload.get("salary_max")
    if salary_min is None or salary_max is None:
        extracted_min, extracted_max = extract_salary_range(jd_text)
        salary_min = salary_min if salary_min is not None else extracted_min
        salary_max = salary_max if salary_max is not None else extracted_max

    job_functions, seniorities = _settings_vocabulary(user["user_id"])
    classification = {}
    classification_pending = 0
    try:
        classification = _classify_job(jd_text, job_functions, seniorities)
    except LLMResponseError as exc:
        logger.warning(
            "Job classification failed, storing as pending: %s", exc
        )
        classification_pending = 1
    source_type = payload.get("source_type") or ("url" if jd_url else "paste")
    job_function = (
        payload.get("job_function")
        or classification.get("job_function")
    )
    seniority = payload.get("seniority") or classification.get("seniority")
    return _jobs.create_job(
        tenant_id=user["user_id"],
        title=title,
        jd_text=jd_text,
        company=payload.get("company"),
        location=payload.get("location"),
        salary_min=salary_min,
        salary_max=salary_max,
        salary_currency=payload.get("salary_currency") or "CNY",
        source_type=source_type,
        source_url=payload.get("source_url") or (jd_url or None),
        job_function=job_function,
        seniority=seniority,
        tech_tags=(
            payload.get("tech_tags")
            or classification.get("tech_tags")
            or []
        ),
        status=payload.get("status") or "未投递",
        classification_pending=classification_pending,
        posting_date=payload.get("posting_date"),
        allowed_job_functions=job_functions,
        allowed_seniorities=seniorities,
    )


@app.post("/api/analyze", status_code=202)
def analyze(
    req: AnalyzeRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue a full ResuAlign pipeline run and return immediately."""
    _enforce_rate_limit(request, _analyze_rate_limiter)
    if not build_config().api_key:
        raise HTTPException(
            status_code=503,
            detail="API key not configured. "
                   "Set via .env file or environment variables.",
        )

    job_id = _queue_job(user, req.model_dump())
    return {"job_id": job_id, "status": "queued"}


def _queue_job(
    user: dict[str, Any],
    payload: dict[str, Any],
    application_id: str | None = None,
    workbench: bool = False,
) -> str:
    """Create a job row, keep its payload in memory, and start the worker."""
    config = build_config()
    job = _registry.create(
        payload,
        config,
        tenant_id=user["user_id"],
        application_id=application_id,
    )
    payload["workbench"] = workbench
    _payloads[job.job_id] = (
        payload,
        config,
        application_id,
        user["user_id"],
    )
    if application_id:
        _applications.set_application_job(
            user["user_id"], application_id, job.job_id, "running"
        )
    threading.Thread(target=_run_job, args=(job.job_id,), daemon=True).start()
    return job.job_id


@app.post("/api/jobs", status_code=201)
def create_library_job(
    req: JobCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Ingest one job from pasted text or a JD URL."""
    _enforce_rate_limit(request, _import_rate_limiter)
    if not (req.jd_text or "").strip() and not (req.jd_url or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Either jd_text or jd_url is required",
        )
    try:
        return _create_job_from_source(
            user,
            {
                "title": req.title,
                "jd_text": req.jd_text,
                "jd_url": req.jd_url,
                "company": req.company,
                "location": req.location,
                "salary_min": req.salary_min,
                "salary_max": req.salary_max,
                "salary_currency": req.salary_currency,
                "source_type": req.source_type,
                "source_url": req.source_url,
                "job_function": req.job_function,
                "seniority": req.seniority,
                "tech_tags": req.tech_tags,
                "status": req.status,
                "posting_date": req.posting_date,
            },
        )
    except CrawlError as exc:
        raise HTTPException(
            status_code=502,
            detail=_jd_parse_error_detail(exc),
        ) from exc
    except UserStoreError as exc:
        if "Duplicate job" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/jobs/parse-jd")
def parse_jd_preview(
    req: JDParseRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Crawl a JD URL and return a preview without creating a job."""
    _enforce_rate_limit(request, _import_rate_limiter)
    jd_url = req.jd_url.strip()
    if not jd_url:
        raise HTTPException(status_code=422, detail="jd_url is required")
    meta: dict[str, Any] = {}
    jd_text = _crawl_jd_or_502(jd_url, meta=meta)
    salary_min, salary_max = extract_salary_range(jd_text)
    has_salary = salary_min is not None or salary_max is not None
    return {
        "title": meta.get("title") or _derive_title(jd_text),
        "jd_text": jd_text,
        "company": meta.get("company"),
        "city": meta.get("city"),
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_currency": "CNY" if has_salary else None,
        "source_url": jd_url,
    }


def _collect_import_rows(req: JobImportRequest) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = list(req.jobs or [])
    if (req.csv_text or "").strip():
        reader = csv.DictReader(io.StringIO(req.csv_text))
        for row in reader:
            rows.append({key: (value or None) for key, value in row.items()})
    return rows


def _run_import(import_id: str) -> None:
    """Process a queued import batch on a daemon worker thread."""
    batch = _import_batches.get(import_id)
    if batch is None:
        return
    user = {"user_id": batch["user_id"]}
    try:
        for row in batch["rows"]:
            if not (row.get("jd_text") or "").strip() and not (
                row.get("jd_url") or ""
            ).strip():
                batch["skipped"] += 1
                batch["errors"].append(
                    f"{row.get('title') or 'Untitled'}: empty JD"
                )
                continue
            try:
                _create_job_from_source(user, row)
                batch["created"] += 1
            except (UserStoreError, CrawlError, LLMResponseError) as exc:
                batch["skipped"] += 1
                batch["errors"].append(
                    f"{row.get('title') or 'Untitled'}: {exc}"
                )
    except Exception as exc:
        logger.exception("Import batch %s failed", import_id)
        batch["errors"].append(f"Import batch failed: {exc}")
    finally:
        batch["done"] = True
        _prune_import_batches()


def _prune_import_batches(max_kept: int = 50) -> None:
    """Drop finished import batches once the in-memory backlog grows."""
    done_ids = [
        import_id
        for import_id, batch in _import_batches.items()
        if batch.get("done")
    ]
    if len(done_ids) <= max_kept:
        return
    for import_id in sorted(done_ids)[: len(done_ids) - max_kept]:
        _import_batches.pop(import_id, None)


@app.post("/api/jobs/import")
def import_library_jobs(
    req: JobImportRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue a batch import so crawl/classification never blocks the API."""
    _enforce_rate_limit(request, _import_rate_limiter)
    rows = _collect_import_rows(req)
    if not rows:
        return {"queued": False, "total": 0, "created": 0, "skipped": 0}
    if len(rows) > _MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"Import exceeds maximum of {_MAX_IMPORT_ROWS} rows",
        )
    import_id = uuid.uuid4().hex
    _import_batches[import_id] = {
        "user_id": user["user_id"],
        "rows": rows,
        "created": 0,
        "skipped": 0,
        "errors": [],
        "done": False,
    }
    threading.Thread(
        target=_run_import, args=(import_id,), daemon=True
    ).start()
    return {
        "queued": True,
        "import_id": import_id,
        "total": len(rows),
        "created": 0,
        "skipped": 0,
        "errors": [],
    }


@app.get("/api/jobs/import/{import_id}")
def import_status(
    import_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the progress of a queued import batch."""
    batch = _import_batches.get(import_id)
    if batch is None or batch["user_id"] != user["user_id"]:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return {
        "queued": not batch["done"],
        "total": len(batch["rows"]),
        "created": batch["created"],
        "skipped": batch["skipped"],
        "errors": batch["errors"],
    }


@app.get("/api/jobs")
def list_library_jobs(
    job_function: str | None = None,
    seniority: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: dict[str, Any] = Depends(get_current_user),
):
    """List library jobs with optional filters."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return _jobs.list_jobs(
        user["user_id"],
        job_function=job_function,
        seniority=seniority,
        status=status,
        search=search,
        limit=limit,
        offset=offset,
    )


@app.get("/api/jobs/{job_id}")
def get_library_job(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return one library job, falling back to an analysis job snapshot."""
    job = _jobs.get_job(user["user_id"], job_id)
    if job is not None:
        return job
    return job_status(job_id, user)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_analysis_job(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Cancel a queued analysis job; running jobs cannot be interrupted."""
    job = _registry.get(job_id, tenant_id=user["user_id"])
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not _registry.cancel(job_id):
        raise HTTPException(
            status_code=409,
            detail="Only queued jobs can be canceled",
        )
    stored = _registry.get_payload(job_id)
    if stored and stored[2]:
        _applications.set_application_job(
            user["user_id"], stored[2], job_id, "draft"
        )
    return {"job_id": job_id, "status": "canceled"}


@app.post("/api/jobs/{job_id}/reclassify")
def reclassify_library_job(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Rerun LLM classification and clear the pending flag on success."""
    job = _jobs.get_job(user["user_id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    jd_text = (job.get("jd_text") or "").strip()
    if not jd_text:
        raise HTTPException(
            status_code=422,
            detail="Job description text is required",
        )
    job_functions, seniorities = _settings_vocabulary(user["user_id"])
    try:
        classification = _classify_job(jd_text, job_functions, seniorities)
    except LLMResponseError as exc:
        logger.warning(
            "Reclassification failed for job %s: %s", job_id, exc
        )
        raise HTTPException(
            status_code=502,
            detail="自动分类暂时不可用，岗位已保留为分类待定，可稍后重试",
        ) from exc
    try:
        updated = _jobs.update_job(
            user["user_id"],
            job_id,
            job_function=classification.get("job_function"),
            seniority=classification.get("seniority"),
            tech_tags=classification.get("tech_tags") or [],
            classification_pending=0,
            allowed_job_functions=job_functions,
            allowed_seniorities=seniorities,
        )
    except UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return updated


@app.post("/api/jobs/{job_id}/final-draft")
def save_final_draft(
    job_id: str,
    req: FinalDraftRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Persist a job-specific final draft and return its new version."""
    try:
        saved = _jobs.save_final_draft(
            user["user_id"], job_id, req.draft
        )
    except UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return saved


@app.patch("/api/jobs/{job_id}")
def update_library_job(
    job_id: str,
    req: JobUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Update editable job fields such as tags, salary, and status."""
    job_functions, seniorities = _settings_vocabulary(user["user_id"])
    try:
        job = _jobs.update_job(
            user["user_id"],
            job_id,
            title=req.title,
            jd_text=req.jd_text,
            company=req.company,
            location=req.location,
            salary_min=req.salary_min,
            salary_max=req.salary_max,
            salary_currency=req.salary_currency,
            source_type=req.source_type,
            source_url=req.source_url,
            job_function=req.job_function,
            seniority=req.seniority,
            tech_tags=req.tech_tags,
            status=req.status,
            posting_date=req.posting_date,
            tailor_granularity=req.tailor_granularity,
            tailor_focus=req.tailor_focus,
            custom_prompt=req.custom_prompt,
            allowed_job_functions=job_functions,
            allowed_seniorities=seniorities,
        )
    except UserStoreError as exc:
        if "Duplicate job" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_library_job(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Delete a library job."""
    if not _jobs.delete_job(user["user_id"], job_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return None


@app.post("/api/jobs/{job_id}/workbench", status_code=202)
def run_workbench(
    job_id: str,
    req: WorkbenchRunRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue a per-job pipeline run pinned to a Master Resume version."""
    _enforce_rate_limit(request, _analyze_rate_limiter)
    job = _jobs.get_job(user["user_id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    resume = _resumes.get_master_resume(user["user_id"], req.master_resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Master resume not found")
    config = build_config()
    if not config.api_key:
        raise HTTPException(
            status_code=503,
            detail="API key not configured. "
                   "Set via .env file or environment variables.",
        )
    cached_diagnosis = _cached_diagnosis(resume, config, user["user_id"])
    payload = {
        "resume_text": resume["content"],
        "jd_text": job["jd_text"],
        "jd_url": job.get("source_url"),
        "run_eval": False,
        "granularity": req.granularity,
        "prompt_focus": req.prompt_focus,
        "custom_prompt": req.custom_prompt,
        "master_resume_id": req.master_resume_id,
        "library_job_id": job_id,
    }
    if cached_diagnosis is not None:
        payload["precomputed_diagnosis"] = cached_diagnosis
    analysis_job_id = _queue_job(user, payload, workbench=True)
    _jobs.update_job(
        user["user_id"],
        job_id,
        workbench_job_id=analysis_job_id,
        workbench_resume_id=req.master_resume_id,
        tailor_granularity=req.granularity,
        tailor_focus=req.prompt_focus,
        custom_prompt=req.custom_prompt,
    )
    return {"job_id": analysis_job_id, "status": "queued", "workbench": True}


@app.get("/api/jobs/{job_id}/appraisal")
def get_workbench_appraisal(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the worth appraisal for one library job."""
    job = _jobs.get_job(user["user_id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    library_median = _jobs.salary_median(
        user["user_id"], job_function=job.get("job_function")
    )
    latest = _registry.snapshot(
        job.get("workbench_job_id"), tenant_id=user["user_id"]
    ) if job.get("workbench_job_id") else None
    match_score = None
    if latest and latest.get("status") == "succeeded" and latest.get("result"):
        result = latest["result"]
        eval_score = result.get("eval_score") or {}
        match_score = eval_score.get("jd_match_score")
        if match_score is None:
            match_score = _gap_match_score(result)
        if match_score is None:
            match_score = result.get("score")
    pinned = None
    if job.get("workbench_resume_id"):
        pinned = _resumes.get_master_resume(
            user["user_id"], job["workbench_resume_id"]
        )
    profile = resume_profile(pinned["content"]) if pinned else {
        "years": None,
        "education": None,
    }
    settings = _settings_store.get_settings(user["user_id"])
    return compute_appraisal(
        job,
        resume_match_score=match_score,
        resume_years=profile["years"],
        resume_education=profile["education"],
        weights=settings["appraisal_weights"],
        settings=settings,
        library_median=library_median,
    )


@app.post("/api/jobs/{job_id}/workbench/accept")
def accept_workbench_diffs(
    job_id: str,
    req: WorkbenchAcceptRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Apply accepted diff indices to the pinned resume and return a draft."""
    job = _jobs.get_job(user["user_id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    analysis_job = _registry.get(
        job.get("workbench_job_id") or "", tenant_id=user["user_id"]
    )
    if analysis_job is None or analysis_job.status != "succeeded":
        raise HTTPException(
            status_code=404,
            detail="Workbench job not found or not finished",
        )
    result = analysis_job.result or {}
    diffs = result.get("diffs") or []
    pinned = _resumes.get_master_resume(
        user["user_id"], job.get("workbench_resume_id") or ""
    )
    if pinned is None:
        raise HTTPException(
            status_code=404,
            detail="Pinned master resume not found",
        )
    base_text = pinned["content"]
    draft, applied_count = _apply_diffs(
        base_text, diffs, req.accepted_indices
    )
    return {
        "draft": draft,
        "accepted_count": applied_count,
        "total_diffs": len(diffs),
    }


def _apply_diffs(
    base_text: str,
    diffs: list[dict[str, Any]],
    accepted_indices: list[int],
) -> tuple[str, int]:
    """Apply accepted diffs to base text in a deterministic, ordered way."""
    draft = base_text
    applied = 0
    for index in sorted(set(accepted_indices)):
        if index < 0 or index >= len(diffs):
            continue
        diff = diffs[index]
        diff_type = diff.get("type", "modify")
        original = diff.get("original") or ""
        proposed = diff.get("proposed") or ""
        if diff_type == "modify" and original and proposed:
            if original in draft:
                draft = draft.replace(original, proposed, 1)
                applied += 1
        elif diff_type == "add" and proposed:
            draft = f"{draft}\n{proposed}"
            applied += 1
        elif diff_type == "remove" and original and original in draft:
            draft = draft.replace(original, "", 1)
            applied += 1
    return draft, applied


def job_status(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the current state of a queued/running/completed job.

    Not registered as a route: GET /api/jobs/{job_id} is served by
    get_library_job, which falls back here for analysis job snapshots.
    """
    snapshot = _registry.snapshot(job_id, tenant_id=user["user_id"])
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return snapshot


@app.post("/api/auth/signup", status_code=201)
def signup(
    req: SignupRequest,
    request: Request,
):
    """Create a user account."""
    _enforce_rate_limit(request, _auth_rate_limiter)
    try:
        user = _users.create_user(req.email, req.password)
    except UserStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return user


@app.post("/api/auth/login")
def login(
    req: LoginRequest,
    request: Request,
):
    """Verify credentials and return an opaque bearer token."""
    _enforce_rate_limit(request, _auth_rate_limiter)
    try:
        token = _users.login(req.email, req.password)
    except UserStoreError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = _users.user_for_token(token)
    return {"token": token, "user": user}


@app.post("/api/auth/logout")
def logout(
    token: Optional[str] = Depends(_bearer_token),
):
    """Revoke the current bearer token."""
    if token is not None:
        _users.revoke_token(token)
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return user


@app.post("/api/master-resumes", status_code=201)
def create_master_resume(
    req: MasterResumeCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Create a master resume with its first version."""
    try:
        return _resumes.create_master_resume(
            user["user_id"], req.title, req.content
        )
    except UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/master-resumes/parse")
async def parse_resume_upload(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(get_current_user),
):
    """Parse an uploaded resume file and return prefilled title/content."""
    filename = (file.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail="Unsupported format. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS)),
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(
            status_code=422, detail="Uploaded file is empty"
        )
    if len(raw) > _MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "File exceeds "
                f"{_MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB"
            ),
        )
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / f"resume{suffix}"
            path.write_bytes(raw)
            text = extract_text(path)
    except FileParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=422,
            detail="No readable text found in the uploaded file",
        )
    return {
        "filename": filename,
        "title": _derive_title(text),
        "content": text,
        "size": len(raw),
    }


@app.get("/api/master-resumes")
def list_master_resumes(user: dict[str, Any] = Depends(get_current_user)):
    """Return the current user's master resumes."""
    return _resumes.list_master_resumes(user["user_id"])


@app.get("/api/master-resumes/{resume_id}")
def get_master_resume(
    resume_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return one master resume with its full version history."""
    resume = _resumes.get_master_resume(user["user_id"], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Master resume not found")
    return resume


@app.post("/api/master-resumes/{resume_id}/diagnose", status_code=202)
def diagnose_master_resume(
    resume_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue an independent no-JD diagnosis for one master resume."""
    _enforce_rate_limit(request, _analyze_rate_limiter)
    resume = _resumes.get_master_resume(user["user_id"], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Master resume not found")
    if not (resume.get("content") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Resume content is empty; edit it before diagnosing",
        )
    if not build_config().api_key:
        raise HTTPException(
            status_code=503,
            detail="API key not configured. "
                   "Set via .env file or environment variables.",
        )
    payload = {
        "resume_text": resume["content"],
        "jd_text": None,
        "run_eval": False,
        "diagnosis": True,
        "master_resume_id": resume_id,
    }
    job_id = _queue_job(user, payload)
    _resumes.set_latest_diagnosis_job(
        user["user_id"], resume_id, job_id
    )
    return {"job_id": job_id, "status": "queued"}


@app.patch("/api/master-resumes/{resume_id}")
def update_master_resume(
    resume_id: str,
    req: MasterResumeUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Append a new version to a master resume."""
    try:
        resume = _resumes.update_master_resume(
            user["user_id"], resume_id, req.content
        )
    except UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if resume is None:
        raise HTTPException(status_code=404, detail="Master resume not found")
    return resume


@app.post("/api/master-resumes/{resume_id}/rollback")
def rollback_master_resume(
    resume_id: str,
    req: MasterResumeRollbackRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Point a master resume back at an existing version."""
    resume = _resumes.rollback_master_resume(
        user["user_id"], resume_id, req.version
    )
    if resume is None:
        raise HTTPException(status_code=404, detail="Master resume not found")
    return resume


@app.delete("/api/master-resumes/{resume_id}", status_code=204)
def delete_master_resume(
    resume_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Delete a master resume and its version history."""
    if not _resumes.delete_master_resume(user["user_id"], resume_id):
        raise HTTPException(status_code=404, detail="Master resume not found")
    return None


@app.post("/api/applications", status_code=201)
def create_application(
    req: ApplicationCreateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Create an application pinned to the master resume's current version."""
    try:
        return _applications.create_application(
            tenant_id=user["user_id"],
            title=req.title,
            master_resume_id=req.master_resume_id,
            jd_text=req.jd_text,
            jd_url=req.jd_url,
        )
    except UserStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/applications")
def list_applications(user: dict[str, Any] = Depends(get_current_user)):
    """Return the current user's applications."""
    return _applications.list_applications(user["user_id"])


@app.get("/api/applications/{application_id}")
def get_application(
    application_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return one application and its pinned resume snapshot."""
    application = _applications.get_application(
        user["user_id"], application_id
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.patch("/api/applications/{application_id}")
def update_application(
    application_id: str,
    req: ApplicationUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Update application metadata without changing its resume snapshot."""
    try:
        application = _applications.update_application(
            user["user_id"],
            application_id,
            title=req.title,
            jd_text=req.jd_text,
            jd_url=req.jd_url,
            status=req.status,
        )
    except UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.delete("/api/applications/{application_id}", status_code=204)
def delete_application(
    application_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Delete an application record."""
    if not _applications.delete_application(user["user_id"], application_id):
        raise HTTPException(status_code=404, detail="Application not found")
    return None


@app.get("/api/settings")
def get_settings(user: dict[str, Any] = Depends(get_current_user)):
    """Return the current user's editable workbench settings."""
    return _settings_store.get_settings(user["user_id"])


@app.put("/api/settings")
def update_settings(
    req: SettingsUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Persist validated settings updates for the current user."""
    updates = {
        key: value
        for key, value in req.model_dump().items()
        if value is not None
    }
    try:
        return _settings_store.update_settings(user["user_id"], updates)
    except UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/applications/{application_id}/run", status_code=202)
def run_application(
    application_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue an analysis using the application's pinned resume and JD."""
    _enforce_rate_limit(request, _analyze_rate_limiter)
    application = _applications.get_application(
        user["user_id"], application_id
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not build_config().api_key:
        raise HTTPException(
            status_code=503,
            detail="API key not configured. "
                   "Set via .env file or environment variables.",
        )
    payload = {
        "resume_text": application["resume_snapshot"],
        "jd_text": application["jd_text"],
        "jd_url": application["jd_url"],
        "run_eval": False,
    }
    job_id = _queue_job(user, payload, application_id=application_id)
    return {"job_id": job_id, "status": "queued"}


def _run_job(job_id: str) -> None:
    """Execute one queued analysis job on a bounded worker thread."""
    with _WORKER_SEMAPHORE:
        entry = _payloads.get(job_id)
        if entry is not None:
            payload, config, application_id, tenant_id = entry
        else:
            stored = _registry.get_payload(job_id)
            if stored is None:
                return
            payload, tenant_id, application_id = stored
            config = build_config()

        try:
            job = _registry.get(job_id)
            if job is None or job.status not in ("queued", "running"):
                return

            _registry.mark_running(job_id)
            recheck = _registry.get(job_id)
            if recheck is None or recheck.status != "running":
                return

            def on_stage(stage: str, message: str) -> None:
                _registry.update_progress(job_id, stage, message)

            jd_text = (payload.get("jd_text") or "").strip()
            if payload.get("jd_url") and not jd_text:
                jd_text = crawl_jd(payload["jd_url"])

            t0 = time.monotonic()
            report = run(
                config,
                payload["resume_text"],
                jd_text,
                run_eval=bool(payload.get("run_eval", False)),
                granularity=payload.get("granularity", "medium"),
                prompt_focus=payload.get("prompt_focus", "balanced"),
                custom_prompt=payload.get("custom_prompt", ""),
                diagnosis=payload.get("precomputed_diagnosis"),
                on_stage=on_stage,
            )
            report.elapsed_seconds = round(time.monotonic() - t0, 1)
            result = _report_to_dict(report)
            if payload.get("diagnosis"):
                result["diagnosis"] = _build_diagnosis_section(result)
                result["diagnosis_source_hash"] = _content_sha256(
                    payload.get("resume_text") or ""
                )
            _registry.succeed(job_id, result)
            if application_id:
                _applications.set_application_job(
                    tenant_id, application_id, job_id, "succeeded"
                )
        except CrawlError as exc:
            _registry.fail(job_id, f"Failed to crawl JD from URL: {exc}")
            if application_id:
                _applications.set_application_job(
                    tenant_id, application_id, job_id, "failed"
                )
        except Exception:
            logger.exception("Analysis job %s failed", job_id)
            if payload.get("diagnosis"):
                error = (
                    "诊断任务暂时失败：模型服务不可用或返回异常，"
                    "请检查 API Key 与网络连接后重试"
                )
            else:
                error = "Analysis failed after an internal error"
            _registry.fail(job_id, error)
            if application_id:
                _applications.set_application_job(
                    tenant_id, application_id, job_id, "failed"
                )
        finally:
            _registry.delete_payload(job_id)
            _payloads.pop(job_id, None)


# ---------------------------------------------------------------------------
# Entry point for ``python -m resualign.api``
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    import uvicorn

    host = os.environ.get("RESUALIGN_HOST", "127.0.0.1")
    port = int(os.environ.get("RESUALIGN_PORT", "8000"))
    uvicorn.run("resualign.api:app", host=host, port=port, reload=True)
