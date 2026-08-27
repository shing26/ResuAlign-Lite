"""API tests for final-draft persistence and save-as-new-resume."""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    GapReport,
    JDProfile,
    Report,
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


def _config(api_key="sk-test"):
    from resualign.models import ResuAlignConfig

    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


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
        "import_batches": getattr(api_module, "_import_batches", {}),
        "settings": getattr(api_module, "_settings_store", None),
    }
    db_path = tmp_path / "final-draft-api.db"
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


def _create_job(title="Backend Engineer", jd_text="Python backend 20-30K"):
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={"title": title, "jd_text": jd_text},
        )
    assert r.status_code == 201
    return r.json()


def _create_resume(title="Master Resume", content="Python developer."):
    r = client.post(
        "/api/master-resumes",
        json={"title": title, "content": content},
    )
    assert r.status_code == 201
    return r.json()


def _finished_report():
    diff = DiffItem(
        type="modify",
        original="Python developer.",
        proposed="Python developer with Redis caching.",
        reason="JD match",
        confidence="high",
        provenance="Python developer.",
    )
    return Report(
        score=80,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(must_have_skills=["Python"]),
        gap_report=GapReport(missing_keywords=["Redis"]),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI services with Redis"},
            diffs=[diff],
        ),
        diffs=[diff],
    )


def test_final_draft_save_refresh_overwrite_and_no_duplicate_job():
    job = _create_job()

    first = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Draft one\n- Redis"},
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["draft"] == "Draft one\n- Redis"
    assert first_body["version"] == 1
    assert first_body["updated_at"] > 0

    refreshed = client.get(f"/api/jobs/{job['job_id']}").json()
    assert refreshed["final_draft"] == first_body["draft"]
    assert refreshed["final_draft_updated_at"] == first_body["updated_at"]
    assert refreshed["final_draft_version"] == 1
    assert len(client.get("/api/jobs").json()) == 1

    second = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Draft two\n- FastAPI"},
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["version"] == 2
    assert second_body["updated_at"] >= first_body["updated_at"]

    overwritten = client.get(f"/api/jobs/{job['job_id']}").json()
    assert overwritten["final_draft"] == "Draft two\n- FastAPI"
    assert overwritten["final_draft_version"] == 2
    assert len(client.get("/api/jobs").json()) == 1

    patched = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"status": "已投递"},
    )
    assert patched.status_code == 200
    assert patched.json()["final_draft"] == "Draft two\n- FastAPI"
    assert patched.json()["final_draft_version"] == 2


def test_final_draft_missing_job_returns_404():
    r = client.post(
        "/api/jobs/does-not-exist/final-draft",
        json={"draft": "Draft"},
    )
    assert r.status_code == 404


def test_final_draft_rejects_empty_draft():
    job = _create_job()
    r = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "   "},
    )
    assert r.status_code == 422


def test_final_draft_save_completes_under_one_second():
    job = _create_job()
    started = time.monotonic()
    r = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Performance draft"},
    )
    elapsed = time.monotonic() - started
    assert r.status_code == 200
    assert elapsed < 1.0


def test_save_as_new_master_resume_does_not_mutate_original():
    resume = _create_resume()
    job = _create_job()
    saved = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Tailored final resume"},
    ).json()

    created = client.post(
        "/api/master-resumes",
        json={
            "title": "Backend Tailored",
            "content": saved["draft"],
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["content"] == "Tailored final resume"
    assert created_body["current_version"] == 1

    original = client.get(f"/api/master-resumes/{resume['resume_id']}").json()
    assert original["content"] == "Python developer."
    assert original["current_version"] == 1


def test_workbench_accept_then_save_final_draft():
    job = _create_job()
    resume = _create_resume(content="Python developer. Redis.")

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
        )
    assert r.status_code == 202
    analysis_job_id = r.json()["job_id"]

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=_finished_report()
    ):
        api_module._run_job(analysis_job_id)

    accepted = client.post(
        f"/api/jobs/{job['job_id']}/workbench/accept",
        json={"job_id": analysis_job_id, "accepted_indices": [0]},
    )
    assert accepted.status_code == 200
    draft = accepted.json()["draft"]

    saved = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": draft},
    )
    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert saved.json()["draft"] == draft


def test_final_draft_persists_accepted_diff_ids():
    job = _create_job()
    api_module._jobs.save_alignment(
        "local",
        job["job_id"],
        diffs=[
            {
                "diff_id": "d1",
                "provenance_state": "verified",
                "proposed": "Draft one",
            },
            {
                "diff_id": "d2",
                "provenance_state": "verified",
                "proposed": "Draft two",
            },
        ],
        alignment_status="succeeded",
    )

    r = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Draft", "accepted_diff_ids": ["d1"]},
    )
    assert r.status_code == 200
    refreshed = client.get(f"/api/jobs/{job['job_id']}").json()
    states = {
        diff["diff_id"]: diff["provenance_state"]
        for diff in refreshed["diffs"]
    }
    assert states == {"d1": "accepted", "d2": "verified"}

    # A later plain save keeps the already-accepted marker.
    client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={"draft": "Draft updated"},
    )
    refreshed = client.get(f"/api/jobs/{job['job_id']}").json()
    states = {
        diff["diff_id"]: diff["provenance_state"]
        for diff in refreshed["diffs"]
    }
    assert states["d1"] == "accepted"
