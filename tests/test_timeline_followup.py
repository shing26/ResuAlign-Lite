"""U10 + F6/F9: timeline clear semantics and follow-up fields."""

from unittest.mock import patch

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
def temp_stores(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "timeline.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "timeline@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "timeline@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job(**overrides):
    payload = {
        "title": "Backend",
        "jd_text": "Python backend engineer.",
    }
    payload.update(overrides)
    with patch("resualign.api._classify_job", return_value={}):
        return client.post(
            "/api/jobs", json=payload, headers=_auth_headers()
        ).json()


def _set_applied_at(job_id, value):
    return client.patch(
        f"/api/jobs/{job_id}",
        json={"applied_at": value},
        headers=_auth_headers(),
    )


def test_patch_applied_at_null_clears_field():
    job = _create_job()
    _set_applied_at(job["job_id"], "2026-08-01T10:00:00Z")
    fetched = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert fetched["applied_at"] == "2026-08-01T10:00:00Z"

    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"applied_at": None},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["applied_at"] is None


def test_patch_applied_at_empty_string_clears_field():
    job = _create_job()
    _set_applied_at(job["job_id"], "2026-08-01T10:00:00Z")
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"applied_at": ""},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["applied_at"] is None


def test_patch_omitting_applied_at_leaves_it_untouched():
    job = _create_job()
    _set_applied_at(job["job_id"], "2026-08-01T10:00:00Z")
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"notes": "only notes"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["applied_at"] == "2026-08-01T10:00:00Z"
    assert r.json()["notes"] == "only notes"


def test_patch_followup_fields_roundtrip():
    job = _create_job()
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={
            "next_step_due_at": "2026-08-15T09:00:00Z",
            "interview_stage": "一面",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["next_step_due_at"] == "2026-08-15T09:00:00Z"
    assert body["interview_stage"] == "一面"

    fetched = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert fetched["next_step_due_at"] == "2026-08-15T09:00:00Z"
    assert fetched["interview_stage"] == "一面"


def test_patch_followup_fields_clear_on_null():
    job = _create_job()
    client.patch(
        f"/api/jobs/{job['job_id']}",
        json={
            "next_step_due_at": "2026-08-15T09:00:00Z",
            "interview_stage": "二面",
        },
        headers=_auth_headers(),
    )
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"next_step_due_at": None, "interview_stage": None},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["next_step_due_at"] is None
    assert r.json()["interview_stage"] is None


def test_list_includes_followup_fields():
    job = _create_job()
    client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"interview_stage": "HR面"},
        headers=_auth_headers(),
    )
    listed = client.get("/api/jobs", headers=_auth_headers()).json()
    assert listed[0]["interview_stage"] == "HR面"
    assert "next_step_due_at" in listed[0]


def test_store_roundtrip_and_clear(tmp_path):
    store = JobLibraryStore(db_path=tmp_path / "s.db")
    job = store.create_job(
        tenant_id="t1",
        title="Backend",
        jd_text="Python backend.",
        next_step_due_at="2026-08-20T08:00:00Z",
        interview_stage="技术面",
    )
    assert job["next_step_due_at"] == "2026-08-20T08:00:00Z"
    assert job["interview_stage"] == "技术面"

    updated = store.update_job("t1", job["job_id"], next_step_due_at="")
    assert updated["next_step_due_at"] is None
    assert updated["interview_stage"] == "技术面"

    updated = store.update_job("t1", job["job_id"], interview_stage="")
    assert updated["interview_stage"] is None


def test_legacy_db_migration_adds_followup_columns(tmp_path):
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE library_jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            jd_text TEXT NOT NULL,
            company TEXT,
            location TEXT,
            salary_min REAL,
            salary_max REAL,
            salary_currency TEXT NOT NULL DEFAULT 'CNY',
            source_type TEXT NOT NULL DEFAULT 'paste',
            source_url TEXT,
            job_function TEXT,
            seniority TEXT,
            tech_tags TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT '未投递',
            posting_date TEXT,
            dedupe_key TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE(tenant_id, dedupe_key)
        );
        INSERT INTO library_jobs (job_id, tenant_id, title, jd_text,
            job_function, dedupe_key, created_at, updated_at)
        VALUES ('j1', 't1', 'Legacy', 'JD text', '后端', 'text:1', 1.0, 1.0);
        """
    )
    conn.commit()
    conn.close()

    store = JobLibraryStore(db_path=db)
    job = store.get_job("t1", "j1")
    assert job["next_step_due_at"] is None
    assert job["interview_stage"] is None
    saved = store.update_job(
        "t1", "j1", next_step_due_at="2026-09-01T00:00:00Z"
    )
    assert saved["next_step_due_at"] == "2026-09-01T00:00:00Z"
