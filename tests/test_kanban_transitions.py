"""Sprint 4: API tests for Kanban drag-transition semantics.

Covers the five-column canonical flow (未投递 -> 已投递 -> 面试中 ->
已拿Offer -> 放弃) driven through ``POST /api/kanban/bulk-status`` with
``expected_status`` as an optimistic lock, plus the per-row conflict
contract and idempotency-key replay semantics.

Contract note: a stale ``expected_status`` is NOT an HTTP 409. The bulk
endpoint returns HTTP 200 and reports each failed row as
``results[].status == "conflict"`` with ``updated: false`` so a mixed
batch can partially succeed. Frontend drag handlers must read
``results[].status`` (not the HTTP status code) to detect a race.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore, canonical_status
from resualign.jobs import JobRegistry
from resualign.workspace import MasterResumeStore, UserStore

client = TestClient(app)
_auth_cache = None

# Canonical five-column flow: draft -> applied -> interview -> offer -> withdrawn.
DRAG_CHAIN = [
    ("draft", "applied"),
    ("applied", "interview"),
    ("interview", "offer"),
    ("offer", "withdrawn"),
]


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": api_module._jobs,
        "settings_store": api_module._settings_store,
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
    }
    db_path = tmp_path / "kanban.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = api_module.ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = api_module.SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "kanban@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "kanban@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job(title: str = "Backend Engineer") -> dict:
    """Create one library job through the API (classification stubbed)."""
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": title,
                "jd_text": f"Python backend engineer with Redis for {title}.",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 201
    return r.json()


def _bulk(job_ids: list[str], status: str, expected_status: str | None = None,
          idempotency_key: str | None = None) -> dict:
    payload: dict = {"job_ids": job_ids, "status": status}
    if expected_status is not None:
        payload["expected_status"] = expected_status
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    r = client.post("/api/kanban/bulk-status", json=payload,
                    headers=_auth_headers())
    assert r.status_code == 200
    return r.json()


def _stored_status(job_id: str) -> str:
    return canonical_status(
        client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()["status"]
    )


def test_kanban_five_column_drag_chain():
    job = _create_job()
    job_id = job["job_id"]
    assert canonical_status(job["status"]) == "draft"

    for expected, target in DRAG_CHAIN:
        body = _bulk([job_id], target, expected_status=expected)
        assert body["updated"] == 1
        assert body["total"] == 1
        item = body["results"][0]
        assert item["updated"] is True
        assert item["status"] == "updated"
        assert canonical_status(item["job"]["status"]) == target
        assert _stored_status(job_id) == target

    # 放弃 is the terminal column; no further transition should exist.
    assert DRAG_CHAIN[-1][1] == "withdrawn"


def test_kanban_applied_creates_auto_followup():
    job = _create_job()
    body = _bulk([job["job_id"]], "applied", expected_status="draft")
    assert body["updated"] == 1
    item = body["results"][0]
    updated_job = item["job"]
    assert updated_job["status_canonical"] == "applied"
    assert updated_job["next_step"] == "投递后跟进"
    applied_date = date.fromisoformat(updated_job["applied_at"][:10])
    expected_date = (applied_date + timedelta(days=3)).isoformat()
    assert updated_job["next_step_due_at"].startswith(expected_date)


def test_kanban_auto_followup_can_be_disabled_in_settings():
    client.put(
        "/api/settings",
        json={"reminder": {"auto_followup_reminder": False}},
        headers=_auth_headers(),
    )
    job = _create_job()
    body = _bulk([job["job_id"]], "applied", expected_status="draft")
    item = body["results"][0]
    assert item["updated"] is True
    assert item["job"]["status_canonical"] == "applied"
    assert item["job"]["next_step"] is None
    assert item["job"]["next_step_due_at"] is None


def test_kanban_expected_status_mismatch_reports_per_row_conflict():
    """A stale expected_status yields 200 + results[].status='conflict'."""
    stale = _create_job(title="Already Applied")
    fresh = _create_job(title="Still Draft")
    # Advance `stale` to applied, keep `fresh` on draft.
    _bulk([stale["job_id"]], "applied", expected_status="draft")

    body = _bulk(
        [stale["job_id"], fresh["job_id"]],
        "interview",
        expected_status="draft",
    )
    assert body["updated"] == 1
    assert body["total"] == 2
    by_id = {item["job_id"]: item for item in body["results"]}

    assert by_id[stale["job_id"]]["updated"] is False
    assert by_id[stale["job_id"]]["status"] == "conflict"
    assert by_id[fresh["job_id"]]["updated"] is True
    assert by_id[fresh["job_id"]]["status"] == "updated"

    # Conflicts leave the stored status untouched.
    assert _stored_status(stale["job_id"]) == "applied"
    assert _stored_status(fresh["job_id"]) == "interview"


def test_kanban_stale_drag_transition_is_conflict_and_does_not_mutate():
    """Frontend race case: dragging from an outdated column must not move the card."""
    job = _create_job()
    job_id = job["job_id"]
    _bulk([job_id], "interview", expected_status="draft")

    # Card is already interview; a stale drag still says draft.
    body = _bulk([job_id], "offer", expected_status="draft")
    item = body["results"][0]
    assert item["status"] == "conflict"
    assert item["updated"] is False
    assert _stored_status(job_id) == "interview"


def test_kanban_expected_status_without_lock_moves_any_state():
    """Without expected_status the optimistic lock is off (default drag fallback)."""
    job = _create_job()
    job_id = job["job_id"]
    _bulk([job_id], "applied", expected_status="draft")
    # No lock: a retry from an unknown client state still applies.
    body = _bulk([job_id], "offer")
    assert body["updated"] == 1
    assert _stored_status(job_id) == "offer"


def test_kanban_idempotency_key_replay_returns_cached_result():
    """Replaying an idempotency key returns the original result without re-applying."""
    job = _create_job()
    job_id = job["job_id"]
    key = "drag-transition-1"

    first = _bulk([job_id], "applied", expected_status="draft", idempotency_key=key)
    assert first["updated"] == 1
    assert _stored_status(job_id) == "applied"

    # Identical replay: same body, status unchanged.
    replay = _bulk([job_id], "applied", expected_status="draft", idempotency_key=key)
    assert replay == first
    assert _stored_status(job_id) == "applied"

    # Same key with a DIFFERENT payload still returns the original cached
    # result — the key guards the operation, not the request content.
    divergent = _bulk([job_id], "offer", idempotency_key=key)
    assert divergent == first
    assert _stored_status(job_id) == "applied"
