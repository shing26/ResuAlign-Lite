"""API tests for the settings page runtime status and reset actions."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
import resualign.config as config_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore, default_settings
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
def temp_settings_stores(tmp_path):
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
        "runtime_llm": dict(config_module.RUNTIME_LLM_OVERRIDE),
    }
    db_path = tmp_path / "settings.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    config_module.clear_runtime_llm()
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
    config_module.RUNTIME_LLM_OVERRIDE.update(saved["runtime_llm"])
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
        json={"email": "settings@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "settings@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def _create_resume():
    r = client.post(
        "/api/master-resumes",
        json={"title": "Settings Resume", "content": "Python developer."},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _create_job():
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend 20-30K",
                "company": "Acme",
                "location": "Shanghai",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 201
    return r.json()


def test_settings_status_reports_llm_and_data_counts():
    _create_resume()
    _create_job()
    with patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.get("/api/settings/status", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_configured"] is True
    assert body["provider"] == "deepseek"
    assert body["model"] == "test-model"
    assert body["personal_mode"] is False
    assert body["resume_count"] == 1
    assert body["job_count"] == 1
    assert body["application_count"] == 0


def test_settings_status_shows_missing_api_key():
    with patch(
        "resualign.api.build_config",
        return_value=_config(api_key=""),
    ):
        r = client.get("/api/settings/status", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["api_key_configured"] is False


def test_settings_reset_restores_builtin_defaults():
    headers = _auth_headers()
    defaults = default_settings()
    changed = {
        "appraisal_weights": {"match": 50, "salary": 20, "hard_conditions": 20, "quality": 10},
        "classification_vocabulary": {
            "job_functions": ["后端"],
            "seniorities": ["高级"],
            "statuses": ["已投递"],
        },
    }
    r = client.put("/api/settings", json=changed, headers=headers)
    assert r.status_code == 200
    assert r.json()["appraisal_weights"]["match"] == 50
    assert r.json()["classification_vocabulary"]["job_functions"] == ["后端"]

    r = client.post("/api/settings/reset", headers=headers)
    assert r.status_code == 200
    restored = r.json()
    assert restored["appraisal_weights"] == defaults["appraisal_weights"]
    assert restored["classification_vocabulary"] == defaults["classification_vocabulary"]
    assert restored["salary_reference"] == defaults["salary_reference"]
    assert restored["llm_provider"] is None
    assert restored["llm_model"] is None


def test_settings_hot_swaps_llm_model_without_restart():
    headers = _auth_headers()
    r = client.put(
        "/api/settings",
        json={"llm_provider": "openrouter", "llm_model": "test-openrouter-model"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["llm_provider"] == "openrouter"
    assert r.json()["llm_model"] == "test-openrouter-model"

    config = api_module.build_config()
    assert config.provider == "openrouter"
    assert config.model == "test-openrouter-model"

    r = client.post("/api/settings/reset", headers=headers)
    assert r.status_code == 200
    config = api_module.build_config()
    assert config.provider == "deepseek"
    assert config.model != "test-openrouter-model"


def test_settings_rejects_unknown_provider():
    r = client.put(
        "/api/settings",
        json={"llm_provider": "not-a-provider", "llm_model": "x"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422
