"""Tests for the appraisal commute, living-cost, weight, and conclusion."""

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.appraisal import compute_appraisal
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


def _job(**overrides):
    payload = {
        "job_id": "job-1",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Shanghai",
        "salary_min": 20000,
        "salary_max": 30000,
        "job_function": "Backend",
        "seniority": "Senior",
        "tech_tags": ["Python", "FastAPI"],
        "source_type": "paste",
        "status": "Draft",
    }
    payload.update(overrides)
    return payload


def test_commute_defaults_and_conclusion_present():
    result = compute_appraisal(_job(), resume_match_score=80, salary_benchmark=25000)
    assert result["components"]["commute"] == 100
    assert result["components"]["living_cost_adjustment"] == 1.0
    assert isinstance(result["conclusion"], str)
    assert result["conclusion"]
    assert "优势在" in result["conclusion"]
    assert "短板在" in result["conclusion"]


def test_commute_score_penalizes_time_and_cost():
    result = compute_appraisal(
        _job(),
        resume_match_score=80,
        salary_benchmark=25000,
        commute_minutes=30,
        commute_cost_per_minute=0.5,
    )
    assert result["components"]["commute"] == pytest.approx(79.0)


def test_living_cost_adjustment_scales_salary_component():
    result = compute_appraisal(
        _job(salary_min=15000, salary_max=25000),
        resume_match_score=50,
        salary_benchmark=25000,
        living_cost_adjustment=1.1,
    )
    assert result["components"]["salary"] == pytest.approx(88.0)
    assert result["components"]["living_cost_adjustment"] == 1.1


def test_commute_weight_changes_score():
    base_weights = {
        "match": 40,
        "salary": 30,
        "hard_conditions": 20,
        "quality": 10,
    }
    with_commute = dict(base_weights)
    with_commute.update({"match": 35, "salary": 25, "commute": 10})
    result = compute_appraisal(
        _job(),
        resume_match_score=100,
        salary_benchmark=20000,
        weights=with_commute,
        commute_minutes=60,
        commute_cost_per_minute=1.0,
    )
    assert result["weights"]["commute"] == 10
    assert result["components"]["commute"] < 100
    assert result["score"] < 100


def test_weights_with_commute_must_still_sum_to_100():
    bad = {
        "match": 40,
        "salary": 30,
        "hard_conditions": 20,
        "quality": 10,
        "commute": 5,
    }
    with pytest.raises(ValueError, match="[Ww]eights"):
        compute_appraisal(_job(), weights=bad)


def test_living_cost_adjustment_out_of_range_rejected():
    with pytest.raises(ValueError, match="living_cost_adjustment"):
        compute_appraisal(_job(), living_cost_adjustment=1.3)


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": api_module._resumes,
        "jobs": api_module._jobs,
        "settings": api_module._settings_store,
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "batch_store": api_module._batch_store,
    }
    db_path = tmp_path / "appraisal-upgrade.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._batch_store = api_module.BatchAlignStore()
    _auth_cache = None
    yield
    api_module._registry = saved["registry"]
    api_module._users = saved["users"]
    api_module._resumes = saved["resumes"]
    api_module._jobs = saved["jobs"]
    api_module._settings_store = saved["settings"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    api_module._payloads = saved["payloads"]
    api_module._batch_store = saved["batch_store"]
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "upgrade@example.com", "password": "password-123"},
        ).status_code
        == 201
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "upgrade@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def test_appraisal_api_accepts_commute_and_living_cost_query_params():
    from unittest.mock import patch

    headers = _auth_headers()
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend",
                "jd_text": "Python backend 20-30K",
                "company": "Acme",
                "location": "Shanghai",
            },
            headers=headers,
        )
    job_id = r.json()["job_id"]
    r = client.get(
        f"/api/jobs/{job_id}/appraisal"
        "?commute_minutes=30&commute_cost_per_minute=0.5"
        "&living_cost_adjustment=1.1",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["components"]["commute"] == pytest.approx(79.0)
    assert body["components"]["living_cost_adjustment"] == 1.1
    assert body["conclusion"]


def test_appraisal_api_rejects_out_of_range_living_cost():
    from unittest.mock import patch

    headers = _auth_headers()
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend",
                "jd_text": "Python backend 20-30K",
            },
            headers=headers,
        )
    job_id = r.json()["job_id"]
    r = client.get(
        f"/api/jobs/{job_id}/appraisal?living_cost_adjustment=1.5",
        headers=headers,
    )
    assert r.status_code == 422
