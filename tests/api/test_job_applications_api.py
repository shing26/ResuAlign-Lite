"""ADR-0067: application spine API (record / read / outcome / timeline)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": api_module._jobs,
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "applications-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)


def _job() -> dict:
    response = client.post("/api/jobs", json={"title": "后端工程师", "jd_text": "Java 后端"})
    assert response.status_code == 201
    return response.json()


def _save_draft(job_id: str) -> dict:
    response = client.post(
        "/api/jobs/" + job_id + "/final-draft",
        json={"draft": "定稿正文", "accepted_diff_ids": []},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_record_requires_final_draft():
    job = _job()
    response = client.post("/api/jobs/" + job["job_id"] + "/application", json={"channel": "官网"})
    assert response.status_code == 422
    assert "定稿" in response.json()["detail"]


def test_record_binds_current_version():
    job = _job()
    saved = _save_draft(job["job_id"])
    response = client.post(
        "/api/jobs/" + job["job_id"] + "/application",
        json={"channel": "官网", "applied_at": "2026-10-28"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version_id"] == saved["version_id"]
    assert body["draft_sha256"] == saved["sha256"]
    assert body["channel"] == "官网"
    assert body["status"] == "applied"

    fetched = client.get("/api/jobs/" + job["job_id"] + "/application")
    assert fetched.status_code == 200
    assert fetched.json()["applied_at"] == "2026-10-28"
    job_now = client.get("/api/jobs/" + job["job_id"]).json()
    assert job_now["status"] == "已投递"
    assert job_now["applied_at"] == "2026-10-28"

    missing = client.get("/api/jobs/does-not-exist/application")
    assert missing.status_code == 404


def test_outcome_and_timeline():
    job = _job()
    _save_draft(job["job_id"])
    client.post("/api/jobs/" + job["job_id"] + "/application", json={"channel": "官网"})

    patched = client.patch(
        "/api/jobs/" + job["job_id"] + "/application",
        json={"status": "interview", "outcome_at": "2026-11-02"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "interview"
    assert client.get("/api/jobs/" + job["job_id"]).json()["status"] == "面试中"

    timeline = client.get("/api/jobs/" + job["job_id"] + "/timeline")
    assert timeline.status_code == 200
    kinds = [event["kind"] for event in timeline.json()["events"]]
    assert "created" in kinds and "application" in kinds and "outcome" in kinds

    bad = client.patch(
        "/api/jobs/" + job["job_id"] + "/application", json={"status": "bogus"}
    )
    assert bad.status_code == 422


def test_legacy_patch_syncs_application():
    job = _job()
    _save_draft(job["job_id"])
    response = client.patch(
        "/api/jobs/" + job["job_id"],
        json={"status": "applied", "applied_at": "2026-10-29"},
    )
    assert response.status_code == 200, response.text
    application = client.get("/api/jobs/" + job["job_id"] + "/application")
    assert application.status_code == 200
    assert application.json()["applied_at"] == "2026-10-29"
