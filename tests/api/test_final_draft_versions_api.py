"""ADR-0066: final-draft version API (list/detail/diff/rollback + export identity)."""

from __future__ import annotations

import hashlib

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
    db_path = tmp_path / "draft-versions-api.db"
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


def _create_job() -> dict:
    response = client.post("/api/jobs", json={"title": "后端工程师", "jd_text": "Java 后端"})
    assert response.status_code == 201
    return response.json()


def _save(job_id: str, draft: str, accepted=None) -> dict:
    response = client.post(
        "/api/jobs/" + job_id + "/final-draft",
        json={"draft": draft, "accepted_diff_ids": accepted or []},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_version_list_and_detail():
    job = _create_job()
    _save(job["job_id"], "第一版", ["d1"])
    second = _save(job["job_id"], "第二版", ["d2"])

    listing = client.get("/api/jobs/" + job["job_id"] + "/final-draft/versions").json()
    assert listing["current_version"] == 2
    assert [item["version"] for item in listing["versions"]] == [1, 2]
    assert listing["versions"][1]["sha256"] == hashlib.sha256("第二版".encode("utf-8")).hexdigest()

    detail = client.get(
        "/api/jobs/" + job["job_id"] + "/final-draft/versions/1"
    ).json()
    assert detail["draft"] == "第一版"
    assert detail["accepted_diff_ids"] == ["d1"]

    missing = client.get("/api/jobs/" + job["job_id"] + "/final-draft/versions/9")
    assert missing.status_code == 404
    assert second["version_id"]


def test_version_diff():
    job = _create_job()
    _save(job["job_id"], "第一行\n第二行")
    _save(job["job_id"], "第一行\n第二行改\n第三行")
    body = client.get(
        "/api/jobs/" + job["job_id"] + "/final-draft/versions/2/diff?against=1"
    ).json()
    assert (body["from_version"], body["to_version"]) == (1, 2)
    assert body["added"] >= 1 and body["removed"] >= 1
    assert any("第二行改" in line for line in body["diff"])


def test_rollback_appends_version():
    job = _create_job()
    _save(job["job_id"], "第一版")
    _save(job["job_id"], "第二版")
    rolled = client.post(
        "/api/jobs/" + job["job_id"] + "/final-draft/rollback", json={"version": 1}
    )
    assert rolled.status_code == 200, rolled.text
    body = rolled.json()
    assert body["version"] == 3
    assert body["draft"] == "第一版"
    current = client.get("/api/jobs/" + job["job_id"]).json()
    assert current["final_draft"] == "第一版"
    assert current["final_draft_version"] == 3
    missing = client.post(
        "/api/jobs/" + job["job_id"] + "/final-draft/rollback", json={"version": 99}
    )
    assert missing.status_code == 404


def test_export_carries_version_identity_but_pdf_stays_clean():
    job = _create_job()
    _save(job["job_id"], "第一版")
    saved = _save(job["job_id"], "第二版")

    exported = client.post(
        "/api/jobs/" + job["job_id"] + "/exports", json={"format": "json"}
    ).json()
    assert exported["meta"]["final_draft_version_id"] == saved["version_id"]
    assert exported["meta"]["final_draft_sha256"] == saved["sha256"]

    pdf = client.post(
        "/api/jobs/" + job["job_id"] + "/exports", json={"format": "pdf"}
    ).json()
    assert saved["sha256"] not in pdf["content"]
    assert "sha256" not in pdf["content"].lower()
