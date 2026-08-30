"""T4: alignment persistence, kanban bulk status, and crawl task state."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
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
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


def _config(api_key: str = "sk-test") -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
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
        )
    }
    db_path = tmp_path / "alignment.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._session_store = api_module._workbench_service.WorkstationSessionStore()
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "alignment@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "alignment@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job() -> dict:
    with patch("resualign.api._classify_job", return_value={}):
        return client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": (
                    "Python backend engineer with Redis "
                    f"{time.time_ns()}."
                ),
            },
            headers=_auth_headers(),
        ).json()


def _create_resume() -> dict:
    return client.post(
        "/api/master-resumes",
        json={
            "title": "Master Resume",
            "content": "Python developer with FastAPI.",
        },
        headers=_auth_headers(),
    ).json()


def test_save_alignment_round_trip(tmp_path):
    store = JobLibraryStore(db_path=tmp_path / "store.db")
    job = store.create_job(
        tenant_id="tenant-1",
        title="Backend",
        jd_text="Python backend engineer.",
    )
    saved = store.save_alignment(
        "tenant-1",
        job["job_id"],
        jd_profile={
            "must_have_skills": ["Python"],
            "business_scenarios": ["high concurrency"],
        },
        gap_report={"missing_keywords": ["Redis"], "strength_matches": ["Python"]},
        match_score=88.0,
        diffs=[
            {
                "type": "modify",
                "original": "Python developer.",
                "proposed": "Python developer with Redis caching.",
            }
        ],
        invalid_diffs=[{"type": "add", "original": "", "proposed": "Fake skill."}],
        draft="# Experience\nPython developer with Redis caching.",
        eval_score={"jd_match_score": 88, "gap_coverage": 0.8},
        model="test-model",
        prompt_version="engine.v1",
    )
    assert saved is not None
    assert saved["alignment_status"] == "succeeded"
    assert saved["match_score"] == 88.0
    assert saved["jd_profile"]["must_have_skills"] == ["Python"]
    assert saved["gap_report"]["missing_keywords"] == ["Redis"]
    assert saved["diffs"][0]["proposed"].endswith("Redis caching.")
    assert saved["invalid_diffs"][0]["proposed"] == "Fake skill."
    assert saved["draft"].startswith("# Experience")
    assert saved["eval_score"]["jd_match_score"] == 88
    assert saved["analysis_ready"] is True

    again = store.get_job("tenant-1", job["job_id"])
    assert again["jd_profile"]["business_scenarios"] == ["high concurrency"]
    assert again["prompt_version"] == "engine.v1"
    assert again["model"] == "test-model"
    assert again["generated_at"] is not None


def test_bulk_update_status_single_transaction_optimistic_lock(tmp_path):
    store = JobLibraryStore(db_path=tmp_path / "store.db")
    first = store.create_job(
        tenant_id="tenant-1", title="A", jd_text="Python A."
    )
    second = store.create_job(
        tenant_id="tenant-1", title="B", jd_text="Python B."
    )
    store.update_job("tenant-1", second["job_id"], status="applied")

    results = store.bulk_update_status(
        "tenant-1",
        [first["job_id"], second["job_id"], "missing-id"],
        "interview",
        expected_status="draft",
    )
    by_id = {item["job_id"]: item for item in results}
    assert by_id[first["job_id"]]["status"] == "updated"
    assert by_id[first["job_id"]]["updated"] is True
    assert by_id[second["job_id"]]["status"] == "conflict"
    assert by_id[second["job_id"]]["updated"] is False
    assert by_id["missing-id"]["status"] == "not_found"

    assert store.get_job("tenant-1", first["job_id"])["status"] == "interview"
    assert store.get_job("tenant-1", second["job_id"])["status"] == "applied"


def test_kanban_bulk_status_api_idempotent():
    job_one = _create_job()
    job_two = _create_job()
    payload = {
        "job_ids": [job_one["job_id"], job_two["job_id"]],
        "status": "applied",
        "idempotency_key": "bulk-key-1",
    }
    first = client.post(
        "/api/kanban/bulk-status", json=payload, headers=_auth_headers()
    )
    assert first.status_code == 200
    body = first.json()
    assert body["updated"] == 2
    assert body["total"] == 2
    assert all(item["status"] == "updated" for item in body["results"])

    replay = client.post(
        "/api/kanban/bulk-status", json=payload, headers=_auth_headers()
    )
    assert replay.status_code == 200
    assert replay.json() == body
    # Replaying does not double-apply or alter the stored status.
    assert (
        client.get(
            f"/api/jobs/{job_one['job_id']}", headers=_auth_headers()
        ).json()["status"]
        == "applied"
    )


def test_kanban_bulk_status_limits_and_validates():
    too_many = client.post(
        "/api/kanban/bulk-status",
        json={"job_ids": [f"job-{i}" for i in range(201)], "status": "draft"},
        headers=_auth_headers(),
    )
    assert too_many.status_code == 422
    empty = client.post(
        "/api/kanban/bulk-status",
        json={"job_ids": [], "status": "draft"},
        headers=_auth_headers(),
    )
    assert empty.status_code == 422
    bad_status = client.post(
        "/api/kanban/bulk-status",
        json={"job_ids": ["job-1"], "status": "not-a-status"},
        headers=_auth_headers(),
    )
    assert bad_status.status_code == 422


def test_workbench_success_persists_alignment():
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

    persisted = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert persisted["alignment_status"] == "succeeded"
    assert persisted["analysis_ready"] is True
    assert persisted["match_score"] == 94.8
    assert persisted["match_score_detail"]["total"] == 94.8
    assert persisted["match_reason"].startswith("基于规则评分：")
    assert persisted["diffs"][0]["proposed"] == (
        "Python developer with Redis caching."
    )
    assert persisted["jd_profile"]["must_have_skills"] == ["Python"]
    assert persisted["gap_report"]["missing_keywords"] == ["Redis"]
    assert persisted["draft"] == "Built FastAPI with Redis caching"
    assert persisted["model"] == "test-model"


def test_workspace_session_hydrates_persisted_results_after_restart():
    """B6: reopening a job renders the persisted alignment, not empty state."""
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
    analysis_job_id = queued.json()["job_id"]
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)

    persisted = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert persisted["analysis_ready"] is True

    # Simulate a restart: no live session exists for this job.
    api_module._session_store = (
        api_module._workbench_service.WorkstationSessionStore()
    )
    r = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    state = r.json()
    assert state["jd"]["profile"]["must_have_skills"] == ["Python"]
    assert state["gap"]["gap_report"]["missing_keywords"] == ["Redis"]
    assert state["gap"]["score"] == 94.8
    assert state["alignment"]["status"] == "succeeded"
    assert state["alignment"]["diffs"][0]["proposed"] == (
        "Python developer with Redis caching."
    )
    assert state["alignment"]["draft"] == "Built FastAPI with Redis caching"


def test_workbench_probe_402_blocks_with_actionable_message():
    """Phase A1: a definitive quota failure (402) blocks queueing with an
    actionable message instead of a 90s timeout then a failed job."""
    job = _create_job()
    resume = _create_resume()
    with patch(
        "resualign.api._probe_active_llm_quick",
        return_value=(False, "模型账户欠费或余额不足，请充值后重试"),
    ):
        resp = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    assert resp.status_code == 422
    assert "欠费" in resp.json()["detail"]


def test_workbench_probe_network_error_is_non_blocking():
    """Phase A1: network/timeout probe states must NOT block queueing; the
    run proceeds and its failure surfaces via last_alignment_error."""
    job = _create_job()
    resume = _create_resume()
    with patch(
        "resualign.api._probe_active_llm_quick",
        return_value=(True, ""),
    ), patch("resualign.api._queue_job", return_value="job-abc"):
        resp = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    assert resp.status_code == 202


def test_noop_diffs_filtered_into_invalid():
    """Phase A2: modify diffs whose proposed == original are no-ops; they
    must not count as accepted advice and land in invalid_diffs."""
    job = _create_job()
    resume = _create_resume()
    noop = DiffItem(
        type="modify",
        original="Python developer.",
        proposed="Python developer.",
        reason="no measurable outcomes",
        confidence="high",
        provenance="Python developer.",
    )
    real = DiffItem(
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
        jd_profile=JDProfile(must_have_skills=["Python"]),
        gap_report=GapReport(missing_keywords=["Redis"]),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI"},
            diffs=[noop, real],
        ),
        diffs=[noop, real],
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
    persisted = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert len(persisted["diffs"]) == 1
    assert persisted["diffs"][0]["proposed"] == (
        "Python developer with Redis caching."
    )
    assert len(persisted["invalid_diffs"]) == 1
    assert persisted["invalid_diffs"][0]["original"] == "Python developer."
