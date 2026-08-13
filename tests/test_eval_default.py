"""F1 backend tests: the workbench Eval switch.

Covers:
- the settings-page global default (``eval_default``) with persistence,
  read-back, and strict boolean validation (422 on non-booleans);
- per-run passthrough on ``POST /api/jobs/{job_id}/workbench``:
  explicit ``run_eval`` wins, ``None`` falls back to the global default,
  and an unset global default keeps the historical ``False`` behavior.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


def _config(api_key="sk-test"):
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "import_batches": getattr(api_module, "_import_batches", {}),
        "settings": getattr(api_module, "_settings_store", None),
    }
    db_path = tmp_path / "eval_default.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
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
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "eval@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "eval@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def _create_resume(title="Master Resume", content="Python developer."):
    r = client.post(
        "/api/master-resumes",
        json={"title": title, "content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _create_library_job(jd_text="Python backend 20-30K", **overrides):
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": jd_text,
                "company": "Acme",
                "location": "Shanghai",
                **overrides,
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 201
    return r.json()


def _queue_workbench(job_id, resume_id, body=None):
    """Queue a workbench run with the worker suppressed and return the
    analysis job id; the queued payload stays in ``_payloads`` so tests can
    assert the exact ``run_eval`` value passed down the pipeline."""
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job_id}/workbench",
            json={"master_resume_id": resume_id, **(body or {})},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    return r.json()["job_id"]


def _queued_run_eval(analysis_job_id):
    return api_module._payloads[analysis_job_id][0]["run_eval"]


# ---------------------------------------------------------------------------
# Settings page: eval_default global default
# ---------------------------------------------------------------------------


def test_get_settings_defaults_eval_default_false():
    r = client.get("/api/settings", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["eval_default"] is False


def test_put_settings_persists_eval_default_true_and_reads_back():
    headers = _auth_headers()
    r = client.put("/api/settings", json={"eval_default": True}, headers=headers)
    assert r.status_code == 200
    assert r.json()["eval_default"] is True

    r = client.get("/api/settings", headers=headers)
    assert r.json()["eval_default"] is True


def test_put_settings_persists_eval_default_false():
    headers = _auth_headers()
    r = client.put(
        "/api/settings", json={"eval_default": False}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["eval_default"] is False


def test_put_settings_rejects_non_boolean_eval_default():
    for bad in ("yes", "not-a-bool", 1, 0, [], {}):
        r = client.put(
            "/api/settings", json={"eval_default": bad}, headers=_auth_headers()
        )
        assert r.status_code == 422, f"eval_default={bad!r} should be rejected"


def test_put_settings_partial_update_keeps_eval_default():
    headers = _auth_headers()
    client.put("/api/settings", json={"eval_default": True}, headers=headers)
    r = client.put(
        "/api/settings",
        json={"classification_vocabulary": {"job_functions": ["后端"],
                                            "seniorities": ["高级"],
                                            "statuses": ["未投递"]}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["eval_default"] is True


# ---------------------------------------------------------------------------
# Workbench: per-run run_eval passthrough
# ---------------------------------------------------------------------------


def test_workbench_run_eval_defaults_to_false_when_unset():
    job = _create_library_job()
    resume = _create_resume()
    analysis_job_id = _queue_workbench(job["job_id"], resume["resume_id"])
    assert _queued_run_eval(analysis_job_id) is False


def test_workbench_run_eval_falls_back_to_global_default():
    client.put("/api/settings", json={"eval_default": True},
               headers=_auth_headers())
    job = _create_library_job()
    resume = _create_resume()
    analysis_job_id = _queue_workbench(job["job_id"], resume["resume_id"])
    assert _queued_run_eval(analysis_job_id) is True


def test_workbench_run_eval_explicit_false_overrides_global_default():
    client.put("/api/settings", json={"eval_default": True},
               headers=_auth_headers())
    job = _create_library_job()
    resume = _create_resume()
    analysis_job_id = _queue_workbench(
        job["job_id"], resume["resume_id"], {"run_eval": False}
    )
    assert _queued_run_eval(analysis_job_id) is False


def test_workbench_run_eval_explicit_true_wins():
    job = _create_library_job()
    resume = _create_resume()
    analysis_job_id = _queue_workbench(
        job["job_id"], resume["resume_id"], {"run_eval": True}
    )
    assert _queued_run_eval(analysis_job_id) is True
