"""Q5: runtime contract enforcement with jsonschema.

Static contract tests (test_contract.py) pin the OpenAPI snapshot; this file
checks the *actual bytes* served for the CRITICAL_ROUTES list against JSON
schemas. Where the OpenAPI declares a response model in
``components.schemas`` (JobPreanalyzeResponse, WorkstationState,
HTTPValidationError) the real schema is resolved and used; otherwise a
minimal hand-written schema derived from the additive contract assertions in
test_contract.py / test_api.py documents the required shape.

Error paths (401/404/422) assert the FastAPI error body shape: ``detail`` is
present, and 422 bodies validate against the declared HTTPValidationError
schema. SSE replay events are checked for the known event-type enum and
well-formed ``data:`` JSON; ``job.gap_ready`` payloads are additionally
validated with the Pydantic JDProfile/GapReport models.
"""

from __future__ import annotations

import json
import time as _time
from unittest.mock import patch

import jsonschema
import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    GapReport,
    JDProfile,
    Report,
    ResuAlignConfig,
)
from resualign.schema_registry import GapReport as GapReportModel
from resualign.schema_registry import JDProfile as JDProfileModel
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)

# Mirrors tests/test_contract.py::CRITICAL_ROUTES (kept local so this file
# stays independent of the static snapshot module).
CRITICAL_ROUTES = {
    "/health",
    "/api/analyze",
    "/api/jobs",
    "/api/jobs/parse-jd",
    "/api/jobs/import",
    "/api/jobs/{job_id}",
    "/api/jobs/{job_id}/workbench",
    "/api/jobs/{job_id}/appraisal",
    "/api/jobs/{job_id}/workbench/accept",
    "/api/master-resumes",
    "/api/master-resumes/{resume_id}",
    "/api/applications",
    "/api/settings",
}

# SSE event types emitted by the workbench session bus (crawl.status,
# job.stage, job.gap_ready, job.error in workbench.py; job.result and
# tailor.diff in jobs.py) plus the replay heartbeat.
SSE_EVENT_TYPES = {
    "crawl.status",
    "job.stage",
    "job.gap_ready",
    "job.error",
    "job.result",
    "tailor.diff",
    "heartbeat",
}

client = TestClient(app)
_auth_cache = None


def _config(api_key: str = "sk-test") -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    global _auth_cache
    saved = {
        name: getattr(api_module, name)
        for name in (
            "_registry",
            "_users",
            "_resumes",
            "_applications",
            "_jobs",
            "_settings_store",
            "_session_store",
            "_PERSONAL_MODE",
            "_payloads",
            "_import_batches",
        )
    }
    db_path = tmp_path / "contract-runtime.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = api_module.JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._session_store = (
        api_module._workbench_service.WorkstationSessionStore()
    )
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "runtime@example.com", "password": "password-123"},
        ).status_code
        == 201
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "runtime@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


# ---------------------------------------------------------------------------
# jsonschema plumbing
# ---------------------------------------------------------------------------


def _resolve_refs(schema, openapi):
    """Replace #/components/schemas/<Name> refs with the declared schema."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            return _resolve_refs(
                openapi["components"]["schemas"][name], openapi
            )
        return {
            key: _resolve_refs(value, openapi)
            for key, value in schema.items()
        }
    if isinstance(schema, list):
        return [_resolve_refs(item, openapi) for item in schema]
    return schema


def _validate(body, schema, label: str) -> None:
    """Validate *body* against *schema*; raise with a readable failure."""
    try:
        jsonschema.validate(body, schema)
    except jsonschema.ValidationError as exc:
        raise AssertionError(
            f"{label} failed runtime schema validation: {exc.message} "
            f"(at {'/'.join(str(p) for p in exc.absolute_path) or '<root>'})"
        ) from exc


# ---------------------------------------------------------------------------
# Minimal hand-written schemas for success bodies (documented required shape)
# ---------------------------------------------------------------------------

JOB_ITEM_SCHEMA = {
    "type": "object",
    "required": [
        "job_id", "tenant_id", "title", "jd_text", "company",
        "status", "source_type", "created_at", "updated_at",
    ],
    "properties": {
        "job_id": {"type": "string"},
        "tenant_id": {"type": "string"},
        "title": {"type": "string"},
        "jd_text": {"type": "string"},
        "company": {"type": ["string", "null"]},
        "status": {"type": "string"},
        "source_type": {"type": "string"},
        "created_at": {"type": ["string", "number", "null"]},
        "updated_at": {"type": ["string", "number", "null"]},
    },
}

JD_PARSE_PREVIEW_SCHEMA = {
    "type": "object",
    "required": [
        "title", "jd_text", "company", "city",
        "salary_min", "salary_max", "salary_currency", "source_url",
    ],
    "properties": {
        "title": {"type": "string"},
        "jd_text": {"type": "string"},
        "company": {"type": ["string", "null"]},
        "city": {"type": ["string", "null"]},
        "salary_min": {"type": ["integer", "number", "null"]},
        "salary_max": {"type": ["integer", "number", "null"]},
        "salary_currency": {"type": ["string", "null"]},
        "source_url": {"type": "string"},
    },
}

IMPORT_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["queued", "import_id", "total", "created", "skipped", "errors"],
    "properties": {
        "queued": {"type": "boolean"},
        "import_id": {"type": "string"},
        "total": {"type": "integer"},
        "created": {"type": "integer"},
        "skipped": {"type": "integer"},
        "errors": {"type": "array", "items": {"type": "string"}},
    },
}

APPRAISAL_SCHEMA = {
    "type": "object",
    "required": ["score", "verdict", "components", "reasons"],
    "properties": {
        "score": {"type": ["integer", "number"]},
        "verdict": {"type": "string"},
        "components": {"type": "object"},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
}

ACCEPT_SCHEMA = {
    "type": "object",
    "required": ["draft", "accepted_count", "total_diffs"],
    "properties": {
        "draft": {"type": "string"},
        "accepted_count": {"type": "integer"},
        "total_diffs": {"type": "integer"},
    },
}

RESUME_ITEM_SCHEMA = {
    "type": "object",
    "required": ["resume_id", "title", "content", "current_version"],
    "properties": {
        "resume_id": {"type": "string"},
        "title": {"type": "string"},
        "content": {"type": "string"},
        "current_version": {"type": "integer"},
    },
}

APPLICATION_ITEM_SCHEMA = {
    "type": "object",
    "required": [
        "application_id", "title", "master_resume_id",
        "resume_version", "resume_snapshot", "status", "created_at",
    ],
    "properties": {
        "application_id": {"type": "string"},
        "title": {"type": "string"},
        "master_resume_id": {"type": "string"},
        "resume_version": {"type": "integer"},
        "resume_snapshot": {"type": "string"},
        "status": {"type": "string"},
        "created_at": {"type": ["string", "number", "null"]},
    },
}


# ---------------------------------------------------------------------------
# Success bodies for CRITICAL_ROUTES
# ---------------------------------------------------------------------------


def test_critical_route_success_bodies_validate():
    openapi = app.openapi()
    headers = _auth_headers()

    # GET /health
    r = client.get("/health")
    assert r.status_code == 200
    _validate(
        r.json(),
        {"type": "object", "required": ["status"],
         "properties": {"status": {"type": "string"}}},
        "GET /health",
    )

    # GET /api/settings
    r = client.get("/api/settings", headers=headers)
    assert r.status_code == 200
    _validate(r.json(), {"type": "object"}, "GET /api/settings")

    # POST /api/analyze -> 202 queued snapshot (worker thread suppressed).
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/analyze",
            json={"resume_text": "Python developer."},
            headers=headers,
        )
    assert r.status_code == 202
    _validate(
        r.json(),
        {"type": "object", "required": ["job_id", "status"],
         "properties": {"job_id": {"type": "string"},
                        "status": {"type": "string"}}},
        "POST /api/analyze",
    )

    # POST /api/jobs -> 201 job item (classification LLM patched away).
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Runtime contract role",
                "jd_text": "Python backend engineer with FastAPI.",
                "company": "RuntimeCo",
            },
            headers=headers,
        )
    assert r.status_code == 201
    job = r.json()
    _validate(job, JOB_ITEM_SCHEMA, "POST /api/jobs")
    job_id = job["job_id"]

    # GET /api/jobs
    r = client.get("/api/jobs", headers=headers)
    assert r.status_code == 200
    _validate(
        r.json(), {"type": "array", "items": JOB_ITEM_SCHEMA}, "GET /api/jobs"
    )

    # GET /api/jobs/{job_id}
    r = client.get(f"/api/jobs/{job_id}", headers=headers)
    assert r.status_code == 200
    _validate(r.json(), JOB_ITEM_SCHEMA, "GET /api/jobs/{job_id}")

    # POST /api/jobs/parse-jd (crawl patched, no network).
    with patch(
        "resualign.api.crawl_jd",
        return_value="Python backend engineer. Salary 25-35K.",
    ):
        r = client.post(
            "/api/jobs/parse-jd",
            json={"jd_url": "https://example.com/jobs/1"},
            headers=headers,
        )
    assert r.status_code == 200
    _validate(r.json(), JD_PARSE_PREVIEW_SCHEMA, "POST /api/jobs/parse-jd")

    # POST /api/jobs/import (classification patched for the worker thread).
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs/import",
            json={"jobs": [{"title": "Imported", "jd_text": "Backend role."}]},
            headers=headers,
        )
    assert r.status_code == 200
    _validate(r.json(), IMPORT_RESPONSE_SCHEMA, "POST /api/jobs/import")

    # POST /api/master-resumes + GET detail + GET list.
    r = client.post(
        "/api/master-resumes",
        json={"title": "Runtime master", "content": "Python developer."},
        headers=headers,
    )
    assert r.status_code == 201
    resume = r.json()
    _validate(resume, RESUME_ITEM_SCHEMA, "POST /api/master-resumes")

    r = client.get(
        f"/api/master-resumes/{resume['resume_id']}", headers=headers
    )
    assert r.status_code == 200
    detail = r.json()
    assert isinstance(detail.get("versions"), list)
    _validate(
        detail,
        {
            **RESUME_ITEM_SCHEMA,
            "required": [*RESUME_ITEM_SCHEMA["required"], "versions"],
            "properties": {
                **RESUME_ITEM_SCHEMA["properties"],
                "versions": {"type": "array"},
            },
        },
        "GET /api/master-resumes/{resume_id}",
    )

    r = client.get("/api/master-resumes", headers=headers)
    assert r.status_code == 200
    _validate(
        r.json(),
        {"type": "array", "items": RESUME_ITEM_SCHEMA},
        "GET /api/master-resumes",
    )

    # POST /api/applications + GET list.
    r = client.post(
        "/api/applications",
        json={
            "title": "Runtime application",
            "master_resume_id": resume["resume_id"],
            "jd_text": "FastAPI role",
        },
        headers=headers,
    )
    assert r.status_code == 201
    _validate(
        r.json(), APPLICATION_ITEM_SCHEMA, "POST /api/applications"
    )
    r = client.get("/api/applications", headers=headers)
    assert r.status_code == 200
    _validate(
        r.json(),
        {"type": "array", "items": APPLICATION_ITEM_SCHEMA},
        "GET /api/applications",
    )

    # Workbench queue -> run with a patched engine -> appraisal + accept.
    report = Report(
        score=80,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(
            must_have_skills=["Python", "FastAPI"],
            nice_to_have_skills=["Redis"],
            business_scenarios=["high concurrency"],
            min_years_experience=5,
        ),
        gap_report=GapReport(
            missing_keywords=["Redis caching"],
            misaligned_emphasis=[],
            strength_matches=["Python"],
        ),
        diffs=[
            DiffItem(
                type="modify",
                original="Python developer.",
                proposed="Python developer with FastAPI async endpoints.",
                reason="JD match",
                confidence="high",
                provenance="Python developer.",
            )
        ],
    )
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api._run_job"
    ):
        r = client.post(
            f"/api/jobs/{job_id}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=headers,
        )
    assert r.status_code == 202
    _validate(
        r.json(),
        {"type": "object", "required": ["job_id", "status", "workbench"],
         "properties": {"job_id": {"type": "string"},
                        "status": {"type": "string"},
                        "workbench": {"type": "boolean"}}},
        "POST /api/jobs/{job_id}/workbench",
    )
    analysis_job_id = r.json()["job_id"]
    with patch("resualign.api.run", return_value=report):
        api_module._run_job(analysis_job_id)

    r = client.get(f"/api/jobs/{job_id}/appraisal", headers=headers)
    assert r.status_code == 200
    _validate(
        r.json(), APPRAISAL_SCHEMA, "GET /api/jobs/{job_id}/appraisal"
    )

    r = client.post(
        f"/api/jobs/{job_id}/workbench/accept",
        json={"job_id": job_id, "accepted_indices": [0]},
        headers=headers,
    )
    assert r.status_code == 200
    _validate(
        r.json(), ACCEPT_SCHEMA, "POST /api/jobs/{job_id}/workbench/accept"
    )

    # POST /api/jobs/{job_id}/preanalyze -> the *declared* response model
    # JobPreanalyzeResponse, resolved from components.schemas.
    r = client.post(f"/api/jobs/{job_id}/preanalyze", headers=headers)
    assert r.status_code == 200
    preanalyze_schema = _resolve_refs(
        openapi["components"]["schemas"]["JobPreanalyzeResponse"], openapi
    )
    _validate(
        r.json(), preanalyze_schema,
        "POST /api/jobs/{job_id}/preanalyze (components.schemas)",
    )


def test_error_paths_have_detail_and_422_validates_openapi_schema():
    openapi = app.openapi()
    headers = _auth_headers()

    # 401: missing bearer token -> FastAPI error body with detail.
    r = client.get("/api/jobs")
    assert r.status_code == 401
    body = r.json()
    assert "detail" in body
    assert isinstance(body["detail"], str) and body["detail"]

    # 404: unknown library job.
    r = client.get("/api/jobs/not-a-real-job", headers=headers)
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body and body["detail"]

    # 404 on a critical sub-route (workbench accept with no workbench job).
    r = client.post(
        "/api/jobs/not-a-real-job/workbench/accept",
        json={"job_id": "not-a-real-job", "accepted_indices": [0]},
        headers=headers,
    )
    assert r.status_code == 404
    assert "detail" in r.json()

    # 422: request validation failure -> validate against the declared
    # HTTPValidationError schema resolved from components.schemas.
    r = client.post("/api/analyze", json={}, headers=headers)
    assert r.status_code == 422
    error_schema = _resolve_refs(
        openapi["components"]["schemas"]["HTTPValidationError"], openapi
    )
    _validate(r.json(), error_schema, "POST /api/analyze 422")


def test_sse_replay_event_types_and_payloads_validate():
    """Replayed workbench events use known types, well-formed JSON, and
    model-validated jd_profile/gap_report payloads."""
    headers = _auth_headers()
    with patch("resualign.api._classify_job", return_value={
        "job_function": "后端", "seniority": "高级", "tech_tags": ["Python"],
    }), patch(
        "resualign.api.profile_jd",
        return_value=JDProfile(
            must_have_skills=["Python", "FastAPI"],
            nice_to_have_skills=["Redis"],
            soft_skills=["Communication"],
            business_scenarios=["high concurrency"],
            min_years_experience=5,
            education_requirements=["BS"],
        ),
    ):
        state = client.post(
            "/api/workbench/session/init",
            json={"raw_jd": "Backend engineer with Redis caching."},
            headers=headers,
        ).json()
        session_id = state["session_id"]

    deadline = 10.0
    start = _time.monotonic()
    while _time.monotonic() - start < deadline:
        session = client.get(
            f"/api/workbench/session/{session_id}", headers=headers
        ).json()
        if (session.get("jd") or {}).get("profile") is not None:
            break
        _time.sleep(0.05)

    events: list[tuple[str, str | None]] = []
    with client.stream(
        "GET",
        f"/api/workbench/session/{session_id}/events?replay=1",
        headers=headers,
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event: "):
                events.append((line.split(" ", 1)[1], None))
            elif line.startswith("data: ") and events:
                events[-1] = (events[-1][0], line[6:])

    assert events, "no SSE events replayed"
    for name, data in events:
        assert name in SSE_EVENT_TYPES, f"unknown SSE event type: {name}"
        if name == "heartbeat":
            continue
        assert data, f"SSE event {name} carries no data payload"
        payload = json.loads(data)  # must be well-formed JSON
        if name == "job.gap_ready" and payload.get("jd_profile"):
            JDProfileModel(**payload["jd_profile"])
            if payload.get("gap_report"):
                GapReportModel(**payload["gap_report"])
