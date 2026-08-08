"""Tests for the three-level workbench result payload."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    EvalScore,
    GapReport,
    JDProfile,
    Report,
    ResuAlignConfig,
    TailoredResume,
)
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
        "resumes": api_module._resumes,
        "applications": api_module._applications,
        "jobs": api_module._jobs,
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "settings": api_module._settings_store,
    }
    db_path = tmp_path / "workbench-result.db"
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
    for key, value in saved.items():
        setattr(api_module, key, value)
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "wb-result@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "wb-result@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_resume():
    return client.post(
        "/api/master-resumes",
        json={
            "title": "Master Resume",
            "content": "Python developer.",
        },
        headers=_auth_headers(),
    ).json()


def _create_job():
    with patch("resualign.api._classify_job", return_value={}):
        return client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer.",
            },
            headers=_auth_headers(),
        ).json()


def test_workbench_result_three_level_payload():
    job = _create_job()
    resume = _create_resume()
    diff = DiffItem(
        type="modify",
        original="Python developer.",
        proposed="Python developer with Redis caching.",
        reason="JD match",
        confidence="high",
        provenance="Python developer.",
    )
    report = Report(
        score=84,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(
            must_have_skills=["Python"],
            nice_to_have_skills=["Redis"],
        ),
        gap_report=GapReport(
            missing_keywords=["Redis"],
            strength_matches=["Python"],
        ),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI with Redis caching"},
            diffs=[diff],
        ),
        diffs=[diff],
        eval_score=EvalScore(
            jd_match_score=90,
            improvement=6,
            hallucination_detected=False,
            hallucination_details=[],
            gap_coverage=0.8,
        ),
    )

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

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)

    snapshot = client.get(
        f"/api/jobs/{analysis_job_id}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "succeeded"
    result = snapshot["result"]
    assert result["score"] == 84
    assert result["diffs"][0]["provenance"] == "Python developer."
    assert result["jd_profile"]["must_have_skills"] == ["Python"]
    assert result["gap_report"]["missing_keywords"] == ["Redis"]
    assert result["eval_score"]["jd_match_score"] == 90
    assert result["eval_score"]["gap_coverage"] == 0.8
    assert result["tailored_resume"]["sections"]["experience"] == (
        "Built FastAPI with Redis caching"
    )


def test_workbench_result_diffs_carry_section_field():
    """Every diff in the workbench result carries the additive section key."""
    job = _create_job()
    resume = _create_resume()
    diff = DiffItem(
        section="项目经历",
        type="modify",
        original="Python developer.",
        proposed="Python developer with Redis caching.",
        reason="JD match",
        confidence="high",
        provenance="Python developer.",
    )
    report = Report(
        score=82,
        skills=["Python"],
        model="test-model",
        tailored_resume=TailoredResume(
            sections={"项目经历": "Built FastAPI with Redis caching"},
            diffs=[diff],
        ),
        diffs=[diff],
    )

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

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)

    snapshot = client.get(
        f"/api/jobs/{analysis_job_id}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "succeeded"
    result = snapshot["result"]
    diffs = result["diffs"]
    assert diffs, "workbench result should carry diffs"
    assert all("section" in diff for diff in diffs)
    assert diffs[0]["section"] == "项目经历"

    # The persisted library alignment keeps the section too.
    library = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert library["diffs"][0]["section"] == "项目经历"
