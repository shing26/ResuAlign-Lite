"""API tests for classification fallback and job reclassification."""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.llm import LLMResponseError
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)


def _classify(jd_text, job_functions=None, seniorities=None, **kwargs):
    return {
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Python", "FastAPI"],
    }


def _wait_import(import_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/import/{import_id}")
        assert r.status_code == 200
        body = r.json()
        if not body["queued"]:
            return body
        time.sleep(0.01)
    raise AssertionError(f"import {import_id} did not finish")


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "import_batches": api_module._import_batches,
        "settings": getattr(api_module, "_settings_store", None),
    }
    db_path = tmp_path / "reclassify-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    api_module._payloads = {}
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    yield
    api_module._registry = saved["registry"]
    api_module._users = saved["users"]
    api_module._resumes = saved["resumes"]
    api_module._applications = saved["applications"]
    api_module._jobs = saved["jobs"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    api_module._payloads = saved["payloads"]
    api_module._import_batches = saved["import_batches"]
    api_module._settings_store = saved["settings"]
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()


def test_create_job_success_exposes_pending_zero():
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(
            "/api/jobs",
            json={"title": "Backend", "jd_text": "Python backend."},
        )
    assert r.status_code == 201
    assert r.json()["classification_pending"] == 0


def test_create_job_classification_failure_still_inserts_pending():
    with patch(
        "resualign.api._classify_job",
        side_effect=LLMResponseError("model unavailable"),
    ):
        r = client.post(
            "/api/jobs",
            json={"title": "Backend", "jd_text": "Python backend."},
        )
    assert r.status_code == 201
    job = r.json()
    assert job["classification_pending"] == 1
    assert job["job_function"] is None
    assert job["seniority"] is None
    assert job["tech_tags"] == []


def test_batch_import_classification_failure_does_not_interrupt():
    def flaky_classify(
        jd_text, job_functions=None, seniorities=None, **kwargs
    ):
        if "Fail" in jd_text:
            raise LLMResponseError("model unavailable")
        return _classify(jd_text, job_functions, seniorities)

    with patch("resualign.api._classify_job", side_effect=flaky_classify):
        r = client.post(
            "/api/jobs/import",
            json={
                "jobs": [
                    {"title": "Ok", "jd_text": "Python backend."},
                    {"title": "Pending", "jd_text": "Fail classification."},
                    {"title": "Empty", "jd_text": ""},
                ]
            },
        )
        assert r.status_code == 200
        final = _wait_import(r.json()["import_id"])
    assert final["created"] == 2
    assert final["skipped"] == 1
    assert len(final["errors"]) == 1
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 2
    pending = next(job for job in jobs if job["title"] == "Pending")
    assert pending["classification_pending"] == 1


def test_reclassify_success_clears_pending_and_overwrites_manual_fields():
    with patch(
        "resualign.api._classify_job",
        side_effect=LLMResponseError("model unavailable"),
    ):
        created = client.post(
            "/api/jobs",
            json={
                "title": "Backend",
                "jd_text": "Python backend.",
                "job_function": "测试",
                "seniority": "初级",
                "tech_tags": ["Manual"],
            },
        ).json()
    assert created["classification_pending"] == 1

    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(f"/api/jobs/{created['job_id']}/reclassify")
    assert r.status_code == 200
    job = r.json()
    assert job["classification_pending"] == 0
    assert job["job_function"] == "后端"
    assert job["seniority"] == "高级"
    assert job["tech_tags"] == ["Python", "FastAPI"]


def test_reclassify_failure_keeps_pending_and_manual_fields():
    with patch(
        "resualign.api._classify_job",
        side_effect=LLMResponseError("model unavailable"),
    ):
        created = client.post(
            "/api/jobs",
            json={
                "title": "Backend",
                "jd_text": "Python backend.",
                "job_function": "测试",
                "seniority": "初级",
                "tech_tags": ["Manual"],
            },
        ).json()

    with patch(
        "resualign.api._classify_job",
        side_effect=LLMResponseError("model unavailable"),
    ):
        r = client.post(f"/api/jobs/{created['job_id']}/reclassify")
    assert r.status_code == 502
    assert "稍后" in r.json()["detail"]
    job = client.get(f"/api/jobs/{created['job_id']}").json()
    assert job["classification_pending"] == 1
    assert job["job_function"] == "测试"
    assert job["seniority"] == "初级"
    assert job["tech_tags"] == ["Manual"]


def test_reclassify_unknown_job_returns_404():
    r = client.post("/api/jobs/does-not-exist/reclassify")
    assert r.status_code == 404
