"""Sprint 6 MCP tools integration (agent-facing job pipeline).

Exercises the four FastMCP-registered tools against isolated real stores and
the *real* API worker path:

* ``fetch_and_evaluate_job``  URL pipeline state machine (crawl mocked)
* ``auto_align_resume``       queue a workbench alignment (engine.run mocked)
* ``get_pending_blockers``    pending blocker queue
* ``resolve_blocker``         pasted-JD blocker resolution

The full-chain test (fetch -> align -> poll succeeded -> diffs on the library
job) is the Sprint 6 money path: it proves the MCP surface wires into the same
stores, worker threads, and persistence the web API uses.

``resualign.agent.mcp_server`` imports FastMCP, which is not yet a declared
project dependency (coordination point with the backend agent: add ``mcp`` +
``fastmcp`` to pyproject). Every mcp_server import is therefore lazy and skips
with a "待 A" note until the module is available in the current environment.
"""

from __future__ import annotations

import importlib
import time

import pytest

import resualign.api as api_module
from resualign.crawler import CrawlError
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    GapReport,
    JDProfile,
    Report,
    ResuAlignConfig,
)
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

MCP_TOOL_NAMES = (
    "fetch_and_evaluate_job",
    "auto_align_resume",
    "get_pending_blockers",
    "resolve_blocker",
)

_JD_TEXT = "负责后端服务开发。要求 Java 与高并发经验。月薪 25-35K，双休。"
_MANUAL_TEXT = "负责后端开发。要求 Python。月薪 20-30K。"


def _agent_module(name: str):
    """Import a resualign.agent submodule, skipping loudly when it is absent."""
    try:
        return importlib.import_module(f"resualign.agent.{name}")
    except ImportError as exc:
        pytest.skip(f"待 A: resualign.agent.{name} 尚未可用 ({exc})")


def _config() -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek", api_key="sk-test", model="test-model"
    )


def _classify(jd_text, job_functions=None, seniorities=None, **kwargs):
    return {
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Python"],
    }


def _crawl_ok(url, meta=None, **kwargs):
    if meta is not None:
        meta["title"] = "后端开发工程师"
        meta["company"] = "Acme"
        meta["city"] = "上海"
    return _JD_TEXT


def _crawl_boom(url, meta=None, **kwargs):
    raise CrawlError("Failed to fetch https://x: HTTP 403", category="http")


def _report_with_diffs() -> Report:
    return Report(
        score=82,
        skills=["Python"],
        diffs=[
            DiffItem(
                type="modify",
                original="Python dev",
                proposed="Java backend services",
                reason="match JD keywords",
                confidence="high",
            )
        ],
        jd_profile=JDProfile(
            must_have_skills=["Java"], business_scenarios=["高并发"]
        ),
        gap_report=GapReport(missing_keywords=["Redis"]),
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    """Swap every store singleton onto one tmp db (test_api fixture pattern)."""
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
    }
    db_path = tmp_path / "agent-integration.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    yield
    for key, value in saved.items():
        setattr(api_module, key, value)
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()


def _poll_job_status(api_module, job_id: str, deadline: float = 20.0) -> str:
    """Wait for a terminal registry job state without any fixed sleep."""
    snapshot = None
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        snapshot = api_module._registry.snapshot(job_id)
        if snapshot is not None and snapshot["status"] in (
            "succeeded",
            "failed",
            "canceled",
        ):
            return snapshot["status"]
        time.sleep(0.05)
    return (snapshot or {}).get("status", "missing")


def _registered_tool_names() -> set[str]:
    """Return tool names FastMCP knows about, with a plain-function fallback."""
    mcp_server = _agent_module("mcp_server")
    names: set[str] = set()
    manager = getattr(mcp_server.get_mcp_app(), "_tool_manager", None)
    if manager is not None:
        try:
            names = {tool.name for tool in manager.list_tools()}
        except Exception:  # pragma: no cover - FastMCP version drift
            names = set()
    if not names:
        names = {
            name
            for name in MCP_TOOL_NAMES
            if callable(getattr(mcp_server, name, None))
        }
    return names


# -- FastMCP registration ----------------------------------------------------


def test_mcp_app_exposes_four_tools():
    names = _registered_tool_names()
    assert set(MCP_TOOL_NAMES) <= names, f"missing tools: {set(MCP_TOOL_NAMES) - names}"


# -- Full chain: fetch -> auto_align -> poll -> diffs ------------------------


def test_fetch_evaluate_then_auto_align_full_chain(monkeypatch):
    tenant = "agent-fullchain"
    mcp_server = _agent_module("mcp_server")

    monkeypatch.setattr(api_module, "crawl_jd", _crawl_ok)
    monkeypatch.setattr(api_module, "_classify_job", _classify)

    fetched = mcp_server.fetch_and_evaluate_job(
        url="https://example.com/jobs/1", tenant_id=tenant
    )
    assert fetched["status"] == "created", fetched
    job_id = fetched["job_id"]
    job = api_module._jobs.get_job(tenant, job_id)
    assert job is not None
    assert job["source_url"] == "https://example.com/jobs/1"

    resume = api_module._resumes.create_master_resume(
        tenant, "主简历", "Python 开发，负责后端服务。"
    )
    assert resume["resume_id"]

    monkeypatch.setattr(api_module, "build_config", lambda: _config())
    monkeypatch.setattr(api_module, "run", lambda *a, **kw: _report_with_diffs())

    queued = mcp_server.auto_align_resume(
        job_id=job_id, master_resume_id=resume["resume_id"], tenant_id=tenant
    )
    assert queued["status"] == "queued", queued
    analysis_job_id = queued["analysis_job_id"]

    assert _poll_job_status(api_module, analysis_job_id) == "succeeded"

    aligned = api_module._jobs.get_job(tenant, job_id)
    assert aligned["alignment_status"] == "succeeded"
    assert aligned["workbench_job_id"] == analysis_job_id
    assert aligned["workbench_resume_id"] == resume["resume_id"]
    diffs = aligned.get("diffs") or []
    assert len(diffs) == 1
    assert diffs[0]["proposed"] == "Java backend services"


def test_auto_align_resume_defaults_to_first_master_resume(monkeypatch):
    tenant = "agent-default-resume"
    mcp_server = _agent_module("mcp_server")

    monkeypatch.setattr(api_module, "crawl_jd", _crawl_ok)
    monkeypatch.setattr(api_module, "_classify_job", _classify)
    fetched = mcp_server.fetch_and_evaluate_job(
        url="https://example.com/jobs/2", tenant_id=tenant
    )
    job_id = fetched["job_id"]

    api_module._resumes.create_master_resume(tenant, "主简历", "Python 后端。")
    monkeypatch.setattr(api_module, "build_config", lambda: _config())
    monkeypatch.setattr(api_module, "run", lambda *a, **kw: _report_with_diffs())

    queued = mcp_server.auto_align_resume(job_id=job_id, tenant_id=tenant)
    assert queued["status"] == "queued", queued
    assert _poll_job_status(api_module, queued["analysis_job_id"]) == "succeeded"


def test_auto_align_resume_errors_on_missing_job():
    mcp_server = _agent_module("mcp_server")
    result = mcp_server.auto_align_resume(job_id="missing", tenant_id="x")
    assert result["status"] == "error"
    assert "job not found" in result["error"]


def test_auto_align_resume_errors_without_api_key(monkeypatch):
    tenant = "agent-no-key"
    mcp_server = _agent_module("mcp_server")
    monkeypatch.setattr(api_module, "crawl_jd", _crawl_ok)
    monkeypatch.setattr(api_module, "_classify_job", _classify)
    job_id = mcp_server.fetch_and_evaluate_job(
        url="https://example.com/jobs/3", tenant_id=tenant
    )["job_id"]
    api_module._resumes.create_master_resume(tenant, "主简历", "Python 后端。")

    monkeypatch.setattr(
        api_module, "build_config", lambda: ResuAlignConfig(api_key="")
    )
    result = mcp_server.auto_align_resume(job_id=job_id, tenant_id=tenant)
    assert result["status"] == "error"
    assert "LLM" in result["error"]


# -- Blockers -----------------------------------------------------------------


def test_get_pending_blockers_lists_crawl_blockers(monkeypatch):
    tenant = "agent-blocked"
    mcp_server = _agent_module("mcp_server")
    monkeypatch.setattr(api_module, "crawl_jd", _crawl_boom)

    blocked = mcp_server.fetch_and_evaluate_job(
        url="https://example.com/jobs/1", tenant_id=tenant
    )
    assert blocked["status"] == "blocked"
    assert blocked["blocker_id"]

    pending = mcp_server.get_pending_blockers(tenant_id=tenant)
    assert [b["blocker_id"] for b in pending] == [blocked["blocker_id"]]
    assert pending[0]["url"] == "https://example.com/jobs/1"
    assert pending[0]["category"]


def test_get_pending_blockers_invalid_url_and_tenant_isolation():
    mcp_server = _agent_module("mcp_server")
    blocked = mcp_server.fetch_and_evaluate_job(
        url="not-a-url", tenant_id="agent-a"
    )
    assert blocked["status"] == "blocked"
    assert blocked["category"] == "invalid_url"

    # Another tenant must not see the blocker.
    assert mcp_server.get_pending_blockers(tenant_id="agent-b") == []


def test_fetch_duplicate_detected_without_second_crawl(monkeypatch):
    tenant = "agent-dup"
    mcp_server = _agent_module("mcp_server")
    calls: list[str] = []

    def _crawl_counted(url, meta=None, **kwargs):
        calls.append(url)
        return _JD_TEXT

    monkeypatch.setattr(api_module, "crawl_jd", _crawl_counted)
    monkeypatch.setattr(api_module, "_classify_job", _classify)

    first = mcp_server.fetch_and_evaluate_job(
        url="https://example.com/jobs/1", tenant_id=tenant
    )
    second = mcp_server.fetch_and_evaluate_job(
        url="https://example.com/jobs/1/", tenant_id=tenant
    )
    assert first["status"] == "created"
    assert second["status"] == "duplicate"
    assert second["job_id"] == first["job_id"]
    assert len(calls) == 1


def test_resolve_blocker_creates_job_and_leaves_pending_queue(monkeypatch):
    tenant = "agent-resolve"
    mcp_server = _agent_module("mcp_server")
    monkeypatch.setattr(api_module, "_classify_job", _classify)

    blocked = mcp_server.fetch_and_evaluate_job(
        url="not-a-url", tenant_id=tenant
    )
    assert blocked["status"] == "blocked"
    blocker_id = blocked["blocker_id"]

    resolved = mcp_server.resolve_blocker(
        blocker_id=blocker_id, text=_MANUAL_TEXT, tenant_id=tenant
    )
    assert resolved["status"] == "resolved", resolved
    assert resolved["job_id"]

    blocker = api_module._jobs.get_blocker(tenant, blocker_id)
    assert blocker["status"] == "resolved"
    assert blocker["manual_text"] == _MANUAL_TEXT
    pending = mcp_server.get_pending_blockers(tenant_id=tenant)
    assert all(b["blocker_id"] != blocker_id for b in pending)


def test_resolve_blocker_reports_error_for_missing_blocker():
    mcp_server = _agent_module("mcp_server")
    result = mcp_server.resolve_blocker(
        blocker_id="missing", text=_MANUAL_TEXT, tenant_id="agent-x"
    )
    assert result["status"] == "error"
    assert "not found" in result["error"]
