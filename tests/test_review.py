"""GET /api/review — weekly delivery review aggregation."""

from __future__ import annotations

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
    """Isolate review tests on a throwaway database (dashboard 模式）。"""
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
    db_path = tmp_path / "review.db"
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


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "review@example.com", "password": "password-123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "review@example.com", "password": "password-123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _tenant_id() -> str:
    """Return the signed-up user's id (the store tenant scoping key)."""
    return client.get(
        "/api/auth/me", headers=_auth_headers()
    ).json()["user_id"]


def _create_job(tenant_id: str, **overrides):
    payload = {"title": "Review Job", "jd_text": f"JD text {time.time()}{id(overrides)}"}
    payload.update(overrides)
    return api_module._jobs.create_job(tenant_id=tenant_id, **payload)


def test_review_requires_auth():
    assert client.get("/api/review").status_code in (401, 403)


def test_review_empty_tenant():
    r = client.get("/api/review", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert len(body["week_pace"]) == 7
    assert sum(item["count"] for item in body["week_pace"]) == 0
    assert body["actions"]["overdue_next_steps"] == []
    # 零样本：两组归因都是 0，不展示比率
    assert body["attribution"]["aligned_pass_rate"] is None
    assert body["attribution"]["unaligned_pass_rate"] is None


def test_review_pace_counts_applied_dates():
    tenant = _tenant_id()
    job_id = _create_job(tenant, title="本周投递")["job_id"]
    today = time.strftime("%Y-%m-%d")
    api_module._jobs.update_job(
        tenant, job_id, status="applied", applied_at=f"{today}T09:00:00"
    )
    r = client.get("/api/review", headers=_auth_headers())
    body = r.json()
    today_count = next(
        item["count"] for item in body["week_pace"] if item["date"] == today
    )
    assert today_count == 1
    assert body["stage_distribution"]["applied"] == 1


def test_review_action_lists_rules():
    tenant = _tenant_id()
    # 逾期 next_step
    j1 = _create_job(tenant, title="逾期跟进")["job_id"]
    api_module._jobs.update_job(
        tenant,
        j1,
        status="applied",
        applied_at="2026-08-01",
        next_step="跟进 HR",
        next_step_due_at="2026-08-10T09:00:00",
    )
    # 临近截止（deadline 在 7 天内）
    j2 = _create_job(tenant, title="临近截止")["job_id"]
    soon = time.strftime("%Y-%m-%d", time.localtime(time.time() + 3 * 86400))
    api_module._jobs.update_job(tenant, j2, status="applied", applied_at="2026-08-01", deadline=soon)
    # 已过期 deadline 不进"临近截止"
    j3 = _create_job(tenant, title="过期截止")["job_id"]
    api_module._jobs.update_job(
        tenant, j3, status="applied", applied_at="2026-08-01", deadline="2026-01-01"
    )
    # draft 状态不进行动清单
    _create_job(tenant, title="草稿不进清单")

    r = client.get("/api/review", headers=_auth_headers())
    body = r.json()
    overdue_ids = {j["job_id"] for j in body["actions"]["overdue_next_steps"]}
    due_ids = {j["job_id"] for j in body["actions"]["due_soon"]}
    assert j1 in overdue_ids
    assert j2 in due_ids
    assert j3 not in due_ids
    assert "草稿不进清单" not in str(body["actions"])


def test_review_attribution_comparison_and_small_sample_guard():
    tenant = _tenant_id()
    # 对齐组 3 条（过筛 2）
    for i in range(3):
        j = _create_job(tenant, title=f"对齐{i}")["job_id"]
        api_module._jobs.update_job(
            tenant, j, status="applied", applied_at="2026-08-01",
            alignment_status="succeeded",
            application_result="screen_pass" if i < 2 else "ats_reject",
        )
    # 未对齐组仅 1 条 → 比率 None（样本不足），只报计数
    j = _create_job(tenant, title="未对齐")["job_id"]
    api_module._jobs.update_job(
        tenant, j, status="applied", applied_at="2026-08-01",
        application_result="screen_pass",
    )
    r = client.get("/api/review", headers=_auth_headers())
    attr = r.json()["attribution"]
    assert attr["aligned_total"] == 3
    assert attr["aligned_pass"] == 2
    assert attr["aligned_pass_rate"] == 0.667
    assert attr["unaligned_total"] == 1
    assert attr["unaligned_pass_rate"] is None


def test_deadline_patch_roundtrip_and_clear():
    tenant = _tenant_id()
    job_id = _create_job(tenant, title="deadline 往返")["job_id"]
    r = client.patch(
        f"/api/jobs/{job_id}",
        json={"deadline": "2026-09-15"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["deadline"] == "2026-09-15"
    # 列表透出
    jobs = client.get("/api/jobs", headers=_auth_headers()).json()
    row = next(j for j in jobs if j["job_id"] == job_id)
    assert row["deadline"] == "2026-09-15"
    # 空串清除
    r = client.patch(
        f"/api/jobs/{job_id}", json={"deadline": ""}, headers=_auth_headers()
    )
    assert r.status_code == 200
    assert r.json()["deadline"] is None
