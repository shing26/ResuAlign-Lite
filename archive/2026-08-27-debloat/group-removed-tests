"""Tests for the MVP-06 job refresh service and endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.api.services.job_refresh import JobRefreshService
from resualign.crawler import CrawlError
from resualign.job_library import CrawlTaskStore, JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)


def _stores(tmp_path):
    db_path = tmp_path / "refresh.db"
    job_store = JobLibraryStore(db_path=db_path)
    crawl_store = CrawlTaskStore(db_path=db_path)
    return job_store, crawl_store


def _url_job(job_store, tenant="tenant-a", **overrides):
    payload = {
        "tenant_id": tenant,
        "title": "Backend Engineer",
        "jd_text": "Python backend engineer.",
        "source_type": "url",
        "source_url": "https://example.com/jobs/1",
    }
    payload.update(overrides)
    refresh_enabled = payload.pop("refresh_enabled", None)
    job = job_store.create_job(**payload)
    if refresh_enabled is not None:
        job = job_store.update_job(
            tenant,
            job["job_id"],
            refresh_enabled=refresh_enabled,
        )
    return job


def _service(job_store, crawl_store, crawler_fn):
    return JobRefreshService(
        job_store=job_store,
        crawl_store=crawl_store,
        crawler_fn=crawler_fn,
    )


def test_refresh_fields_exist_on_url_jobs(tmp_path):
    job_store, _ = _stores(tmp_path)
    job = _url_job(job_store)
    assert job["refresh_enabled"] is True
    assert job["last_refresh_at"] is None
    assert job["refresh_status"] is None
    assert job["match_stale"] is False


def test_queue_refresh_creates_once_and_deduplicates(tmp_path):
    job_store, crawl_store = _stores(tmp_path)
    service = _service(job_store, crawl_store, lambda *a, **k: "text")
    job = _url_job(job_store)
    first = service.queue_refresh("tenant-a", job["job_id"])
    assert first["queued"] is True
    second = service.queue_refresh("tenant-a", job["job_id"])
    assert second["queued"] is False
    assert second["crawl_id"] == first["crawl_id"]
    assert second["reason"] == "already_pending"


def test_run_refresh_updates_changed_fields_and_records_event(tmp_path):
    job_store, crawl_store = _stores(tmp_path)

    def fake_crawler(url, meta=None, on_stage=None):
        if on_stage:
            on_stage("fetching", "fetching")
        meta.update(
            {
                "title": "Senior Backend Engineer",
                "company": "Acme",
                "city": "Shanghai",
            }
        )
        return "Python backend engineer with distributed systems."

    service = _service(job_store, crawl_store, fake_crawler)
    job = _url_job(job_store)
    result = service.run_refresh("tenant-a", job["job_id"])
    assert result["status"] == "succeeded"
    assert result["changed"] is True
    assert set(result["changed_fields"]) >= {"jd_text", "title", "company"}
    refreshed = job_store.get_job("tenant-a", job["job_id"])
    assert refreshed["jd_text"].startswith("Python backend engineer with")
    assert refreshed["title"] == "Senior Backend Engineer"
    assert refreshed["refresh_status"] == "succeeded"
    assert refreshed["last_refresh_at"] is not None
    assert refreshed["match_stale"] is True
    events = job_store.list_refresh_events("tenant-a", job["job_id"])
    assert len(events) == 1
    assert "jd_text" in events[0]["changed_fields"]


def test_run_refresh_without_diff_does_not_flag_stale(tmp_path):
    job_store, crawl_store = _stores(tmp_path)

    def fake_crawler(url, meta=None, on_stage=None):
        return "Python backend engineer."

    service = _service(job_store, crawl_store, fake_crawler)
    job = _url_job(job_store)
    result = service.run_refresh("tenant-a", job["job_id"])
    assert result["changed"] is False
    refreshed = job_store.get_job("tenant-a", job["job_id"])
    assert refreshed["match_stale"] is False
    assert refreshed["refresh_status"] == "succeeded"


def test_run_refresh_marks_closed_page_and_failure(tmp_path):
    job_store, crawl_store = _stores(tmp_path)

    def fail_crawler(url, meta=None, on_stage=None):
        raise CrawlError("page gone", category="http")

    service = _service(job_store, crawl_store, fail_crawler)
    job = _url_job(job_store)
    result = service.run_refresh("tenant-a", job["job_id"])
    assert result["status"] == "closed"
    refreshed = job_store.get_job("tenant-a", job["job_id"])
    assert refreshed["refresh_status"] == "closed"
    events = job_store.list_refresh_events("tenant-a", job["job_id"])
    assert events[0]["status"] == "closed"
    assert "page gone" in events[0]["error"]


def test_queue_refresh_all_only_targets_eligible_jobs(tmp_path):
    job_store, crawl_store = _stores(tmp_path)
    service = _service(job_store, crawl_store, lambda *a, **k: "text")
    _url_job(job_store, title="URL A")
    _url_job(
        job_store,
        title="Disabled",
        refresh_enabled=0,
        source_url="https://example.com/jobs/disabled",
    )
    job_store.create_job(
        tenant_id="tenant-a",
        title="Pasted",
        jd_text="Pasted JD.",
        source_type="paste",
    )
    queued = service.queue_refresh_all("tenant-a")
    assert [item["title"] for item in queued] == ["URL A"]


def test_refresh_api_runs_and_exposes_new_fields(tmp_path):
    client = TestClient(app)
    saved = _save_api_state(tmp_path)
    try:
        headers = _auth_headers(client)
        tenant = client.get("/api/auth/me", headers=headers).json()["user_id"]

        def fake_crawler(url, meta=None, on_stage=None):
            meta.update({"title": "Senior Backend", "company": "Acme"})
            return "Python backend engineer with distributed systems."

        job_store = api_module._jobs
        crawl_store = api_module._crawl_tasks
        old_service = api_module._refresh_service
        api_module._refresh_service = JobRefreshService(
            job_store=job_store,
            crawl_store=crawl_store,
            crawler_fn=fake_crawler,
        )
        job = _url_job(job_store, tenant=tenant)
        try:
            response = client.post(
                f"/api/jobs/{job['job_id']}/refresh",
                headers=headers,
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "succeeded"
            assert body["changed"] is True
            fetched = client.get(
                f"/api/jobs/{job['job_id']}", headers=headers
            ).json()
            assert fetched["refresh_status"] == "succeeded"
            assert fetched["match_stale"] is True
            assert fetched["last_refresh_at"] is not None
        finally:
            api_module._refresh_service = old_service
    finally:
        _restore_api_state(saved)


def _save_api_state(tmp_path) -> dict:
    saved = {
        "_registry": api_module._registry,
        "_users": api_module._users,
        "_resumes": getattr(api_module, "_resumes", None),
        "_applications": getattr(api_module, "_applications", None),
        "_jobs": api_module._jobs,
        "_crawl_tasks": api_module._crawl_tasks,
        "_settings_store": getattr(api_module, "_settings_store", None),
        "_PERSONAL_MODE": api_module._PERSONAL_MODE,
        "_refresh_service": api_module._refresh_service,
    }
    db_path = tmp_path / "refresh-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._crawl_tasks = CrawlTaskStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._refresh_service = JobRefreshService()
    return saved


def _restore_api_state(saved: dict) -> None:
    for name, value in saved.items():
        setattr(api_module, name, value)


def _auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/auth/signup",
        json={"email": "refresh@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "refresh@example.com", "password": "password-123"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}
