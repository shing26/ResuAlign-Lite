"""Tests for the unified pipeline board status model and bulk updates."""

import time
from unittest.mock import patch

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
_auth_cache = None
_other_cache = None

LEGACY_DRAFT = "\u672a\u6295\u9012"  # 未投递
LEGACY_APPLIED = "\u5df2\u6295\u9012"  # 已投递


def _classify(jd_text, job_functions=None, seniorities=None, **kwargs):
    return {}


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache, _other_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": api_module._resumes,
        "applications": api_module._applications,
        "jobs": api_module._jobs,
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "settings": api_module._settings_store,
    }
    db_path = tmp_path / "pipeline-board.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    _auth_cache = None
    _other_cache = None
    yield
    for key, value in saved.items():
        setattr(api_module, key, value)
    _auth_cache = None
    _other_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "board@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "board@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _other_headers():
    global _other_cache
    if _other_cache is not None:
        return _other_cache
    client.post(
        "/api/auth/signup",
        json={"email": "other-board@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "other-board@example.com", "password": "password-123"},
    ).json()["token"]
    _other_cache = {"Authorization": f"Bearer {token}"}
    return _other_cache


def _create_job(**overrides):
    payload = {
        "title": "Backend Engineer",
        "jd_text": "Python backend engineer with Redis.",
    }
    payload.update(overrides)
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post("/api/jobs", json=payload, headers=_auth_headers())
    assert r.status_code == 201
    return r.json()


def test_board_status_migration_maps_legacy_chinese_status(tmp_path):
    store = JobLibraryStore(db_path=tmp_path / "store.db")
    job = store.create_job(
        tenant_id="tenant-1",
        title="Legacy job",
        jd_text="Legacy JD text",
        status=LEGACY_APPLIED,
    )

    assert job["status"] == LEGACY_APPLIED
    assert job["status_canonical"] == "applied"
    assert job["status_label"] == LEGACY_APPLIED
    by_canonical = store.list_jobs("tenant-1", status="applied")
    by_legacy = store.list_jobs("tenant-1", status=LEGACY_APPLIED)
    assert [item["job_id"] for item in by_canonical] == [job["job_id"]]
    assert [item["job_id"] for item in by_legacy] == [job["job_id"]]


def test_timeline_fields_round_trip_via_api():
    with patch("resualign.api._classify_job", side_effect=_classify):
        created = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer.",
            },
            headers=_auth_headers(),
        )
    assert created.status_code == 201
    job_id = created.json()["job_id"]

    updated = client.patch(
        f"/api/jobs/{job_id}",
        json={
            "status": "applied",
            "applied_at": "2026-08-04T10:30",
            "next_step": "\u51c6\u5907\u9762\u8bd5",
            "notes": "\u5df2\u6295\u9012\u5185\u63a8",
            "offer_at": "2026-08-10T12:00",
            "rejected_at": "",
        },
        headers=_auth_headers(),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["status"] == "applied"
    assert body["applied_at"] == "2026-08-04T10:30"
    assert body["next_step"] == "\u51c6\u5907\u9762\u8bd5"
    assert body["notes"] == "\u5df2\u6295\u9012\u5185\u63a8"
    # ADR-0027: moving to applied clears later-stage offer_at even when passed.
    assert body["offer_at"] is None
    # U10: an empty string clears a timeline field (NULL in storage, None out).
    assert body["rejected_at"] is None


def test_patch_status_interview_auto_fills_applied_at():
    job = _create_job()
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={"status": "interview"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["applied_at"] == time.strftime("%Y-%m-%d")
    assert body["offer_at"] is None
    assert body["rejected_at"] is None


def test_kanban_bulk_status_offer_writes_offer_at_and_clears_followup():
    job = _create_job()
    job_id = job["job_id"]
    client.patch(
        f"/api/jobs/{job_id}",
        json={"status": "applied", "applied_at": "2026-08-04T10:30"},
        headers=_auth_headers(),
    )
    client.patch(
        f"/api/jobs/{job_id}",
        json={
            "next_step": "prepare",
            "next_step_due_at": "2026-08-20T09:00:00Z",
            "interview_stage": "first round",
        },
        headers=_auth_headers(),
    )

    r = client.post(
        "/api/kanban/bulk-status",
        json={
            "job_ids": [job_id],
            "status": "offer",
            "expected_status": "applied",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 1
    updated = body["results"][0]["job"]
    assert updated["offer_at"] == time.strftime("%Y-%m-%d")
    assert updated["applied_at"] == "2026-08-04T10:30"
    assert updated["next_step"] is None
    assert updated["next_step_due_at"] is None
    assert updated["interview_stage"] is None
    assert updated["rejected_at"] is None


def test_kanban_bulk_status_withdrawn_keeps_history_and_clears_followup():
    job = _create_job()
    job_id = job["job_id"]
    client.patch(
        f"/api/jobs/{job_id}",
        json={"status": "applied", "applied_at": "2026-08-04T10:30"},
        headers=_auth_headers(),
    )
    client.patch(
        f"/api/jobs/{job_id}",
        json={
            "next_step": "final round",
            "next_step_due_at": "2026-08-25T09:00:00Z",
            "interview_stage": "final round",
        },
        headers=_auth_headers(),
    )

    r = client.post(
        "/api/kanban/bulk-status",
        json={
            "job_ids": [job_id],
            "status": "withdrawn",
            "expected_status": "applied",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 1
    updated = body["results"][0]["job"]
    assert updated["applied_at"] == "2026-08-04T10:30"
    assert updated["rejected_at"] == time.strftime("%Y-%m-%d")
    assert updated["next_step"] is None
    assert updated["next_step_due_at"] is None
    assert updated["interview_stage"] is None
    assert updated["offer_at"] is None


def test_bulk_status_endpoint_validates_tenant_ownership():
    with patch("resualign.api._classify_job", side_effect=_classify):
        mine = client.post(
            "/api/jobs",
            json={"title": "Mine", "jd_text": "Python backend A."},
            headers=_auth_headers(),
        ).json()
        theirs = client.post(
            "/api/jobs",
            json={"title": "Theirs", "jd_text": "Python backend B."},
            headers=_other_headers(),
        ).json()

    body = client.post(
        "/api/jobs/bulk-status",
        json={
            "job_ids": [mine["job_id"], theirs["job_id"], "missing-id"],
            "status": "interview",
        },
        headers=_auth_headers(),
    ).json()

    assert body["total"] == 3
    assert body["updated"] == 1
    by_id = {item["job_id"]: item for item in body["results"]}
    assert by_id[mine["job_id"]]["status"] == "updated"
    assert by_id[theirs["job_id"]]["status"] == "not_found"
    assert by_id["missing-id"]["status"] == "not_found"

    updated_job = client.get(
        f"/api/jobs/{mine['job_id']}", headers=_auth_headers()
    ).json()
    assert updated_job["status"] == "interview"
    untouched = client.get(
        f"/api/jobs/{theirs['job_id']}", headers=_other_headers()
    ).json()
    assert untouched["status"] == LEGACY_DRAFT
