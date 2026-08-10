"""Sprint 6 HITL webhook fan-out tests (RESUALIGN_WEBHOOK_URL).

Covers ``resualign.agent.hitl.emit_hitl_event`` and its wiring into the Sprint 3
fetcher pipeline:

* configured webhook  -> POST JSON ``{event, payload}``, never raises
* no webhook URL      -> no HTTP send, structured-log fallback
* webhook failure     -> swallowed (must not break the calling pipeline)
* ``blocker.created`` -> fired on every fetcher blocker creation (invalid URL,
  crawl failure), including through the MCP ``fetch_and_evaluate_job`` tool

The fetcher imports ``emit_hitl_event`` directly (``from ...agent.hitl import
emit_hitl_event``), so patching the *fetcher module* binding is what isolates
the wiring assertion; patching ``hitl.httpx.post`` isolates the transport.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import resualign.api as api_module
from resualign.agent.hitl import emit_hitl_event
from resualign.crawler import CrawlError
from resualign.job_library import JobLibraryStore

TEST_WEBHOOK = "https://hooks.example.test/resualign/hitl"


@pytest.fixture(autouse=True)
def _isolated_webhook_env(monkeypatch):
    """Keep a developer's real RESUALIGN_WEBHOOK_URL out of every test."""
    monkeypatch.delenv("RESUALIGN_WEBHOOK_URL", raising=False)
    yield


@pytest.fixture
def isolated_jobs(tmp_path):
    """Point the module fetcher service at a tmp job store."""
    saved = api_module._jobs
    api_module._jobs = JobLibraryStore(db_path=tmp_path / "hitl-webhook.db")
    yield api_module._jobs
    api_module._jobs = saved


# -- emit_hitl_event ---------------------------------------------------------


def test_emit_hitl_event_posts_json_when_webhook_configured(monkeypatch):
    monkeypatch.setenv("RESUALIGN_WEBHOOK_URL", TEST_WEBHOOK)
    payload = {
        "blocker_id": "b-1",
        "url": "https://example.com/jobs/1",
        "reason": "需要登录",
        "category": "login_required",
    }
    with patch("resualign.agent.hitl.httpx.post") as mock_post:
        emit_hitl_event("blocker.created", payload)

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == TEST_WEBHOOK
    assert kwargs["json"] == {"event": "blocker.created", "payload": payload}
    assert kwargs.get("timeout") is not None


def test_emit_hitl_event_without_url_never_sends(monkeypatch):
    with patch(
        "resualign.agent.hitl.httpx.post",
        side_effect=AssertionError("webhook must not be called"),
    ) as mock_post, patch("resualign.agent.hitl.log_event") as mock_log:
        emit_hitl_event("blocker.created", {"blocker_id": "b-1"})

    mock_post.assert_not_called()
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "blocker.created"
    assert mock_log.call_args.kwargs["extra"] == {"blocker_id": "b-1"}


def test_emit_hitl_event_swallows_webhook_failures(monkeypatch):
    monkeypatch.setenv("RESUALIGN_WEBHOOK_URL", TEST_WEBHOOK)
    with patch(
        "resualign.agent.hitl.httpx.post",
        side_effect=RuntimeError("connection refused"),
    ):
        emit_hitl_event("blocker.created", {"blocker_id": "b-1"})


# -- blocker.created wiring --------------------------------------------------


def test_fetcher_fires_blocker_created_on_invalid_url(isolated_jobs):
    with patch("resualign.api.services.fetcher.emit_hitl_event") as mock_emit:
        result = api_module._fetcher.submit_url(
            "hitl-tenant", "not-a-url"
        )
    assert result["status"] == "blocked"
    mock_emit.assert_called_once()
    event, payload = mock_emit.call_args.args
    assert event == "blocker.created"
    assert payload["blocker_id"] == result["blocker_id"]
    assert payload["category"] == "invalid_url"
    assert payload["url"] == "not-a-url"


def test_fetcher_fires_blocker_created_on_crawl_failure(
    isolated_jobs, monkeypatch
):
    def _boom(url, meta=None, **kwargs):
        raise CrawlError("Failed to fetch https://x: HTTP 403", category="http")

    monkeypatch.setattr(api_module, "crawl_jd", _boom)
    with patch("resualign.api.services.fetcher.emit_hitl_event") as mock_emit:
        result = api_module._fetcher.submit_url(
            "hitl-tenant", "https://example.com/jobs/1"
        )
    assert result["status"] == "blocked"
    mock_emit.assert_called_once()
    event, payload = mock_emit.call_args.args
    assert event == "blocker.created"
    assert payload["blocker_id"] == result["blocker_id"]
    assert payload["url"] == "https://example.com/jobs/1"


def test_mcp_fetch_tool_fires_blocker_created(isolated_jobs):
    try:
        from resualign.agent.mcp_server import fetch_and_evaluate_job
    except ImportError:
        pytest.skip("待 A: resualign.agent.mcp_server 依赖 mcp 未安装")

    with patch("resualign.api.services.fetcher.emit_hitl_event") as mock_emit:
        result = fetch_and_evaluate_job(
            url="not-a-url", tenant_id="hitl-mcp"
        )
    assert result["status"] == "blocked"
    mock_emit.assert_called_once()


def test_fetcher_blocker_event_reaches_webhook(isolated_jobs, monkeypatch):
    """End-to-end: configured webhook -> fetcher blocker -> POSTed JSON."""
    monkeypatch.setenv("RESUALIGN_WEBHOOK_URL", TEST_WEBHOOK)
    with patch("resualign.agent.hitl.httpx.post") as mock_post:
        result = api_module._fetcher.submit_url(
            "hitl-tenant", "not-a-url"
        )
    assert result["status"] == "blocked"
    mock_post.assert_called_once()
    body = mock_post.call_args.kwargs["json"]
    assert body["event"] == "blocker.created"
    assert body["payload"]["blocker_id"] == result["blocker_id"]
    assert body["payload"]["category"] == "invalid_url"
