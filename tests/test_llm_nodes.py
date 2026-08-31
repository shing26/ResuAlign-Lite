"""Sprint 5: multi-node LLM configuration (CRUD/activate/test), .env seed,
build_config hot-reload, tenant isolation, and the 40s guardrail timeout."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
import resualign.config as config_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.llm import OpenAIClient
from resualign.llm_nodes import LLMNodeStore
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


def _config(api_key: str = "sk-test") -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


def _node_payload(**overrides):
    payload = {
        "name": "DeepSeek 主节点",
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-secret-1234567890abcd",
        "model": "deepseek-chat",
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def temp_llm_node_stores(tmp_path):
    """Swap every API store (including the new llm_nodes store) to tmp."""
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
            "_llm_nodes",
            "_PERSONAL_MODE",
            "_payloads",
            "_import_batches",
        )
    }
    saved_runtime = dict(config_module.RUNTIME_LLM_OVERRIDE)
    db_path = tmp_path / "llm-nodes.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._llm_nodes = LLMNodeStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    config_module.clear_runtime_llm()
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
    config_module.RUNTIME_LLM_OVERRIDE.update(saved_runtime)
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None


def _auth_headers(email: str = "nodes@example.com") -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


@contextmanager
def _personal_mode():
    """Context manager enabling personal mode for stored-LLM resolution."""
    saved = api_module._PERSONAL_MODE
    api_module._PERSONAL_MODE = True
    try:
        yield
    finally:
        api_module._PERSONAL_MODE = saved


@contextmanager
def _empty_env():
    """Env without usable credentials: the .env seed never fires."""
    with patch("resualign.api.routers.nodes.EnvSettings") as mock_env:
        mock_env.return_value.llm_provider = "deepseek"
        mock_env.return_value.deepseek_api_key = ""
        mock_env.return_value.deepseek_model = ""
        mock_env.return_value.deepseek_base_url = ""
        yield


def _mock_env(mock_env, provider: str = "deepseek", **values) -> None:
    """Seed a patched EnvSettings with the attributes the code reads."""
    mock_env.return_value.llm_provider = provider
    for name in (
        "deepseek_api_key",
        "deepseek_model",
        "deepseek_base_url",
        "openrouter_api_key",
        "openrouter_model",
        "ollama_model",
    ):
        setattr(mock_env.return_value, name, values.get(name, ""))


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=response
    )


# ---------------------------------------------------------------------------
# Node CRUD roundtrip + api_key masking
# ---------------------------------------------------------------------------


def test_node_crud_roundtrip_and_api_key_masking():
    headers = _auth_headers()
    r = client.post("/api/llm/nodes", json=_node_payload(), headers=headers)
    assert r.status_code == 201
    body = r.json()
    node_id = body["node_id"]
    assert body["name"] == "DeepSeek 主节点"
    assert body["provider"] == "deepseek"
    assert body["model"] == "deepseek-chat"
    assert body["is_active"] is True  # first node auto-active
    assert body["base_url"] == "https://api.deepseek.com"
    assert "sk-secret-1234567890abcd" not in body["api_key"]
    assert "••••" in body["api_key"]

    r = client.get("/api/llm/nodes", headers=headers)
    assert r.status_code == 200
    nodes = r.json()
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == node_id
    assert "sk-secret-1234567890abcd" not in nodes[0]["api_key"]

    r = client.put(
        f"/api/llm/nodes/{node_id}",
        json={"model": "deepseek-reasoner"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["model"] == "deepseek-reasoner"

    r = client.delete(f"/api/llm/nodes/{node_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    with _empty_env():
        r = client.get("/api/llm/nodes", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


def test_create_node_rejects_unknown_provider():
    headers = _auth_headers()
    r = client.post(
        "/api/llm/nodes",
        json=_node_payload(provider="not-a-provider"),
        headers=headers,
    )
    assert r.status_code == 422


def test_update_node_can_switch_active_via_is_active_field():
    headers = _auth_headers()
    a = client.post(
        "/api/llm/nodes", json=_node_payload(name="A"), headers=headers
    ).json()
    b = client.post(
        "/api/llm/nodes", json=_node_payload(name="B"), headers=headers
    ).json()
    assert a["is_active"] is True
    assert b["is_active"] is False

    r = client.put(
        f"/api/llm/nodes/{b['node_id']}",
        json={"is_active": True},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    nodes = {
        n["node_id"]: n
        for n in client.get("/api/llm/nodes", headers=headers).json()
    }
    assert nodes[a["node_id"]]["is_active"] is False


def test_unknown_node_returns_404():
    headers = _auth_headers()
    assert (
        client.put(
            "/api/llm/nodes/nope", json={"model": "x"}, headers=headers
        ).status_code
        == 404
    )
    assert (
        client.delete("/api/llm/nodes/nope", headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            "/api/llm/nodes/nope/activate", headers=headers
        ).status_code
        == 404
    )
    assert (
        client.post("/api/llm/nodes/nope/test", headers=headers).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Activation uniqueness + DELETE-active auto-promotion
# ---------------------------------------------------------------------------


def test_activate_second_node_deactivates_first():
    headers = _auth_headers()
    a = client.post(
        "/api/llm/nodes", json=_node_payload(name="A"), headers=headers
    ).json()
    b = client.post(
        "/api/llm/nodes", json=_node_payload(name="B"), headers=headers
    ).json()
    assert a["is_active"] is True
    assert b["is_active"] is False

    r = client.post(
        f"/api/llm/nodes/{b['node_id']}/activate", headers=headers
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    nodes = {
        n["node_id"]: n
        for n in client.get("/api/llm/nodes", headers=headers).json()
    }
    assert nodes[a["node_id"]]["is_active"] is False
    assert nodes[b["node_id"]]["is_active"] is True


def test_delete_active_node_promotes_oldest_remaining():
    headers = _auth_headers()
    a = client.post(
        "/api/llm/nodes", json=_node_payload(name="A"), headers=headers
    ).json()
    b = client.post(
        "/api/llm/nodes", json=_node_payload(name="B"), headers=headers
    ).json()
    client.post(f"/api/llm/nodes/{b['node_id']}/activate", headers=headers)

    r = client.delete(f"/api/llm/nodes/{b['node_id']}", headers=headers)
    assert r.status_code == 200
    nodes = client.get("/api/llm/nodes", headers=headers).json()
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == a["node_id"]
    assert nodes[0]["is_active"] is True


# ---------------------------------------------------------------------------
# .env seed (seed-only; SQLite is authoritative afterwards)
# ---------------------------------------------------------------------------


def test_get_nodes_seeds_default_from_env_when_empty():
    headers = _auth_headers()
    with patch("resualign.api.routers.nodes.EnvSettings") as mock_env:
        _mock_env(
            mock_env,
            deepseek_api_key="sk-env-seed-key-1234567890",
            deepseek_model="deepseek-chat",
        )
        r = client.get("/api/llm/nodes", headers=headers)
    assert r.status_code == 200
    nodes = r.json()
    assert len(nodes) == 1
    node = nodes[0]
    assert node["name"] == ".env 默认"
    assert node["is_active"] is True
    assert node["provider"] == "deepseek"
    assert node["model"] == "deepseek-chat"
    assert "sk-env-seed-key" not in node["api_key"]
    assert "••••" in node["api_key"]


def test_env_seed_only_runs_when_tenant_has_no_nodes():
    headers = _auth_headers()
    created = client.post(
        "/api/llm/nodes", json=_node_payload(), headers=headers
    ).json()
    with patch("resualign.api.routers.nodes.EnvSettings") as mock_env:
        _mock_env(
            mock_env,
            deepseek_api_key="sk-env-seed-key-1234567890",
            deepseek_model="env-model",
        )
        r = client.get("/api/llm/nodes", headers=headers)
    nodes = r.json()
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == created["node_id"]
    assert nodes[0]["model"] == "deepseek-chat"  # SQLite, not env-model


def test_get_nodes_does_not_seed_without_usable_env_credentials():
    headers = _auth_headers()
    with _empty_env():
        r = client.get("/api/llm/nodes", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Node test endpoint (network mocked)
# ---------------------------------------------------------------------------


def test_node_test_success_reports_latency():
    headers = _auth_headers()
    node = client.post(
        "/api/llm/nodes",
        json=_node_payload(api_key="sk-probe-key-1234567890"),
        headers=headers,
    ).json()
    with patch("httpx.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        r = client.post(
            f"/api/llm/nodes/{node['node_id']}/test", headers=headers
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert isinstance(body["latency_ms"], float)
    assert body["latency_ms"] >= 0
    assert "deepseek" in body["message"]
    sent = mock_post.call_args.kwargs["json"]
    assert sent["model"] == "deepseek-chat"
    assert (
        mock_post.call_args.kwargs["headers"]["Authorization"]
        == "Bearer sk-probe-key-1234567890"
    )


def test_node_test_readable_failure_reason():
    headers = _auth_headers()
    node = client.post(
        "/api/llm/nodes", json=_node_payload(), headers=headers
    ).json()
    with patch("httpx.post", side_effect=_status_error(401)):
        r = client.post(
            f"/api/llm/nodes/{node['node_id']}/test", headers=headers
        )
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "http_401"
    assert "认证失败" in body["message"]
    assert isinstance(body["latency_ms"], float)


def test_node_test_timeout_readable_reason():
    headers = _auth_headers()
    node = client.post(
        "/api/llm/nodes", json=_node_payload(), headers=headers
    ).json()
    with patch(
        "httpx.post", side_effect=httpx.TimeoutException("timed out")
    ):
        r = client.post(
            f"/api/llm/nodes/{node['node_id']}/test", headers=headers
        )
    body = r.json()
    assert body["ok"] is False
    assert body["status"] == "timeout"
    assert "超时" in body["message"]


# ---------------------------------------------------------------------------
# build_config prefers the active node (hot reload, no restart)
# ---------------------------------------------------------------------------


def test_build_config_prefers_active_node():
    with _personal_mode():
        api_module._llm_nodes.create_node(
            "local",
            name="Active",
            provider="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-node-active-key",
            model="anthropic/claude-sonnet",
            is_active=True,
        )
        with patch("resualign.config.EnvSettings") as mock_env:
            _mock_env(
                mock_env,
                deepseek_api_key="env-key",
                deepseek_model="env-model",
            )
            config = api_module.build_config()
        assert config.provider == "openrouter"
        assert config.model == "anthropic/claude-sonnet"
        assert config.api_key == "sk-node-active-key"
        assert config.base_url == "https://openrouter.ai/api/v1"


def test_build_config_hot_reloads_after_activating_another_node():
    with _personal_mode():
        api_module._llm_nodes.create_node(
            "local", name="A", provider="deepseek",
            api_key="sk-a", model="model-a",
        )
        n2 = api_module._llm_nodes.create_node(
            "local", name="B", provider="openrouter",
            api_key="sk-b", model="model-b",
        )
        with patch("resualign.config.EnvSettings") as mock_env:
            _mock_env(mock_env)
            config = api_module.build_config()
        assert config.provider == "deepseek"
        assert config.model == "model-a"
        assert config.api_key == "sk-a"

        api_module._llm_nodes.activate_node("local", n2["node_id"])
        with patch("resualign.config.EnvSettings") as mock_env:
            _mock_env(mock_env)
            config = api_module.build_config()
        assert config.provider == "openrouter"
        assert config.model == "model-b"
        assert config.api_key == "sk-b"


def test_build_config_falls_back_to_legacy_llm_when_nodes_empty():
    with _personal_mode():
        api_module._settings_store.update_settings(
            "local",
            {
                "llm": {
                    "provider": "deepseek",
                    "model": "legacy-model",
                    "api_key": "sk-legacy",
                }
            },
        )
        with patch("resualign.config.EnvSettings") as mock_env:
            _mock_env(mock_env)
            config = api_module.build_config()
        assert config.provider == "deepseek"
        assert config.model == "legacy-model"
        assert config.api_key == "sk-legacy"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_tenant_isolation_nodes_not_visible_across_tenants():
    headers = _auth_headers()
    node1 = client.post(
        "/api/llm/nodes", json=_node_payload(), headers=headers
    ).json()

    client.post(
        "/api/auth/signup",
        json={
            "email": "other-nodes@example.com",
            "password": "password-123",
        },
    )
    login = client.post(
        "/api/auth/login",
        json={
            "email": "other-nodes@example.com",
            "password": "password-123",
        },
    )
    other_headers = {"Authorization": f"Bearer {login.json()['token']}"}

    with _empty_env():
        r = client.get("/api/llm/nodes", headers=other_headers)
    assert r.status_code == 200
    assert r.json() == []

    assert (
        client.put(
            f"/api/llm/nodes/{node1['node_id']}",
            json={"model": "x"},
            headers=other_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/llm/nodes/{node1['node_id']}/activate",
            headers=other_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/llm/nodes/{node1['node_id']}/test",
            headers=other_headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/llm/nodes/{node1['node_id']}",
            headers=other_headers,
        ).status_code
        == 404
    )
    # The owning tenant still sees its node untouched.
    nodes = client.get("/api/llm/nodes", headers=headers).json()
    assert [n["node_id"] for n in nodes] == [node1["node_id"]]


# ---------------------------------------------------------------------------
# T4: 40s guardrail timeout
# ---------------------------------------------------------------------------


def test_default_timeout_tuned_to_40s_in_sprint5():
    """Read/connect windows still bound worst-case hangs; transport errors now fail after one attempt (see tests/test_llm_timeout.py)."""
    assert OpenAIClient.DEFAULT_TIMEOUT == 120.0
    assert OpenAIClient.DEFAULT_CONNECT_TIMEOUT == 30.0
    inst = OpenAIClient(_config())
    try:
        assert inst._client.timeout.read == 120.0
        assert inst._client.timeout.connect == 30.0
    finally:
        inst.close()


def test_node_test_persists_health():
    """test 端点结果落库：list_nodes 返回健康三字段，供徽标与失败横幅。"""
    headers = _auth_headers()
    node = client.post(
        "/api/llm/nodes",
        json=_node_payload(api_key="sk-health-key-1234567890"),
        headers=headers,
    ).json()
    with patch("httpx.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        client.post(f"/api/llm/nodes/{node['node_id']}/test", headers=headers)
    listed = client.get("/api/llm/nodes", headers=headers).json()
    target = next(n for n in listed if n["node_id"] == node["node_id"])
    assert target["last_test_status"] == "ok"
    assert isinstance(target["last_test_latency_ms"], (int, float))
    assert target["last_test_at"] > 0


def test_test_all_probes_every_node_and_persists():
    headers = _auth_headers()
    n1 = client.post(
        "/api/llm/nodes", json=_node_payload(), headers=headers
    ).json()
    n2 = client.post(
        "/api/llm/nodes",
        json=_node_payload(model="deepseek-chat-v2"),
        headers=headers,
    ).json()
    with patch("httpx.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        r = client.post("/api/llm/nodes/test-all", headers=headers)
    assert r.status_code == 200
    results = r.json()["results"]
    assert {item["node_id"] for item in results} >= {n1["node_id"], n2["node_id"]}
    assert all(item["ok"] for item in results)
    assert all("name" in item and "is_active" in item for item in results)
    # 全部落库
    listed = client.get("/api/llm/nodes", headers=headers).json()
    assert all(n["last_test_status"] == "ok" for n in listed)
