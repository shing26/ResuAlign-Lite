"""MVP-10 cost guardrails: daily LLM cap, cost estimate, and recording."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.llm import OpenAIClient, register_daily_usage_recorder
from resualign.llm_usage import (
    LLMUsageStore,
    estimate_call_cost,
    llm_tenant_context,
)
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore

client = TestClient(app)
_auth_cache = None


@pytest.fixture(autouse=True)
def temp_cost_stores(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "settings": api_module._settings_store,
        "llm_usage": api_module._llm_usage,
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "cost.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._llm_usage = LLMUsageStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    _auth_cache = None
    yield
    api_module._registry = saved["registry"]
    api_module._users = saved["users"]
    api_module._settings_store = saved["settings"]
    api_module._llm_usage = saved["llm_usage"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "cost@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "cost@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def test_settings_roundtrip_daily_cap_and_prices():
    headers = _auth_headers()
    r = client.put(
        "/api/settings",
        json={
            "daily_llm_cap": 12,
            "llm_cost_per_1k_in": 0.5,
            "llm_cost_per_1k_out": 1.5,
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["daily_llm_cap"] == 12
    assert body["llm_cost_per_1k_in"] == 0.5
    assert body["llm_cost_per_1k_out"] == 1.5

    r = client.get("/api/settings", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["daily_llm_cap"] == 12
    assert body["llm_cost_per_1k_in"] == 0.5
    assert body["llm_cost_per_1k_out"] == 1.5


def test_settings_rejects_negative_cap_and_prices():
    headers = _auth_headers()
    for payload in (
        {"daily_llm_cap": -1},
        {"llm_cost_per_1k_in": -0.1},
        {"llm_cost_per_1k_out": -1.0},
    ):
        r = client.put("/api/settings", json=payload, headers=headers)
        assert r.status_code == 422


def test_usage_store_increments_and_switches_day(tmp_path):
    store = LLMUsageStore(db_path=tmp_path / "usage.db")
    store.record_call("t1", usage_date="2026-08-17", estimated_cost=1.25)
    store.record_call("t1", usage_date="2026-08-17", estimated_cost=1.25)
    store.record_call("t1", usage_date="2026-08-18", estimated_cost=0.5)

    day1 = store.get_usage("t1", usage_date="2026-08-17")
    assert day1["calls"] == 2
    assert day1["estimated_cost"] == 2.5

    day2 = store.get_usage("t1", usage_date="2026-08-18")
    assert day2["calls"] == 1
    assert day2["estimated_cost"] == 0.5


def test_estimate_call_cost():
    assert estimate_call_cost(0.5, 1.5) == 2.5
    assert estimate_call_cost(None, None) == 0.0


def test_recorder_skips_unbound_and_counts_tenant(monkeypatch):
    from resualign.api.services.cost_guard import record_daily_llm_usage

    original = api_module._settings_store
    monkeypatch.setattr(
        api_module,
        "_settings_store",
        SettingsStore(db_path=api_module._settings_store.db_path),
    )
    register_daily_usage_recorder(record_daily_llm_usage)
    try:
        record_daily_llm_usage()
        assert api_module._llm_usage.get_usage("t1")["calls"] == 0

        with llm_tenant_context("t1"):
            record_daily_llm_usage()
            record_daily_llm_usage()
        usage = api_module._llm_usage.get_usage("t1")
        assert usage["calls"] == 2
    finally:
        register_daily_usage_recorder(None)
        monkeypatch.setattr(api_module, "_settings_store", original)


def test_openai_retries_record_once(httpx_mock, tmp_path, monkeypatch):
    from resualign.api.services.cost_guard import record_daily_llm_usage

    monkeypatch.setattr(
        api_module,
        "_settings_store",
        SettingsStore(db_path=tmp_path / "retry.db"),
    )
    register_daily_usage_recorder(record_daily_llm_usage)
    client_obj = OpenAIClient(
        ResuAlignConfig(provider="deepseek", api_key="sk-test", model="m1")
    )
    client_obj.max_retries = 1
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"ok": true}'}}]}
    )
    try:
        with llm_tenant_context("t1"):
            client_obj.chat_json("system", "user")
        assert api_module._llm_usage.get_usage("t1")["calls"] == 1
    finally:
        register_daily_usage_recorder(None)


def test_enforce_cap_rejects_when_reached():
    api_module._settings_store.update_settings("t1", {"daily_llm_cap": 1})
    api_module._llm_usage.record_call("t1")
    with pytest.raises(HTTPException) as exc_info:
        api_module.enforce_daily_llm_cap("t1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "llm_daily_cap_reached"


def test_analyze_route_returns_429_without_queuing():
    headers = _auth_headers()
    user = client.get("/api/auth/me", headers=headers).json()
    api_module._settings_store.update_settings(
        user["user_id"],
        {"daily_llm_cap": 0},
    )
    with patch("resualign.api._queue_job") as mock_queue:
        r = client.post(
            "/api/analyze",
            json={"resume_text": "Python", "jd_text": "Backend"},
            headers=headers,
        )
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "llm_daily_cap_reached"
    mock_queue.assert_not_called()


def test_ops_metrics_daily_block():
    api_module._settings_store.update_settings("local", {"daily_llm_cap": 3})
    api_module._llm_usage.record_call("local")
    r = client.get("/api/ops/metrics")
    assert r.status_code == 200
    daily = r.json()["llm"]["daily"]
    assert daily["calls"] == 1
    assert daily["cap"] == 3
    assert daily["blocked"] is False
    assert daily["remaining"] == 2
    assert daily["estimated_cost"] == 0.0


def test_settings_status_reports_daily_usage():
    headers = _auth_headers()
    user = client.get("/api/auth/me", headers=headers).json()
    api_module._settings_store.update_settings(
        user["user_id"],
        {"daily_llm_cap": 4, "llm_cost_per_1k_in": 0.5},
    )
    api_module._llm_usage.record_call(
        user["user_id"],
        estimated_cost=estimate_call_cost(0.5, None),
    )
    r = client.get("/api/settings/status", headers=headers)
    assert r.status_code == 200
    daily = r.json()["daily"]
    assert daily["calls"] == 1
    assert daily["cap"] == 4
    assert daily["remaining"] == 3
    assert daily["blocked"] is False


# ---------------------------------------------------------------------------
# P1-1（2026-09-06 安全审查 #77）：每日 cap 原子预留——堵 check-then-spend 竞态
# ---------------------------------------------------------------------------


def test_reserve_call_stops_at_cap(tmp_path):
    store = LLMUsageStore(db_path=tmp_path / "usage.db")
    assert store.reserve_call("t1", cap=2) is True
    assert store.reserve_call("t1", cap=2) is True
    assert store.reserve_call("t1", cap=2) is False
    usage = store.get_usage("t1")
    assert usage["calls"] == 0
    assert usage["reserves"] == 2


def test_concurrent_reserve_never_exceeds_cap(tmp_path):
    import threading

    store = LLMUsageStore(db_path=tmp_path / "usage.db")
    granted = []
    lock = threading.Lock()

    def attempt():
        ok = store.reserve_call("t1", cap=5)
        with lock:
            granted.append(ok)

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for ok in granted if ok) == 5
    assert store.get_usage("t1")["reserves"] == 5


def test_record_call_consumes_reservation(tmp_path):
    store = LLMUsageStore(db_path=tmp_path / "usage.db")
    store.reserve_call("t1", cap=3)
    store.record_call("t1")
    usage = store.get_usage("t1")
    assert usage["calls"] == 1
    assert usage["reserves"] == 0


def test_release_call_returns_unconsumed_slot(tmp_path):
    store = LLMUsageStore(db_path=tmp_path / "usage.db")
    store.reserve_call("t1", cap=2)
    store.release_call("t1")
    usage = store.get_usage("t1")
    assert usage["reserves"] == 0
    # 释放后可以再次预留
    assert store.reserve_call("t1", cap=2) is True


def test_enforce_reserves_atomically_and_blocks_second_entry():
    api_module._settings_store.update_settings("t1", {"daily_llm_cap": 1})
    # 第一次入队成功并占住唯一名额
    api_module.enforce_daily_llm_cap("t1")
    assert api_module._llm_usage.get_usage("t1")["reserves"] == 1
    # 并发/后续入队被原子条件递增挡下（旧的 check-then-spend 会整体击穿）
    with pytest.raises(HTTPException) as exc_info:
        api_module.enforce_daily_llm_cap("t1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "llm_daily_cap_reached"
    # 真实调用发生 → 消费预留，额度不再被占
    api_module._llm_usage.record_call("t1")
    assert api_module._llm_usage.get_usage("t1")["reserves"] == 0


def test_run_job_releases_slot_when_no_llm_calls():
    """入队预留了 cap 名额但任务零 LLM 调用（缓存全命中/早失败）→ 释放。"""
    import time as _time

    from resualign.models import (
        GapReport,
        JDProfile,
        Report,
        TailoredResume,
    )

    headers = _auth_headers()
    user = client.get("/api/auth/me", headers=headers).json()
    api_module._settings_store.update_settings(
        user["user_id"], {"daily_llm_cap": 5}
    )
    resume = client.post(
        "/api/master-resumes",
        json={"title": "R", "content": "Python developer."},
        headers=headers,
    ).json()
    with patch("resualign.api._classify_job", return_value={}):
        job = client.post(
            "/api/jobs",
            json={
                "title": "B",
                "jd_text": f"Python backend {_time.time_ns()}",
            },
            headers=headers,
        ).json()
    report = Report(
        score=80,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(must_have_skills=["Python"]),
        gap_report=GapReport(missing_keywords=[]),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI"},
            diffs=[],
        ),
        diffs=[],
    )
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config",
        return_value=ResuAlignConfig(
            provider="deepseek", api_key="sk-test", model="test-model"
        ),
    ):
        queued = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=headers,
        )
    assert queued.status_code == 202
    analysis_job_id = queued.json()["job_id"]
    # 入队已预留 1 个名额
    assert api_module._llm_usage.get_usage(user["user_id"])["reserves"] == 1
    with patch("resualign.api.build_config"), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)
    usage = api_module._llm_usage.get_usage(user["user_id"])
    assert usage["calls"] == 0
    assert usage["reserves"] == 0
