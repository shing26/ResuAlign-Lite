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
