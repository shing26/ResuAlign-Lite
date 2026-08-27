"""Phase A JD intake orchestrator contract tests (ADR-0029).

Covers the minimal agent loop over the MCP tool boundary:

* default tools resolve to the MCP functions, not API internals
* one fetch plus at most one decision round per URL (budget)
* blocked fetches keep the blocker pending or resolve with pasted text
* tool/policy failures degrade to the blocker path and emit observability
* queue-driven mode processes pending blockers
* full integration through the real MCP fetch tool with isolated stores
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import resualign.api as api_module
from resualign.agent import hitl as hitl_module
from resualign.agent.mcp_server import (
    fetch_and_evaluate_job,
    get_pending_blockers,
    resolve_blocker,
)
from resualign.agent.orchestrator import (
    JdIntakePolicy,
    JdIntakeTools,
    process_pending_blockers,
    run_jd_intake,
)
from resualign.agent.policy_llm import LLMJdIntakePolicy
from resualign.crawler import CrawlError
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.llm import LLMResponseError
from resualign.settings_store import SettingsStore
from resualign.workspace import MasterResumeStore, UserStore

_URL = "https://example.com/jobs/1"
_JD_TEXT = "负责后端服务开发。要求 Java 与高并发经验。月薪 25-35K。"


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    """Point every store singleton at a throwaway database for this test."""
    saved = {
        name: getattr(api_module, name)
        for name in (
            "_jobs",
            "_resumes",
            "_registry",
            "_users",
            "_settings_store",
            "_payloads",
        )
    }
    db_path = tmp_path / "orchestrator.db"
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._payloads = {}
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)


@pytest.fixture(autouse=True)
def no_llm():
    """Keep the job-creation pipeline LLM-free (classification never runs)."""
    with patch.object(
        api_module, "_settings_vocabulary", return_value=([], [])
    ), patch.object(api_module, "_classify_job", return_value={}):
        yield


@pytest.fixture(autouse=True)
def no_webhook():
    """Default to the structured-log HITL path unless a test opts in."""
    with patch.object(hitl_module, "_get_webhook_url", return_value=""):
        yield


class _StubTools:
    """Stub MCP tool contract that records every call."""

    def __init__(
        self,
        fetch_result,
        resolve_result=None,
        pending_result=None,
    ):
        self.fetch_result = fetch_result
        self.resolve_result = resolve_result or {
            "status": "error",
            "error": "unexpected resolve",
        }
        self.pending_result = pending_result or []
        self.fetch_calls = 0
        self.pending_calls = 0
        self.resolve_calls: list[tuple[str, str, str]] = []

    def as_tools(self) -> JdIntakeTools:
        return JdIntakeTools(
            fetch=self.fetch,
            pending_blockers=self.pending_blockers,
            resolve=self.resolve,
        )

    def fetch(self, url: str, tenant_id: str) -> dict:
        self.fetch_calls += 1
        return self.fetch_result

    def pending_blockers(self, tenant_id: str) -> list[dict]:
        self.pending_calls += 1
        return self.pending_result

    def resolve(self, blocker_id: str, text: str, tenant_id: str) -> dict:
        self.resolve_calls.append((blocker_id, text, tenant_id))
        return self.resolve_result


def _blocked_fetch(
    blocker_id: str = "b-1",
    category: str = "network_error",
    reason: str = "fetch failed",
) -> dict:
    return {
        "status": "blocked",
        "blocker_id": blocker_id,
        "url": _URL,
        "category": category,
        "reason": reason,
    }


def _events(mock_log) -> list[str]:
    return [call.args[1] for call in mock_log.call_args_list]


def _crawl_ok(text: str = _JD_TEXT):
    def _fetch(url, meta=None, **kwargs):
        if meta is not None:
            meta["title"] = "后端开发工程师"
            meta["company"] = "Acme"
            meta["city"] = "上海"
        return text

    return _fetch


def _crawl_error(category: str, message: str):
    def _fetch(url, meta=None, **kwargs):
        raise CrawlError(message, category=category, url=url)

    return _fetch


# -- Tool contract -----------------------------------------------------------


def test_default_tools_are_mcp_tool_functions():
    tools = JdIntakeTools.default()
    assert tools.fetch is fetch_and_evaluate_job
    assert tools.pending_blockers is get_pending_blockers
    assert tools.resolve is resolve_blocker


# -- Single-URL intake -------------------------------------------------------


def test_run_jd_intake_accepts_created_job():
    stub = _StubTools({"status": "created", "job_id": "job-1"})
    with patch("resualign.agent.orchestrator.log_event") as mock_log:
        result = run_jd_intake(_URL, tools=stub.as_tools())
    assert result["status"] == "created"
    assert result["job_id"] == "job-1"
    assert result["agent_rounds"] == 0
    assert result["tool_calls"] == 1
    assert result["budget_exceeded"] is False
    assert stub.fetch_calls == 1
    assert stub.resolve_calls == []
    assert _events(mock_log) == ["agent.decision"]


def test_run_jd_intake_returns_duplicate_without_resolving():
    stub = _StubTools(
        {"status": "duplicate", "job_id": "job-1", "reason": "已在岗位库"}
    )
    result = run_jd_intake(_URL, tools=stub.as_tools())
    assert result["status"] == "duplicate"
    assert result["job_id"] == "job-1"
    assert result["tool_calls"] == 1
    assert stub.resolve_calls == []


def test_run_jd_intake_keeps_blocker_pending_without_text():
    stub = _StubTools(_blocked_fetch())
    with patch("resualign.agent.orchestrator.log_event") as mock_log:
        result = run_jd_intake(_URL, tools=stub.as_tools())
    assert result["status"] == "blocked"
    assert result["action"] == "keep_pending"
    assert result["blocker_id"] == "b-1"
    assert result["agent_rounds"] == 1
    assert result["tool_calls"] == 1
    assert stub.resolve_calls == []
    assert "agent.decision" in _events(mock_log)


def test_run_jd_intake_resolves_retryable_blocker_with_text():
    stub = _StubTools(
        _blocked_fetch(),
        resolve_result={"status": "resolved", "job_id": "job-9"},
    )
    result = run_jd_intake(
        _URL, resolve_text=_JD_TEXT, tools=stub.as_tools()
    )
    assert result["status"] == "resolved"
    assert result["job_id"] == "job-9"
    assert result["agent_rounds"] == 1
    assert result["tool_calls"] == 2
    assert stub.resolve_calls == [("b-1", _JD_TEXT, "local")]


def test_run_jd_intake_never_resolves_without_text_even_if_policy_says_so():
    class _OvereagerPolicy:
        max_agent_rounds = 1

        def decide(self, blocker, resolve_text=""):
            return "resolve"

    stub = _StubTools(_blocked_fetch())
    result = run_jd_intake(
        _URL, policy=_OvereagerPolicy(), tools=stub.as_tools()
    )
    assert result["status"] == "blocked"
    assert result["action"] == "keep_pending"
    assert stub.resolve_calls == []


def test_run_jd_intake_keeps_human_only_blockers_pending_even_with_text():
    stub = _StubTools(_blocked_fetch(category="login_required"))
    result = run_jd_intake(
        _URL, resolve_text=_JD_TEXT, tools=stub.as_tools()
    )
    assert result["status"] == "blocked"
    assert result["action"] == "keep_pending"
    assert stub.resolve_calls == []


def test_run_jd_intake_resolve_rejection_keeps_blocker_pending():
    stub = _StubTools(
        _blocked_fetch(),
        resolve_result={"status": "error", "error": "not pending"},
    )
    with patch("resualign.agent.orchestrator.log_event") as mock_log:
        result = run_jd_intake(
            _URL, resolve_text=_JD_TEXT, tools=stub.as_tools()
        )
    assert result["status"] == "blocked"
    assert result["action"] == "resolve_failed"
    assert "not pending" in result["error"]
    assert result["tool_calls"] == 2
    assert "agent.failure" in _events(mock_log)


def test_run_jd_intake_fetch_exception_degrades_and_emits_failure():
    def boom(url, tenant_id):
        raise RuntimeError("tool exploded")

    tools = JdIntakeTools(
        fetch=boom,
        pending_blockers=lambda tenant_id: [],
        resolve=lambda *args: {},
    )
    with patch("resualign.agent.orchestrator.log_event") as mock_log:
        result = run_jd_intake(_URL, tools=tools)
    assert result["status"] == "degraded"
    assert result["error"] == "tool exploded"
    assert result["tool_calls"] == 1
    assert "agent.failure" in _events(mock_log)


def test_run_jd_intake_unexpected_tool_status_degrades():
    stub = _StubTools({"status": "weird"})
    with patch("resualign.agent.orchestrator.log_event") as mock_log:
        result = run_jd_intake(_URL, tools=stub.as_tools())
    assert result["status"] == "degraded"
    assert "unexpected fetch tool status" in result["reason"]
    assert "agent.failure" in _events(mock_log)


def test_run_jd_intake_respects_zero_decision_budget():
    stub = _StubTools(_blocked_fetch())
    policy = JdIntakePolicy(max_agent_rounds=0)
    with patch("resualign.agent.orchestrator.log_event") as mock_log:
        result = run_jd_intake(_URL, policy=policy, tools=stub.as_tools())
    assert result["status"] == "degraded"
    assert result["budget_exceeded"] is True
    assert result["blocker_id"] == "b-1"
    assert stub.resolve_calls == []
    assert "agent.budget_exceeded" in _events(mock_log)


def test_run_jd_intake_invalid_policy_action_falls_back_to_pending():
    class _BadPolicy:
        max_agent_rounds = 1

        def decide(self, blocker, resolve_text=""):
            return "launch_missiles"

    stub = _StubTools(_blocked_fetch())
    result = run_jd_intake(_URL, policy=_BadPolicy(), tools=stub.as_tools())
    assert result["status"] == "blocked"
    assert result["action"] == "keep_pending"
    assert "invalid policy action" in result["error"]
    assert stub.resolve_calls == []


def test_run_jd_intake_policy_exception_falls_back_to_pending():
    class _BoomPolicy:
        max_agent_rounds = 1

        def decide(self, blocker, resolve_text=""):
            raise ValueError("no idea")

    stub = _StubTools(_blocked_fetch())
    result = run_jd_intake(_URL, policy=_BoomPolicy(), tools=stub.as_tools())
    assert result["status"] == "blocked"
    assert result["action"] == "keep_pending"
    assert "no idea" in result["error"]
    assert stub.resolve_calls == []


def test_run_jd_intake_llm_policy_failure_falls_back_to_pending():
    class _RaisingLLMClient:
        def chat_structured(self, system, user, schema_model, model=None):
            raise LLMResponseError("provider down")

    stub = _StubTools(_blocked_fetch())
    result = run_jd_intake(
        _URL,
        policy=LLMJdIntakePolicy(client=_RaisingLLMClient()),
        tools=stub.as_tools(),
    )
    assert result["status"] == "blocked"
    assert result["action"] == "keep_pending"
    assert "provider down" in result["error"]
    assert stub.resolve_calls == []


# -- Queue-driven mode -------------------------------------------------------


def test_process_pending_blockers_applies_one_decision_per_blocker():
    pending = [
        {
            "blocker_id": "b-1",
            "url": "https://example.com/jobs/1",
            "category": "network_error",
            "reason": "timeout",
        },
        {
            "blocker_id": "b-2",
            "url": "https://example.com/jobs/2",
            "category": "login_required",
            "reason": "login",
        },
    ]
    stub = _StubTools(
        {},
        resolve_result={"status": "resolved", "job_id": "job-1"},
        pending_result=pending,
    )
    result = process_pending_blockers(
        "local", resolve_texts={"b-1": _JD_TEXT}, tools=stub.as_tools()
    )
    assert result["blockers_seen"] == 2
    assert result["blocker_decisions"] == 2
    assert result["resolved"] == 1
    assert result["blocked"] == 1
    assert result["degraded"] == 0
    assert stub.pending_calls == 1
    assert stub.resolve_calls == [("b-1", _JD_TEXT, "local")]


def test_process_pending_blockers_empty_queue_returns_zero_stats():
    stub = _StubTools({}, pending_result=[])
    result = process_pending_blockers(tools=stub.as_tools())
    assert result == {
        "blockers_seen": 0,
        "blocker_decisions": 0,
        "blocked": 0,
        "resolved": 0,
        "degraded": 0,
    }


# -- Full integration through the real MCP tools -----------------------------


def test_run_jd_intake_through_real_mcp_tools_creates_job(monkeypatch):
    tenant = "orchestrator-e2e"
    monkeypatch.setattr(api_module, "crawl_jd", _crawl_ok())
    monkeypatch.setattr(api_module, "_classify_job", lambda *a, **kw: {})

    result = run_jd_intake("https://example.com/jobs/1", tenant_id=tenant)
    assert result["status"] == "created", result
    assert result["job_id"]
    job = api_module._jobs.get_job(tenant, result["job_id"])
    assert job is not None
    assert job["source_url"] == "https://example.com/jobs/1"


def test_run_jd_intake_through_real_mcp_tools_resolves_blocker(monkeypatch):
    tenant = "orchestrator-e2e-blocked"
    monkeypatch.setattr(
        api_module, "crawl_jd", _crawl_error("network_error", "boom")
    )
    monkeypatch.setattr(api_module, "_classify_job", lambda *a, **kw: {})

    result = run_jd_intake(
        "https://example.com/jobs/2",
        tenant_id=tenant,
        resolve_text=_JD_TEXT,
    )
    assert result["status"] == "resolved", result
    assert result["job_id"]
    job = api_module._jobs.get_job(tenant, result["job_id"])
    assert job is not None
    assert _JD_TEXT in job["jd_text"]
    pending = api_module._jobs.list_blockers(tenant, status="pending")
    assert all(b["blocker_id"] != result["blocker_id"] for b in pending)
