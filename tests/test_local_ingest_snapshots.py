"""V4: Local Ingest Token, local-ingest endpoint, and applied snapshots."""

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
    db_path = tmp_path / "v4.db"
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


def _token() -> str:
    return client.get("/api/settings").json()["local_ingest_token"]


def _ingest(payload, token=None):
    headers = {"X-ResuAlign-Token": token} if token else None
    return client.post(
        "/api/jobs/local-ingest", json=payload, headers=headers
    )


def _job_payload(**overrides):
    payload = {
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Shanghai",
        "salary_text": "20-30K",
        "job_page_url": "https://www.shixiseng.com/intern/abc",
        "jd_text": "Python backend engineer. Build APIs with FastAPI.",
        "site": "shixiseng",
    }
    payload.update(overrides)
    return payload


def test_settings_generates_and_resets_local_ingest_token():
    first = client.get("/api/settings").json()["local_ingest_token"]
    assert isinstance(first, str) and len(first) >= 20
    assert client.get("/api/settings").json()["local_ingest_token"] == first

    reset = client.post("/api/settings/local-ingest-token/reset")
    assert reset.status_code == 200
    second = reset.json()["local_ingest_token"]
    assert second != first
    assert client.get("/api/settings").json()["local_ingest_token"] == second


def test_local_ingest_requires_valid_token():
    missing = _ingest(_job_payload())
    assert missing.status_code == 401
    detail = missing.json()["detail"]
    assert detail["code"] == "missing_token"
    assert "Token" in detail["reason"]

    invalid = _ingest(_job_payload(), token="not-a-token")
    assert invalid.status_code == 401
    assert invalid.json()["detail"]["code"] == "invalid_token"


def test_local_ingest_creates_pending_job_with_deterministic_fields():
    token = _token()
    r = _ingest(
        {
            **_job_payload(),
            "title": "",
            "jd_text": "后端工程师\nBuild scalable APIs.",
        },
        token=token,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "created"
    job = body["job"]
    assert job["classification_pending"] == 1
    assert job["title"] == "后端工程师"
    assert job["company"] == "Acme"
    assert job["location"] == "Shanghai"
    assert job["salary_min"] == 20000
    assert job["salary_max"] == 30000
    assert job["status"] == "未投递"
    assert job["source_url"] == "https://www.shixiseng.com/intern/abc"


def test_local_ingest_specific_dedupe_by_url_never_overwrites():
    token = _token()
    first = _ingest(_job_payload(), token=token).json()
    job_id = first["job_id"]
    client.post(
        f"/api/jobs/{job_id}/final-draft",
        json={"draft": "# Kept draft"},
    )
    client.patch(
        f"/api/jobs/{job_id}",
        json={
            "status": "applied",
            "applied_at": "2026-08-01",
            "notes": "keep note",
        },
    )

    duplicate = _ingest(
        _job_payload(
            job_page_url="https://www.shixiseng.com/intern/abc?from=search",
            jd_text="Completely different JD text",
            title="Different title",
        ),
        token=token,
    )
    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body["status"] == "duplicate"
    assert body["job_id"] == job_id
    existing = client.get(f"/api/jobs/{job_id}").json()
    assert existing["status"] == "applied"
    assert existing["notes"] == "keep note"
    assert existing["final_draft"] == "# Kept draft"


def test_local_ingest_universal_dedupe_by_text_hash():
    token = _token()
    first = _ingest(
        {
            "title": "Python Intern",
            "job_page_url": "https://company-a.com/jobs/1",
            "jd_text": "Python backend intern, FastAPI, 15-25K",
            "site": "universal",
        },
        token=token,
    ).json()
    assert first["status"] == "created"

    duplicate = _ingest(
        {
            "title": "Python Intern (copy)",
            "job_page_url": "https://company-b.com/jobs/2",
            "jd_text": "python backend intern, FastAPI, 15-25K",
            "site": "universal",
        },
        token=token,
    )
    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body["status"] == "duplicate"
    assert body["job_id"] == first["job_id"]

    # The same text through the specific site is deduped by URL, not text.
    specific = _ingest(
        {
            "title": "Python Intern",
            "job_page_url": "https://www.shixiseng.com/intern/new",
            "jd_text": "python backend intern, FastAPI, 15-25K",
            "site": "shixiseng",
        },
        token=token,
    )
    assert specific.status_code == 200
    assert specific.json()["status"] == "created"


def test_apply_freezes_snapshot_and_reapply_appends_without_downgrade():
    store = api_module._jobs
    job = store.create_job(
        tenant_id="local",
        title="Backend Engineer",
        jd_text="Python backend",
        company="Acme",
        location="Shanghai",
    )
    store.save_final_draft("local", job["job_id"], "# Draft v1")
    store.update_job(
        "local",
        job["job_id"],
        workbench_resume_id="resume-1",
        match_score=88,
    )

    applied = store.update_job(
        "local",
        job["job_id"],
        status="已投递",
        applied_at="2026-08-01",
    )
    assert applied["status"] == "已投递"
    snapshots = store.list_application_snapshots("local", job["job_id"])
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot["version_index"] == 1
    assert snapshot["final_draft"] == "# Draft v1"
    assert snapshot["match_score"] == 88
    assert snapshot["master_resume_id"] == "resume-1"
    assert snapshot["applied_at"] == "2026-08-01"

    reapplied = store.update_job(
        "local",
        job["job_id"],
        status="已投递",
        applied_at="2026-08-02",
        interview_stage="一面",
    )
    assert reapplied["status"] == "已投递"
    assert reapplied["interview_stage"] is None
    snapshots = store.list_application_snapshots("local", job["job_id"])
    assert [item["version_index"] for item in snapshots] == [2, 1]
    assert snapshots[0]["applied_at"] == "2026-08-02"
    assert snapshots[1]["final_draft"] == "# Draft v1"


def test_reapplying_applied_from_interview_does_not_downgrade():
    store = api_module._jobs
    job = store.create_job(
        tenant_id="local",
        title="Intern",
        jd_text="Intern JD",
    )
    store.save_final_draft("local", job["job_id"], "# Intern draft")
    store.update_job(
        "local",
        job["job_id"],
        status="面试中",
        applied_at="2026-07-20",
    )
    assert store.list_application_snapshots("local", job["job_id"]) == []

    again = store.update_job(
        "local",
        job["job_id"],
        status="已投递",
        applied_at="2026-08-03",
    )
    assert again["status"] == "面试中"
    assert again["applied_at"] == "2026-07-20"
    snapshots = store.list_application_snapshots("local", job["job_id"])
    assert len(snapshots) == 1
    assert snapshots[0]["applied_at"] == "2026-08-03"


def test_legacy_applied_job_without_snapshot_stays_empty():
    store = api_module._jobs
    job = store.create_job(
        tenant_id="local",
        title="Legacy Applied",
        jd_text="Legacy JD",
        status="已投递",
        applied_at="2026-06-01",
    )
    store.save_final_draft("local", job["job_id"], "# Legacy draft")
    assert store.list_application_snapshots("local", job["job_id"]) == []


def test_delete_job_removes_application_snapshots():
    store = api_module._jobs
    job = store.create_job(
        tenant_id="local",
        title="Delete me",
        jd_text="JD to delete",
    )
    store.save_final_draft("local", job["job_id"], "# Draft")
    store.update_job("local", job["job_id"], status="已投递")
    assert len(store.list_application_snapshots("local", job["job_id"])) == 1

    deleted, _ = store.delete_job("local", job["job_id"])
    assert deleted is True
    assert store.list_application_snapshots("local", job["job_id"]) == []
