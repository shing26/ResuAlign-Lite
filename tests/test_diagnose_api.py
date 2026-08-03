"""API tests for independent master-resume diagnosis (PRD A1 / Ticket T1)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import Report, ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None
_other_cache = None


def _config(api_key="sk-test"):
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_diagnosis_stores(tmp_path):
    global _auth_cache
    global _other_cache
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
    db_path = tmp_path / "diagnose.db"
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
    _other_cache = None
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
    _other_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "tester@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def _other_headers():
    global _other_cache
    if _other_cache is not None:
        return _other_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "other-password"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "other-password"},
    )
    assert r.status_code == 200
    _other_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _other_cache


def _create_resume(title="Master Resume", content="Python developer."):
    r = client.post(
        "/api/master-resumes",
        json={"title": title, "content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _queue_diagnosis(resume_id):
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/master-resumes/{resume_id}/diagnose",
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    return r.json()


def test_diagnose_success_polls_and_survives_refresh():
    resume = _create_resume()
    report = Report(
        score=78,
        skills=["Python", "FastAPI"],
        issues=["Add metrics"],
        model="test-model",
    )

    body = _queue_diagnosis(resume["resume_id"])
    job_id = body["job_id"]
    assert body["status"] == "queued"

    detail = client.get(
        f"/api/master-resumes/{resume['resume_id']}", headers=_auth_headers()
    ).json()
    assert detail["latest_diagnosis_job_id"] == job_id

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(job_id)

    snapshot = client.get(
        f"/api/jobs/{job_id}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "succeeded"
    result = snapshot["result"]
    assert result["score"] == 78
    assert result["diagnosis"]["score"] == 78
    assert result["diagnosis"]["skills"] == ["Python", "FastAPI"]
    assert result["diagnosis"]["issues"] == ["Add metrics"]
    assert result["diagnosis"]["suggestions"] == ["建议：Add metrics"]

    # Refresh recovery: a fresh store still links the job on the same DB.
    api_module._resumes = MasterResumeStore(
        db_path=api_module._registry.db_path
    )
    detail = client.get(
        f"/api/master-resumes/{resume['resume_id']}", headers=_auth_headers()
    ).json()
    assert detail["latest_diagnosis_job_id"] == job_id
    recovered = client.get(
        f"/api/jobs/{job_id}", headers=_auth_headers()
    ).json()
    assert recovered["status"] == "succeeded"
    assert recovered["result"]["diagnosis"]["score"] == 78


def test_diagnose_runs_engine_without_jd():
    resume = _create_resume(content="Python developer.")
    report = Report(score=80, skills=["Python"], model="test-model")
    body = _queue_diagnosis(resume["resume_id"])

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ) as mock_run:
        api_module._run_job(body["job_id"])

    assert mock_run.call_args.args[1] == "Python developer."
    assert not mock_run.call_args.args[2]
    assert mock_run.call_args.kwargs["run_eval"] is False


def test_diagnosis_result_contains_source_hash():
    resume = _create_resume(content="Python developer.")
    body = _queue_diagnosis(resume["resume_id"])
    report = Report(score=80, skills=["Python"], model="test-model")

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(body["job_id"])

    data = client.get(
        f"/api/jobs/{body['job_id']}", headers=_auth_headers()
    ).json()
    assert data["result"]["diagnosis_source_hash"] == api_module._content_sha256(
        "Python developer."
    )


def test_diagnose_failure_is_actionable_and_retry_updates_link():
    resume = _create_resume()
    first = _queue_diagnosis(resume["resume_id"])

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", side_effect=RuntimeError("boom")
    ):
        api_module._run_job(first["job_id"])

    failed = client.get(
        f"/api/jobs/{first['job_id']}", headers=_auth_headers()
    ).json()
    assert failed["status"] == "failed"
    assert "诊断" in failed["error"]
    assert "重试" in failed["error"]

    report = Report(score=80, skills=["Python"], issues=[], model="test-model")
    second = _queue_diagnosis(resume["resume_id"])
    assert second["job_id"] != first["job_id"]

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(second["job_id"])

    snapshot = client.get(
        f"/api/jobs/{second['job_id']}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "succeeded"
    detail = client.get(
        f"/api/master-resumes/{resume['resume_id']}", headers=_auth_headers()
    ).json()
    assert detail["latest_diagnosis_job_id"] == second["job_id"]


def test_diagnosis_polling_contract_matches_workbench():
    resume = _create_resume()
    body = _queue_diagnosis(resume["resume_id"])

    queued = client.get(
        f"/api/jobs/{body['job_id']}", headers=_auth_headers()
    ).json()
    assert set(queued) == {
        "job_id",
        "status",
        "stage",
        "message",
        "elapsed_seconds",
        "result",
        "error",
    }
    assert queued["status"] == "queued"
    assert queued["result"] is None
    assert queued["error"] is None


def test_diagnose_requires_existing_resume_and_tenant_isolation():
    resume = _create_resume()
    r = client.post(
        "/api/master-resumes/missing/diagnose", headers=_auth_headers()
    )
    assert r.status_code == 404

    r = client.post(
        f"/api/master-resumes/{resume['resume_id']}/diagnose",
        headers=_other_headers(),
    )
    assert r.status_code == 404


def test_diagnose_requires_api_key():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config("")
    ):
        r = client.post(
            f"/api/master-resumes/{resume['resume_id']}/diagnose",
            headers=_auth_headers(),
        )
    assert r.status_code == 503
    assert "API key not configured" in r.json()["detail"]


def test_diagnose_personal_mode_has_no_login_wall():
    api_module._PERSONAL_MODE = True
    r = client.post(
        "/api/master-resumes",
        json={"title": "Local", "content": "Python developer."},
    )
    assert r.status_code == 201
    resume_id = r.json()["resume_id"]

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(f"/api/master-resumes/{resume_id}/diagnose")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert client.get(f"/api/jobs/{body['job_id']}").status_code == 200


def test_diagnose_cancel_then_retry_updates_latest_link():
    resume = _create_resume()
    first = _queue_diagnosis(resume["resume_id"])

    canceled = client.post(
        f"/api/jobs/{first['job_id']}/cancel",
        headers=_auth_headers(),
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "canceled"

    snapshot = client.get(
        f"/api/jobs/{first['job_id']}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "canceled"

    report = Report(
        score=80,
        skills=["Python"],
        issues=[],
        model="test-model",
    )
    second = _queue_diagnosis(resume["resume_id"])
    assert second["job_id"] != first["job_id"]
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(second["job_id"])

    snapshot = client.get(
        f"/api/jobs/{second['job_id']}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "succeeded"
    detail = client.get(
        f"/api/master-resumes/{resume['resume_id']}",
        headers=_auth_headers(),
    ).json()
    assert detail["latest_diagnosis_job_id"] == second["job_id"]
