"""API tests for the settings page runtime status and reset actions."""

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
import resualign.config as config_module
from resualign.api import app
from resualign.api.routers.settings import mask_api_key
from resualign.jobs import JobRegistry
from resualign.llm_nodes import LLMNodeStore
from resualign.llm_usage import LLMUsageStore
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore, default_settings
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None


def _config(api_key="sk-test"):
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_settings_stores(tmp_path):
    global _auth_cache
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
        "llm_nodes": getattr(api_module, "_llm_nodes", None),
        "llm_usage": getattr(api_module, "_llm_usage", None),
        "runtime_llm": dict(config_module.RUNTIME_LLM_OVERRIDE),
    }
    db_path = tmp_path / "settings.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._llm_nodes = LLMNodeStore(db_path=db_path)
    api_module._llm_usage = LLMUsageStore(db_path=db_path)
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
    api_module._registry = saved["registry"]
    api_module._users = saved["users"]
    api_module._resumes = saved["resumes"]
    api_module._applications = saved["applications"]
    api_module._jobs = saved["jobs"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    api_module._payloads = saved["payloads"]
    api_module._import_batches = saved["import_batches"]
    api_module._settings_store = saved["settings"]
    api_module._llm_nodes = saved["llm_nodes"]
    api_module._llm_usage = saved["llm_usage"]
    config_module.RUNTIME_LLM_OVERRIDE.update(saved["runtime_llm"])
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "settings@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "settings@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def _create_resume():
    r = client.post(
        "/api/master-resumes",
        json={"title": "Settings Resume", "content": "Python developer."},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _create_job():
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend 20-30K",
                "company": "Acme",
                "location": "Shanghai",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 201
    return r.json()


def test_settings_status_reports_llm_and_data_counts():
    _create_resume()
    _create_job()
    with patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.get("/api/settings/status", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_configured"] is True
    assert body["provider"] == "deepseek"
    assert body["model"] == "test-model"
    assert body["personal_mode"] is False
    assert body["resume_count"] == 1
    assert body["job_count"] == 1
    assert body["application_count"] == 0


def test_settings_status_shows_missing_api_key():
    with patch(
        "resualign.api.build_config",
        return_value=_config(api_key=""),
    ):
        r = client.get("/api/settings/status", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["api_key_configured"] is False


def test_settings_reset_restores_builtin_defaults():
    headers = _auth_headers()
    defaults = default_settings()
    changed = {
        "classification_vocabulary": {
            "job_functions": ["后端"],
            "seniorities": ["高级"],
            "statuses": ["已投递"],
        },
    }
    r = client.put("/api/settings", json=changed, headers=headers)
    assert r.status_code == 200
    assert r.json()["classification_vocabulary"]["job_functions"] == ["后端"]

    r = client.post("/api/settings/reset", headers=headers)
    assert r.status_code == 200
    restored = r.json()
    assert restored["classification_vocabulary"] == defaults["classification_vocabulary"]
    assert restored["llm_provider"] is None
    assert restored["llm_model"] is None


def test_settings_hot_swaps_llm_model_without_restart():
    headers = _auth_headers()
    r = client.put(
        "/api/settings",
        json={"llm_provider": "openrouter", "llm_model": "test-openrouter-model"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["llm_provider"] == "openrouter"
    assert r.json()["llm_model"] == "test-openrouter-model"

    config = api_module.build_config()
    assert config.provider == "openrouter"
    assert config.model == "test-openrouter-model"

    r = client.post("/api/settings/reset", headers=headers)
    assert r.status_code == 200
    config = api_module.build_config()
    assert config.provider == "deepseek"
    assert config.model != "test-openrouter-model"


def test_settings_rejects_unknown_provider():
    r = client.put(
        "/api/settings",
        json={"llm_provider": "not-a-provider", "llm_model": "x"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# LLM api_key persistence, masking, and build_config priority
# ---------------------------------------------------------------------------


def test_mask_api_key_hides_secret():
    assert mask_api_key(None) is None
    assert mask_api_key("") is None
    assert mask_api_key("abc") == "••••"
    masked = mask_api_key("sk-1234567890abcd")
    assert masked == "sk-1••••abcd"
    assert "sk-1234567890abcd" not in masked


def test_put_settings_persists_llm_and_masks_api_key():
    headers = _auth_headers()
    r = client.put(
        "/api/settings",
        json={
            "llm": {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "api_key": "sk-secret-1234567890",
                "base_url": "https://api.deepseek.com",
            }
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    llm = body["llm"]
    assert llm["provider"] == "deepseek"
    assert llm["model"] == "deepseek-chat"
    assert llm["base_url"] == "https://api.deepseek.com"
    assert llm["api_key"] is not None
    assert "sk-secret-1234567890" not in llm["api_key"]
    assert "••••" in llm["api_key"]
    # Legacy top-level fields stay in sync for older clients.
    assert body["llm_provider"] == "deepseek"
    assert body["llm_model"] == "deepseek-chat"

    r = client.get("/api/settings", headers=headers)
    assert r.status_code == 200
    llm = r.json()["llm"]
    assert llm["api_key"] is not None
    assert "sk-secret-1234567890" not in llm["api_key"]


def test_put_settings_llm_partial_update_keeps_other_fields():
    headers = _auth_headers()
    client.put(
        "/api/settings",
        json={"llm": {"provider": "deepseek", "model": "m1", "api_key": "sk-abc"}},
        headers=headers,
    )
    r = client.put(
        "/api/settings",
        json={"llm": {"model": "m2"}},
        headers=headers,
    )
    assert r.status_code == 200
    llm = r.json()["llm"]
    assert llm["provider"] == "deepseek"
    assert llm["model"] == "m2"
    assert llm["api_key"] is not None  # untouched by the partial update


def test_put_settings_llm_clear_api_key():
    headers = _auth_headers()
    client.put(
        "/api/settings",
        json={"llm": {"provider": "deepseek", "api_key": "sk-to-clear"}},
        headers=headers,
    )
    r = client.put(
        "/api/settings",
        json={"llm": {"api_key": None}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["llm"]["api_key"] is None
    r = client.get("/api/settings", headers=headers)
    assert r.json()["llm"]["api_key"] is None


def test_put_settings_legacy_llm_provider_model_still_works():
    headers = _auth_headers()
    r = client.put(
        "/api/settings",
        json={"llm_provider": "openrouter", "llm_model": "legacy-model"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["llm_provider"] == "openrouter"
    assert body["llm_model"] == "legacy-model"
    assert body["llm"]["provider"] == "openrouter"
    assert body["llm"]["model"] == "legacy-model"


def test_put_settings_llm_rejects_unknown_provider():
    r = client.put(
        "/api/settings",
        json={"llm": {"provider": "not-a-provider", "model": "x"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_put_settings_llm_rejects_model_without_provider():
    r = client.put(
        "/api/settings",
        json={"llm": {"model": "x"}},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_settings_reset_clears_saved_llm():
    headers = _auth_headers()
    client.put(
        "/api/settings",
        json={"llm": {"provider": "deepseek", "model": "m", "api_key": "sk-x"}},
        headers=headers,
    )
    r = client.post("/api/settings/reset", headers=headers)
    assert r.status_code == 200
    restored = r.json()
    assert restored["llm_provider"] is None
    assert restored["llm_model"] is None
    assert restored["llm"]["provider"] is None
    assert restored["llm"]["api_key"] is None


@contextmanager
def _personal_mode():
    """Context manager enabling personal mode for stored-LLM resolution."""
    saved = api_module._PERSONAL_MODE
    api_module._PERSONAL_MODE = True
    try:
        yield
    finally:
        api_module._PERSONAL_MODE = saved

def test_build_config_uses_stored_llm_in_personal_mode():
    with _personal_mode():
        api_module._settings_store.update_settings(
            "local",
            {
                "llm": {
                    "provider": "deepseek",
                    "model": "stored-model",
                    "api_key": "sk-stored-key",
                }
            },
        )
        with patch("resualign.config.EnvSettings") as mock_env:
            mock_env.return_value.llm_provider = "deepseek"
            mock_env.return_value.deepseek_api_key = "env-key"
            mock_env.return_value.deepseek_model = "env-model"
            config = api_module.build_config()
        assert config.provider == "deepseek"
        assert config.api_key == "sk-stored-key"
        assert config.model == "stored-model"


def test_build_config_falls_back_to_env_when_store_empty():
    with _personal_mode():
        with patch("resualign.config.EnvSettings") as mock_env:
            mock_env.return_value.llm_provider = "deepseek"
            mock_env.return_value.deepseek_api_key = "env-key"
            mock_env.return_value.deepseek_model = "env-model"
            config = api_module.build_config()
        assert config.api_key == "env-key"
        assert config.model == "env-model"


def test_build_config_explicit_kwargs_beat_stored():
    with _personal_mode():
        api_module._settings_store.update_settings(
            "local",
            {"llm": {"provider": "deepseek", "api_key": "sk-stored"}},
        )
        config = api_module.build_config(provider="openrouter", api_key="sk-cli")
        assert config.provider == "openrouter"
        assert config.api_key == "sk-cli"


def test_build_config_ignores_stored_key_for_different_provider():
    with _personal_mode():
        api_module._settings_store.update_settings(
            "local",
            {"llm": {"provider": "deepseek", "api_key": "sk-deepseek"}},
        )
        with patch("resualign.config.EnvSettings") as mock_env:
            mock_env.return_value.llm_provider = "deepseek"
            mock_env.return_value.deepseek_api_key = ""
            mock_env.return_value.openrouter_api_key = ""
            config = api_module.build_config(provider="openrouter")
        assert config.provider == "openrouter"
        assert config.api_key == ""


def test_build_config_stored_kwarg_priority_over_env():
    with patch("resualign.config.EnvSettings") as mock_env:
        mock_env.return_value.llm_provider = "deepseek"
        mock_env.return_value.deepseek_api_key = "env-key"
        config = config_module.build_config(
            stored={"provider": "deepseek", "api_key": "stored-key"}
        )
    assert config.api_key == "stored-key"


def test_build_config_stored_empty_fields_fall_through_to_env():
    with patch("resualign.config.EnvSettings") as mock_env:
        mock_env.return_value.llm_provider = "deepseek"
        mock_env.return_value.deepseek_api_key = "env-key"
        config = config_module.build_config(stored={"provider": "deepseek"})
    assert config.api_key == "env-key"


# ---------------------------------------------------------------------------
# POST /api/settings/test-connection
# ---------------------------------------------------------------------------


def _status_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=response
    )


def test_test_connection_reports_missing_key():
    with patch("resualign.api.build_config", return_value=_config(api_key="")):
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "API Key" in body["message"]


def test_test_connection_success():
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "httpx.post"
    ) as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "deepseek" in body["message"]
    assert mock_post.call_args.kwargs["json"]["model"] == "test-model"
    assert (
        mock_post.call_args.kwargs["headers"]["Authorization"]
        == "Bearer sk-test"
    )


def test_test_connection_auth_failure():
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "httpx.post", side_effect=_status_error(401)
    ):
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "认证失败" in body["message"]


def test_test_connection_model_not_found():
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "httpx.post", side_effect=_status_error(404)
    ):
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.json()["ok"] is False
    assert "模型或端点不存在" in r.json()["message"]


def test_test_connection_timeout():
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "httpx.post", side_effect=httpx.TimeoutException("timed out")
    ):
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.json()["ok"] is False
    assert "超时" in r.json()["message"]


def test_test_connection_network_error():
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "httpx.post", side_effect=httpx.ConnectError("connection refused")
    ):
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.json()["ok"] is False
    assert "网络错误" in r.json()["message"]


def test_test_connection_ollama_without_key_attempts_request():
    ollama_cfg = ResuAlignConfig(
        provider="ollama",
        api_key="",
        model="llama3",
        base_url="http://localhost:11434/v1",
    )
    with patch(
        "resualign.api.build_config", return_value=ollama_cfg
    ), patch("httpx.post") as mock_post:
        mock_post.return_value.raise_for_status.return_value = None
        r = client.post(
            "/api/settings/test-connection", json={}, headers=_auth_headers()
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert mock_post.call_args.kwargs["json"]["model"] == "llama3"
    assert "Authorization" not in mock_post.call_args.kwargs["headers"]


def test_test_connection_form_overrides_stored_config():
    with _personal_mode():
        api_module._settings_store.update_settings(
            "local",
            {
                "llm": {
                    "provider": "deepseek",
                    "model": "stored-model",
                    "api_key": "sk-stored-key",
                }
            },
        )
        with patch("httpx.post") as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            r = client.post(
                "/api/settings/test-connection",
                json={
                    "provider": "openrouter",
                    "model": "form-model",
                    "api_key": "sk-form-key",
                },
                headers=_auth_headers(),
            )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        sent = mock_post.call_args.kwargs["json"]
        assert sent["model"] == "form-model"
        assert (
            mock_post.call_args.kwargs["headers"]["Authorization"]
            == "Bearer sk-form-key"
        )


def test_test_connection_uses_stored_config_without_body():
    with _personal_mode():
        api_module._settings_store.update_settings(
            "local",
            {
                "llm": {
                    "provider": "deepseek",
                    "model": "stored-model",
                    "api_key": "sk-stored-key",
                }
            },
        )
        with patch("httpx.post") as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            r = client.post(
                "/api/settings/test-connection", json={}, headers=_auth_headers()
            )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        sent = mock_post.call_args.kwargs["json"]
        assert sent["model"] == "stored-model"
        assert (
            mock_post.call_args.kwargs["headers"]["Authorization"]
            == "Bearer sk-stored-key"
        )
