"""B3: JD analysis cache schema versioning and readable failure stages."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.cache import ContentCache
from resualign.jd_analysis import (
    JD_ANALYSIS_PROMPT_VERSION,
    profile_and_gaps,
)
from resualign.jobs import JobRegistry
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

from .conftest import _gap, _profile

client = TestClient(app)
_auth_cache = None


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
    }
    db_path = tmp_path / "cache-fix.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


class _FakeClient:
    def __init__(self, model="test-model"):
        self.model = model
        self.calls = 0

    def chat_json(self, system, user, model=None):
        self.calls += 1
        return {"jd_profile": _profile(), "gap_report": _gap()}


def _legacy_entry(profile=None):
    """Build a cache payload shaped like the pre-v2 writer (alias keys)."""
    return {
        "jd_profile": profile
        or {
            **_profile(),
            "required_skills": ["Java"],
            "nice_to_have": ["Redis"],
            "business_scene": ["Microservices"],
        },
        "gap_report": _gap(),
    }


def test_profile_and_gaps_tolerates_legacy_alias_fields():
    cache = ContentCache(db_path=":memory:")
    client_ = _FakeClient()
    content = "Resume text\n\nJD text"
    cache.put(
        "tenant-1",
        "test-model",
        "jd-analysis-v1",
        content,
        _legacy_entry(),
    )
    profile, gap = profile_and_gaps(
        client_, "Resume text", "JD text", cache=cache, tenant="tenant-1"
    )
    assert client_.calls == 1  # v1 entry is NOT read under the v2 key
    assert profile.must_have_skills == ["Java"]
    assert gap.missing_keywords == ["Redis"]


def test_profile_and_gaps_hit_under_v2_key_with_extra_fields():
    cache = ContentCache(db_path=":memory:")
    client_ = _FakeClient()
    content = "Resume text\n\nJD text"
    cache.put(
        "tenant-1",
        "test-model",
        JD_ANALYSIS_PROMPT_VERSION,
        content,
        _legacy_entry(),
    )
    profile, gap = profile_and_gaps(
        client_, "Resume text", "JD text", cache=cache, tenant="tenant-1"
    )
    assert client_.calls == 0  # cache hit under the versioned key
    assert profile.must_have_skills == ["Java"]
    assert gap.missing_keywords == ["Redis"]


def test_profile_and_gaps_writes_versioned_key():
    cache = ContentCache(db_path=":memory:")
    client_ = _FakeClient()
    profile_and_gaps(
        client_, "Resume text", "JD text", cache=cache, tenant="tenant-1"
    )
    cached = cache.get(
        "tenant-1",
        "test-model",
        JD_ANALYSIS_PROMPT_VERSION,
        "Resume text\n\nJD text",
    )
    assert cached is not None
    assert cached["jd_profile"]["must_have_skills"] == ["Java"]


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "cache@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "cache@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job():
    with patch("resualign.api._classify_job", return_value={}):
        return client.post(
            "/api/jobs",
            json={
                "title": "Backend",
                "jd_text": "Python backend with Redis.",
            },
            headers=_auth_headers(),
        ).json()


def _config():
    return ResuAlignConfig(
        provider="deepseek", api_key="sk-test", model="test-model"
    )


def test_run_job_failure_records_stage_and_readable_reason():
    job = _create_job()
    resume = client.post(
        "/api/master-resumes",
        json={"title": "R", "content": "Python dev."},
        headers=_auth_headers(),
    ).json()

    def _boom(*args, **kwargs):
        on_stage = kwargs.get("on_stage")
        if on_stage is not None:
            on_stage("jd_analysis", "Extracting JD profile and analyzing gaps...")
        raise api_module.LLMResponseError("provider timeout")

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        queued = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    assert queued.status_code == 202
    analysis_job_id = queued.json()["job_id"]

    with patch("resualign.api.run", side_effect=_boom):
        api_module._run_job(analysis_job_id)

    snapshot = api_module._registry.snapshot(analysis_job_id)
    assert snapshot["status"] == "failed"
    assert "阶段失败" in snapshot["error"]
    assert "API Key" in snapshot["error"]
    registry_job = api_module._registry.get(analysis_job_id)
    assert registry_job.stage in ("diagnose", "jd_analysis", "tailoring")


def test_run_job_failure_without_stage_has_readable_message():
    job = _create_job()
    resume = client.post(
        "/api/master-resumes",
        json={"title": "R2", "content": "Python dev."},
        headers=_auth_headers(),
    ).json()

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        queued = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    analysis_job_id = queued.json()["job_id"]

    with patch("resualign.api.run", side_effect=_boom):
        api_module._run_job(analysis_job_id)

    snapshot = api_module._registry.snapshot(analysis_job_id)
    assert snapshot["status"] == "failed"
    assert "Analysis failed after an internal error" not in snapshot["error"]
    assert "阶段失败" in snapshot["error"]
