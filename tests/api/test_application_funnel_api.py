"""ADR-0067/C: application funnel endpoint (counts + adoption rows + rates)."""

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
    db_path = tmp_path / "funnel-api.db"
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


def test_funnel_reports_counts_rows_and_rates():
    job = client.post("/api/jobs", json={"title": "后端工程师", "jd_text": "Java 后端"}).json()
    client.post(
        "/api/jobs/" + job["job_id"] + "/final-draft",
        json={"draft": "定稿正文", "accepted_diff_ids": ["d1", "d2"]},
    )
    client.post(
        "/api/jobs/" + job["job_id"] + "/application",
        json={"channel": "官网", "applied_at": "2026-10-28"},
    )

    body = client.get("/api/analytics/application-funnel").json()
    counts = body["counts"]
    assert counts["jobs"] == 1
    assert counts["drafts"] == 1
    assert counts["versions"] == 1
    assert counts["accepted_diffs"] == 2
    assert counts["applications"] == 1

    assert len(body["applications"]) == 1
    row = body["applications"][0]
    assert row["channel"] == "官网"
    assert row["final_draft_version"] == 1
    assert row["accepted_count"] == 2
    assert row["status"] == "applied"

    rates = body["rates"]
    assert rates["draft_rate"] == 1.0
    assert rates["interview_rate"] == 0.0
    assert "样本" in body["note"]


def test_funnel_interview_moves_rate():
    job = client.post("/api/jobs", json={"title": "前端工程师", "jd_text": "React"}).json()
    client.post(
        "/api/jobs/" + job["job_id"] + "/final-draft",
        json={"draft": "定稿", "accepted_diff_ids": ["d1"]},
    )
    client.post("/api/jobs/" + job["job_id"] + "/application", json={"channel": "内推"})
    client.patch(
        "/api/jobs/" + job["job_id"] + "/application",
        json={"status": "interview", "outcome_at": "2026-11-02"},
    )
    body = client.get("/api/analytics/application-funnel").json()
    assert body["rates"]["interview_rate"] == 1.0
    assert body["applications"][0]["outcome_at"] == "2026-11-02"
