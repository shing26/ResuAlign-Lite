"""T4: alignment persistence, kanban bulk status, and crawl task state."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import CrawlTaskStore, JobLibraryStore
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


def test_crawl_task_state_machine_and_retry(tmp_path):
    store = CrawlTaskStore(db_path=tmp_path / "crawl.db")
    task = store.create(
        "tenant-1", "https://example.com/jobs/1", job_id="job-1"
    )
    assert task["status"] == "queued"
    assert store.update_state(task["crawl_id"], "fetching")["status"] == "fetching"
    assert store.update_state(task["crawl_id"], "parsing")["status"] == "parsing"
    assert (
        store.update_state(task["crawl_id"], "classifying")["status"]
        == "classifying"
    )
    done = store.update_state(task["crawl_id"], "succeeded", stage="done")
    assert done["status"] == "succeeded"
    assert done["finished_at"] is not None

    with pytest.raises(api_module.UserStoreError, match="Invalid crawl"):
        store.update_state(task["crawl_id"], "fetching")

    # Failed tasks may be requeued for a retry.
    retry_task = store.create("tenant-1", "https://example.com/jobs/2")
    store.update_state(retry_task["crawl_id"], "failed", error="boom")
    assert store.requeue_interrupted(retry_task["crawl_id"]) is True
    assert store.get(retry_task["crawl_id"])["status"] == "queued"


def test_crawl_task_restart_recovery(tmp_path):
    store = CrawlTaskStore(db_path=tmp_path / "crawl.db")
    first = store.create("tenant-1", "https://example.com/jobs/1")
    second = store.create("tenant-1", "https://example.com/jobs/2")
    store.update_state(first["crawl_id"], "fetching")
    store.update_state(first["crawl_id"], "parsing")
    store.update_state(second["crawl_id"], "fetching")
    store.update_state(second["crawl_id"], "parsing")
    store.update_state(second["crawl_id"], "classifying")
    store.update_state(second["crawl_id"], "succeeded")

    assert set(store.pending_crawl_ids()) == {first["crawl_id"]}
    assert store.recover_interrupted() == 1
    assert store.get(first["crawl_id"])["status"] == "queued"
    assert store.get(second["crawl_id"])["status"] == "succeeded"


def test_crawl_jd_on_stage_callback(monkeypatch):
    from resualign import crawler

    stages = []

    class _FakeFetched:
        content = b"<p>JD</p>"
        encoding = "utf-8"
        url = "https://example.com/jobs/1"
        ip = None
        cookies = {}

    monkeypatch.setattr(
        crawler,
        "_static_fetch",
        lambda *args, **kwargs: _FakeFetched(),
    )
    monkeypatch.setattr(
        crawler,
        "_parse_html",
        lambda *args, **kwargs: "Parsed JD",
    )

    text = crawler.crawl_jd(
        "https://example.com/jobs/1",
        on_stage=lambda stage, message: stages.append(stage),
    )
    assert text == "Parsed JD"
    assert stages == ["fetching", "parsing"]


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
    assert persisted["match_score"] == 90
    assert persisted["diffs"][0]["proposed"] == (
        "Python developer with Redis caching."
    )
    assert persisted["jd_profile"]["must_have_skills"] == ["Python"]
    assert persisted["gap_report"]["missing_keywords"] == ["Redis"]
    assert persisted["draft"] == "Built FastAPI with Redis caching"
    assert persisted["model"] == "test-model"
