"""Tests for the no-login personal workbench mode."""

from pathlib import Path
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


def _config():
    return ResuAlignConfig(
        provider="deepseek",
        api_key="sk-test",
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_personal_stores(tmp_path):
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
    db_path = tmp_path / "personal.db"
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


def test_personal_mode_uses_stable_local_user():
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    first = r.json()
    assert first["user_id"] == "local"
    assert first["email"] == "local@resualign.local"

    second = client.get("/api/auth/me").json()
    assert second["user_id"] == first["user_id"]


def test_personal_mode_analyze_without_token():
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/analyze",
            json={"resume_text": "Python developer."},
        )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    assert client.get(f"/api/jobs/{job_id}").status_code == 200


def test_personal_mode_workbench_without_token():
    r = client.post(
        "/api/master-resumes",
        json={"title": "Master Resume", "content": "Python developer."},
    )
    assert r.status_code == 201
    assert r.json()["resume_id"]

    resumes = client.get("/api/master-resumes").json()
    assert len(resumes) == 1


def test_personal_mode_jobs_share_the_same_tenant():
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        first = client.post(
            "/api/analyze", json={"resume_text": "Python developer."}
        ).json()["job_id"]
        second = client.post(
            "/api/analyze", json={"resume_text": "Java developer."}
        ).json()["job_id"]

    assert client.get(f"/api/jobs/{first}").status_code == 200
    assert client.get(f"/api/jobs/{second}").status_code == 200


def test_personal_mode_frontend_keeps_login_modal_disabled():
    app_js = (
        Path(__file__).resolve().parents[1]
        / "src" / "resualign" / "static" / "app.js"
    )
    source = app_js.read_text(encoding="utf-8")
    assert (
        "if (response.status === 401 && !state.personal) {"
        in source
    )
    assert "state.personal = true;" in source
    assert "openLoginModal();" in source
    index = (
        Path(__file__).resolve().parents[1]
        / "src" / "resualign" / "static" / "index.html"
    )
    assert 'data-form="login"' not in index.read_text(encoding="utf-8")


def test_personal_mode_deep_link_resources_survive_refresh():
    resume = client.post(
        "/api/master-resumes",
        json={"title": "Deep Link Resume", "content": "Python."},
    )
    assert resume.status_code == 201
    resume_id = resume.json()["resume_id"]
    with patch("resualign.api._classify_job", return_value={}):
        job = client.post(
            "/api/jobs",
            json={"title": "Deep Link Job", "jd_text": "Python job."},
        )
    assert job.status_code == 201
    job_id = job.json()["job_id"]

    db_path = api_module._registry.db_path
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)

    restored_resume = client.get(
        f"/api/master-resumes/{resume_id}"
    ).json()
    restored_job = client.get(f"/api/jobs/{job_id}").json()
    assert restored_resume["content"] == "Python."
    assert restored_job["title"] == "Deep Link Job"
