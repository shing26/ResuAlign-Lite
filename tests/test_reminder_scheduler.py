"""Tests for the MVP-04 reminder scheduler and /api/reminders endpoint."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.scheduler import ReminderScheduler
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone(timedelta(hours=8)))
_NOW_TS = _NOW.timestamp()


def _due(hour: int, day: int = 17, month: int = 8) -> str:
    return datetime(
        2026, month, day, hour, 0, tzinfo=timezone(timedelta(hours=8))
    ).isoformat()


def _make_store(tmp_path) -> JobLibraryStore:
    return JobLibraryStore(db_path=tmp_path / "reminders.db")


def _make_active_job(
    store: JobLibraryStore,
    tenant: str,
    title: str,
    due_at: str,
) -> dict:
    job = store.create_job(
        tenant_id=tenant,
        title=title,
        jd_text=f"Python backend engineer for {title}.",
    )
    return store.update_job(
        tenant,
        job["job_id"],
        status="已投递",
        next_step_due_at=due_at,
    )


def test_store_migration_exposes_reminder_sent_at(tmp_path):
    store = _make_store(tmp_path)
    job = _make_active_job(store, "tenant-a", "Backend", _due(9, day=1))
    assert job["reminder_sent_at"] is None
    assert job["reminder_attempts"] == 0
    assert job["reminder_next_retry_at"] is None
    store.claim_due_reminders(_NOW_TS)
    fetched = store.get_job("tenant-a", job["job_id"])
    assert fetched["reminder_sent_at"] == _NOW_TS


def test_list_reminders_filters_status_and_due_window(tmp_path):
    store = _make_store(tmp_path)
    _make_active_job(store, "tenant-a", "Overdue", _due(9, day=1))
    _make_active_job(store, "tenant-a", "Today", _due(13))
    store.create_job(
        tenant_id="tenant-a",
        title="Future",
        jd_text="Future role.",
    )
    store.update_job(
        "tenant-a",
        store.create_job(
            tenant_id="tenant-a",
            title="Future Active",
            jd_text="Future active role.",
        )["job_id"],
        status="面试中",
        next_step_due_at=_due(9, day=20),
    )
    store.update_job(
        "tenant-a",
        store.create_job(
            tenant_id="tenant-a",
            title="Offer",
            jd_text="Offer role.",
        )["job_id"],
        status="已拿Offer",
        next_step_due_at=_due(9, day=1),
    )
    reminders = store.list_reminders("tenant-a", scope="today", now=_NOW_TS)
    titles = [item["title"] for item in reminders]
    assert titles == ["Overdue", "Today"]
    assert reminders[0]["overdue"] is True
    assert reminders[1]["overdue"] is False
    assert reminders[0]["status_canonical"] == "applied"


def test_scheduler_emits_without_claiming_and_success_marks_sent_once(tmp_path):
    store = _make_store(tmp_path)
    job = _make_active_job(store, "tenant-a", "Backend", _due(9, day=1))
    scheduler = ReminderScheduler(store, interval_seconds=60)
    assert len(scheduler.tick()) == 1
    # Discovery does not mark the reminder sent; delivery owns persistence.
    assert store.get_job("tenant-a", job["job_id"])["reminder_sent_at"] is None

    first = store.claim_pending_reminders(_NOW_TS)
    assert len(first) == 1
    assert store.mark_reminder_sent("tenant-a", job["job_id"], _NOW_TS) is True
    second = store.claim_pending_reminders(_NOW_TS)
    assert len(second) == 0
    assert (
        store.get_job("tenant-a", job["job_id"])["reminder_sent_at"] == _NOW_TS
    )


def test_concurrent_claims_do_not_duplicate(tmp_path):
    store = _make_store(tmp_path)
    _make_active_job(store, "tenant-a", "Backend", _due(9, day=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: store.claim_pending_reminders(_NOW_TS), range(2))
        )
    assert sum(len(result) for result in results) == 1


def test_patch_clears_reminder_sent_at_via_api(tmp_path):
    client = TestClient(app)
    saved = _save_api_state(tmp_path)
    try:
        headers = _auth_headers(client)
        tenant = client.get("/api/auth/me", headers=headers).json()["user_id"]
        job = api_module._jobs.create_job(
            tenant_id=tenant,
            title="Backend",
            jd_text="Python backend engineer.",
        )
        patched = client.patch(
            f"/api/jobs/{job['job_id']}",
            json={
                "status": "已投递",
                "next_step_due_at": _due(9, day=1),
            },
            headers=headers,
        ).json()
        assert patched["reminder_sent_at"] is None
        api_module._jobs.claim_due_reminders(_NOW_TS)
        assert (
            api_module._jobs.get_job(tenant, job["job_id"])["reminder_sent_at"]
            == _NOW_TS
        )
        client.patch(
            f"/api/jobs/{job['job_id']}",
            json={"next_step_due_at": _due(9, day=2)},
            headers=headers,
        )
        assert (
            api_module._jobs.get_job(tenant, job["job_id"])["reminder_sent_at"]
            is None
        )
    finally:
        _restore_api_state(saved)


def test_reminders_api_returns_today_and_rejects_bad_scope(tmp_path):
    client = TestClient(app)
    saved = _save_api_state(tmp_path)
    try:
        headers = _auth_headers(client)
        tenant = client.get("/api/auth/me", headers=headers).json()["user_id"]
        api_module._jobs.create_job(
            tenant_id=tenant,
            title="Backend",
            jd_text="Python backend engineer.",
        )
        job = api_module._jobs.create_job(
            tenant_id=tenant,
            title="Active",
            jd_text="Active role.",
        )
        api_module._jobs.update_job(
            tenant,
            job["job_id"],
            status="面试中",
            next_step_due_at=_due(9),
        )
        response = client.get("/api/reminders?scope=today", headers=headers)
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["job_id"] == job["job_id"]
        assert items[0]["status_canonical"] == "interview"
        assert client.get(
            "/api/reminders?scope=week", headers=headers
        ).status_code == 422
    finally:
        _restore_api_state(saved)


def _save_api_state(tmp_path) -> dict:
    saved = {
        "_registry": api_module._registry,
        "_users": api_module._users,
        "_resumes": getattr(api_module, "_resumes", None),
        "_applications": getattr(api_module, "_applications", None),
        "_jobs": api_module._jobs,
        "_settings_store": getattr(api_module, "_settings_store", None),
        "_PERSONAL_MODE": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    return saved


def _restore_api_state(saved: dict) -> None:
    for name, value in saved.items():
        setattr(api_module, name, value)


def _auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/api/auth/signup",
        json={"email": "reminder@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "reminder@example.com", "password": "password-123"},
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}
