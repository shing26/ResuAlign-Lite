"""Tests for the dashboard aggregation API (GET /api/dashboard)."""

from __future__ import annotations

import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    """Isolate the dashboard tests on a throwaway database."""
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
            "_PERSONAL_MODE",
            "_payloads",
            "_import_batches",
        )
    }
    db_path = tmp_path / "dashboard.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "dashboard@example.com", "password": "password-123"},
        ).status_code
        == 201
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "dashboard@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _tenant_id() -> str:
    """Return the signed-up user's id (the store tenant scoping key)."""
    return client.get(
        "/api/auth/me", headers=_auth_headers()
    ).json()["user_id"]


def _create_job(tenant_id: str, **overrides) -> dict:
    """Create a library job directly through the store (no LLM involved)."""
    payload: dict = {
        "title": "Backend",
        "jd_text": "Python backend engineer.",
    }
    payload.update(overrides)
    return api_module._jobs.create_job(tenant_id=tenant_id, **payload)


def _set_updated_at(job_id: str, timestamp: float) -> None:
    """Pin a job's updated_at so quick_continue selection is deterministic."""
    conn = sqlite3.connect(str(api_module._jobs.db_path))
    try:
        conn.execute(
            "UPDATE library_jobs SET updated_at = ? WHERE job_id = ?",
            (timestamp, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_dashboard_requires_auth():
    r = client.get("/api/dashboard")
    assert r.status_code == 401


def test_dashboard_empty_state():
    headers = _auth_headers()
    r = client.get("/api/dashboard", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["kpi"] == {
        "resumes": 0,
        "jobs": 0,
        "applied": 0,
        "interview": 0,
        "offer": 0,
        "declined": 0,
        "active_followups": 0,
    }
    assert body["skill_gaps"] == []
    assert body["quick_continue"] is None


def test_dashboard_kpi_counts_and_followups():
    tenant = _tenant_id()
    api_module._resumes.create_master_resume(
        tenant, "Master", "# Experience\nPython backend engineer."
    )
    _create_job(tenant, title="Draft", jd_text="Draft role text.")
    _create_job(
        tenant,
        title="Applied",
        jd_text="Applied role text.",
        status="已投递",
        next_step_due_at="2999-12-31T09:00:00Z",
    )
    _create_job(
        tenant,
        title="Interview",
        jd_text="Interview role text.",
        status="面试中",
        next_step_due_at="2999-12-31T09:00:00Z",
    )
    _create_job(
        tenant,
        title="Offer",
        jd_text="Offer role text.",
        status="已拿Offer",
    )
    _create_job(
        tenant,
        title="Withdrawn",
        jd_text="Withdrawn role text.",
        status="放弃",
        next_step_due_at="2000-01-01T00:00:00Z",
    )

    r = client.get("/api/dashboard", headers=_auth_headers())
    assert r.status_code == 200
    kpi = r.json()["kpi"]
    assert kpi["resumes"] == 1
    assert kpi["jobs"] == 5
    # applied系 = applied + interview + offer
    assert kpi["applied"] == 3
    assert kpi["interview"] == 1
    assert kpi["offer"] == 1
    assert kpi["declined"] == 1
    # future due dates count, past/no due dates do not
    assert kpi["active_followups"] == 2


def test_dashboard_skill_gaps_frequency_and_order():
    tenant = _tenant_id()
    _create_job(
        tenant,
        title="A",
        jd_text="JD text A",
        jd_profile={"must_have_skills": ["Python", "FastAPI"]},
    )
    _create_job(
        tenant,
        title="B",
        jd_text="JD text B",
        jd_profile={"must_have_skills": ["Python", "Redis"]},
    )
    _create_job(
        tenant,
        title="C",
        jd_text="JD text C",
        jd_profile={"must_have_skills": ["FastAPI"]},
    )
    # No JD profile -> contributes nothing.
    _create_job(tenant, title="D", jd_text="JD text D")

    body = client.get("/api/dashboard", headers=_auth_headers()).json()
    assert body["skill_gaps"] == [
        {"skill": "FastAPI", "count": 2},
        {"skill": "Python", "count": 2},
        {"skill": "Redis", "count": 1},
    ]


def test_dashboard_skill_gaps_capped_at_eight():
    tenant = _tenant_id()
    skills = [f"Skill{i}" for i in range(10)]
    for i, skill in enumerate(skills):
        _create_job(
            tenant,
            title=f"J{i}",
            jd_text=f"JD text for {skill}.",
            jd_profile={"must_have_skills": [skill]},
        )

    body = client.get("/api/dashboard", headers=_auth_headers()).json()
    assert len(body["skill_gaps"]) == 8
    # All counts are 1, so the tie-break orders skills alphabetically.
    assert [item["skill"] for item in body["skill_gaps"]] == sorted(skills[:8])


def test_dashboard_quick_continue_picks_most_recent_unfinished():
    tenant = _tenant_id()
    succeeded = _create_job(
        tenant,
        title="Succeeded",
        jd_text="Succeeded role text.",
        company="Acme",
        alignment_status="succeeded",
    )
    idle = _create_job(
        tenant,
        title="Idle",
        jd_text="Idle role text.",
        company="Beta",
        alignment_status="idle",
    )
    failed = _create_job(
        tenant,
        title="Failed",
        jd_text="Failed role text.",
        alignment_status="failed",
    )
    base = time.time()
    _set_updated_at(succeeded["job_id"], base + 1000.0)
    _set_updated_at(idle["job_id"], base + 500.0)
    _set_updated_at(failed["job_id"], base)

    body = client.get("/api/dashboard", headers=_auth_headers()).json()
    quick = body["quick_continue"]
    assert quick["job_id"] == idle["job_id"]
    assert quick["title"] == "Idle"
    assert quick["company"] == "Beta"
    assert quick["alignment_status"] == "idle"
    assert isinstance(quick["updated_at"], (int, float))


def test_dashboard_quick_continue_falls_back_to_latest_when_all_succeeded():
    tenant = _tenant_id()
    older = _create_job(
        tenant,
        title="Older",
        jd_text="Older role text.",
        alignment_status="succeeded",
    )
    newest = _create_job(
        tenant,
        title="Newest",
        jd_text="Newest role text.",
        alignment_status="succeeded",
    )
    base = time.time()
    _set_updated_at(older["job_id"], base)
    _set_updated_at(newest["job_id"], base + 1000.0)

    body = client.get("/api/dashboard", headers=_auth_headers()).json()
    assert body["quick_continue"]["job_id"] == newest["job_id"]


def test_dashboard_is_tenant_scoped():
    tenant_a = _tenant_id()
    _create_job(
        tenant_a,
        title="A job",
        jd_text="A role text.",
        jd_profile={"must_have_skills": ["Python"]},
    )
    api_module._resumes.create_master_resume(tenant_a, "A resume", "content")

    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "b@example.com", "password": "password-123"},
        ).status_code
        == 201
    )
    token_b = client.post(
        "/api/auth/login",
        json={"email": "b@example.com", "password": "password-123"},
    ).json()["token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    body = client.get("/api/dashboard", headers=headers_b).json()
    assert body["kpi"] == {
        "resumes": 0,
        "jobs": 0,
        "applied": 0,
        "interview": 0,
        "offer": 0,
        "declined": 0,
        "active_followups": 0,
    }
    assert body["skill_gaps"] == []
    assert body["quick_continue"] is None
