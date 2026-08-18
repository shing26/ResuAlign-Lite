"""Tests for the Sprint 6 agent-native backend (MCP server, HITL, headless).

The MCP tools are the plain functions registered with FastMCP (the
``@mcp.tool()`` decorator returns the original callable), so every test
calls them directly without booting an MCP transport. Store singletons are
swapped onto ``resualign.api`` following the ``test_api`` fixture pattern
(tmp isolation + package-attribute replacement).
"""

import asyncio
import time
from unittest.mock import patch

import httpx
import pytest

import resualign.api as api_module
from resualign.agent import hitl as hitl_module
from resualign.agent.headless import run_headless, run_headless_round
from resualign.agent.mcp_server import (
    auto_align_resume,
    fetch_and_evaluate_job,
    get_mcp_app,
    get_pending_blockers,
    job_ingest_and_profile,
    job_tracker_manage,
    master_resume_query,
    resolve_blocker,
    resume_align_and_tailor,
)
from resualign.crawler import CrawlError
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.models import ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import MasterResumeStore, UserStore


@pytest.fixture(autouse=True)
def temp_agent_stores(tmp_path):
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
    db_path = tmp_path / "agent.db"
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


def _test_config(api_key="sk-test"):
    return ResuAlignConfig(
        provider="deepseek", api_key=api_key, model="test-model"
    )


def _crawl_ok(text="负责后端服务开发。月薪 25-35K，双休。"):
    def _fetch(url, meta=None, **kwargs):
        if meta is not None:
            meta["title"] = "后端开发工程师"
            meta["company"] = "Acme"
            meta["city"] = "上海"
        return text

    return _fetch


def _crawl_error(category, message):
    def _fetch(url, meta=None, **kwargs):
        raise CrawlError(message, category=category, url=url)

    return _fetch


def _make_library_job(
    tenant="local",
    title="后端开发工程师",
    text="负责后端服务开发。月薪 25-35K。",
):
    return api_module._jobs.create_job(
        tenant_id=tenant,
        title=title,
        jd_text=text,
        source_type="paste",
    )


def _make_master_resume(
    tenant="local",
    title="主简历",
    content="Python 后端开发。Java 经验。",
):
    return api_module._resumes.create_master_resume(tenant, title, content)


# -- MCP server plumbing -----------------------------------------------------


def test_get_mcp_app_registers_eight_tools():
    app = get_mcp_app()
    tools = asyncio.run(app.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "fetch_and_evaluate_job",
        "auto_align_resume",
        "get_pending_blockers",
        "resolve_blocker",
        "job_ingest_and_profile",
        "resume_align_and_tailor",
        "job_tracker_manage",
        "master_resume_query",
    } <= names


# -- fetch_and_evaluate_job --------------------------------------------------


def test_fetch_and_evaluate_creates_job():
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()):
        result = fetch_and_evaluate_job(
            url="https://example.com/jobs/1", tenant_id="local"
        )
    assert result["status"] == "created"
    assert result["job_id"]
    job = api_module._jobs.get_job("local", result["job_id"])
    assert job is not None
    assert job["source_type"] == "url"
    assert api_module._jobs.list_blockers("local") == []


def test_fetch_and_evaluate_duplicate():
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()):
        first = fetch_and_evaluate_job(
            url="https://example.com/jobs/1", tenant_id="local"
        )
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()):
        second = fetch_and_evaluate_job(
            url="https://example.com/jobs/1/", tenant_id="local"
        )
    assert first["status"] == "created"
    assert second["status"] == "duplicate"
    assert second["job_id"] == first["job_id"]
    assert api_module._jobs.list_blockers("local") == []


def test_fetch_and_evaluate_blocked_on_crawl_error():
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=_crawl_error("http", "Failed to fetch: HTTP 403"),
    ):
        result = fetch_and_evaluate_job(
            url="https://example.com/jobs/1", tenant_id="local"
        )
    assert result["status"] == "blocked"
    assert result["category"] == "login_required"
    assert result["blocker_id"]
    blocker = api_module._jobs.get_blocker("local", result["blocker_id"])
    assert blocker is not None
    assert blocker["status"] == "pending"


def test_fetch_and_evaluate_blocked_on_invalid_url():
    result = fetch_and_evaluate_job(
        url="ftp://example.com/jobs/1", tenant_id="local"
    )
    assert result["status"] == "blocked"
    assert result["category"] == "invalid_url"
    assert result["blocker_id"]


# -- auto_align_resume -------------------------------------------------------


def test_auto_align_queues_job_and_registry_has_it():
    job = _make_library_job()
    resume = _make_master_resume()
    with patch.object(
        api_module, "build_config", return_value=_test_config()
    ), patch.object(api_module, "_run_job"):
        result = auto_align_resume(
            job_id=job["job_id"],
            master_resume_id=resume["resume_id"],
            tenant_id="local",
        )
    assert result["status"] == "queued"
    analysis_job_id = result["analysis_job_id"]
    registry_job = api_module._registry.get(analysis_job_id)
    assert registry_job is not None
    assert registry_job.status == "queued"
    payload = api_module._payloads[analysis_job_id][0]
    assert payload["library_job_id"] == job["job_id"]
    assert payload["master_resume_id"] == resume["resume_id"]
    assert payload["granularity"] == "medium"
    updated = api_module._jobs.get_job("local", job["job_id"])
    assert updated["workbench_job_id"] == analysis_job_id
    assert updated["workbench_resume_id"] == resume["resume_id"]


def test_auto_align_uses_first_master_resume_when_unspecified():
    job = _make_library_job()
    first = _make_master_resume(title="第一份")
    time.sleep(0.01)
    second = _make_master_resume(title="第二份")
    with patch.object(
        api_module, "build_config", return_value=_test_config()
    ), patch.object(api_module, "_run_job"):
        result = auto_align_resume(job_id=job["job_id"], tenant_id="local")
    assert result["status"] == "queued"
    payload = api_module._payloads[result["analysis_job_id"]][0]
    # list_master_resumes orders by updated_at DESC, so the default pick is
    # the most recently updated resume.
    assert payload["master_resume_id"] == second["resume_id"]
    assert payload["master_resume_id"] != first["resume_id"]


def test_auto_align_missing_job_returns_error():
    result = auto_align_resume(job_id="does-not-exist", tenant_id="local")
    assert result["status"] == "error"
    assert "job not found" in result["error"]


def test_auto_align_without_master_resume_returns_error():
    job = _make_library_job()
    result = auto_align_resume(job_id=job["job_id"], tenant_id="local")
    assert result["status"] == "error"
    assert "resume" in result["error"]


def test_auto_align_emits_low_confidence_event():
    job = _make_library_job()
    _make_master_resume()
    api_module._jobs.update_job(
        "local", job["job_id"], diffs=[{"confidence": "low", "reason": "x"}]
    )
    with patch.object(
        api_module, "build_config", return_value=_test_config()
    ), patch.object(api_module, "_run_job"), patch.object(
        hitl_module, "emit_hitl_event"
    ) as mock_emit:
        result = auto_align_resume(job_id=job["job_id"], tenant_id="local")
    assert result["status"] == "queued"
    mock_emit.assert_called_once()
    event, payload = mock_emit.call_args.args
    assert event == "alignment.low_confidence"
    assert payload["job_id"] == job["job_id"]
    assert payload["diff_index"] == 0
    assert payload["confidence"] == "low"


# -- get_pending_blockers ----------------------------------------------------


def test_get_pending_blockers_empty():
    assert get_pending_blockers(tenant_id="local") == []


def test_get_pending_blockers_lists_only_pending():
    pending = api_module._jobs.create_blocker(
        "local",
        url="https://example.com/jobs/1",
        title="后端开发工程师",
        reason="boom",
        category="timeout",
    )
    resolved = api_module._jobs.create_blocker(
        "local", url="https://example.com/jobs/2", reason="boom",
        category="timeout",
    )
    api_module._jobs.resolve_blocker(
        "local", resolved["blocker_id"], job_id="some-job"
    )
    items = get_pending_blockers(tenant_id="local")
    assert len(items) == 1
    assert items[0]["blocker_id"] == pending["blocker_id"]
    assert items[0]["url"] == "https://example.com/jobs/1"
    assert items[0]["title"] == "后端开发工程师"
    assert items[0]["category"] == "timeout"
    assert items[0]["reason"] == "boom"
    assert items[0]["created_at"]


# -- resolve_blocker ---------------------------------------------------------


def test_resolve_blocker_success():
    blocker = api_module._jobs.create_blocker(
        "local",
        url="https://example.com/jobs/1",
        reason="login needed",
        category="login_required",
    )
    result = resolve_blocker(
        blocker_id=blocker["blocker_id"],
        text="负责后端服务开发。月薪 25-35K。",
        tenant_id="local",
    )
    assert result["status"] == "resolved"
    assert result["job_id"]
    updated = api_module._jobs.get_blocker("local", blocker["blocker_id"])
    assert updated["status"] == "resolved"
    assert updated["job_id"] == result["job_id"]
    job = api_module._jobs.get_job("local", result["job_id"])
    assert job is not None
    assert job["source_type"] == "paste"


def test_resolve_blocker_missing_returns_error():
    result = resolve_blocker(
        blocker_id="missing", text="text", tenant_id="local"
    )
    assert result["status"] == "error"
    assert "not found" in result["error"]


def test_resolve_blocker_not_pending_returns_error():
    blocker = api_module._jobs.create_blocker(
        "local", url="https://x", reason="r", category="timeout"
    )
    api_module._jobs.resolve_blocker(
        "local", blocker["blocker_id"], job_id="j1"
    )
    result = resolve_blocker(
        blocker_id=blocker["blocker_id"], text="text", tenant_id="local"
    )
    assert result["status"] == "error"
    assert "pending" in result["error"]


# -- compound MCP tools (compound-ai-system-spec-final.md §四) ---------------


def test_job_ingest_and_profile_creates_text_job_with_snapshot():
    result = job_ingest_and_profile(
        source="负责后端服务开发，要求 Python 与高并发经验，月薪 25-35K。",
        source_type="text",
        tenant_id="local",
    )
    assert result["status"] == "created"
    assert result["job_id"]
    job = api_module._jobs.get_job("local", result["job_id"])
    assert job is not None
    assert job["source_type"] == "text"
    assert "jd_profile" in result
    assert "hard_gates" in result
    assert "classification" in result


def test_job_ingest_and_profile_url_returns_status_and_snapshot():
    with patch.object(
        api_module._fetcher,
        "submit_url",
        return_value={"status": "created", "job_id": "job-1"},
    ):
        result = job_ingest_and_profile(
            source="https://example.com/jobs/1",
            source_type="url",
            tenant_id="local",
        )
    assert result["status"] == "created"
    assert result["job_id"] == "job-1"
    assert result["jd_profile"] == {}


def test_job_ingest_and_profile_validates_source_type():
    result = job_ingest_and_profile(
        source="ops", source_type="ftp", tenant_id="local"
    )
    assert result["status"] == "error"
    assert "source_type" in result["error"]


def test_resume_align_and_tailor_queues_with_style():
    job = _make_library_job()
    resume = _make_master_resume()
    with patch.object(
        api_module, "build_config", return_value=_test_config()
    ), patch.object(api_module, "_run_job"):
        result = resume_align_and_tailor(
            job_id=job["job_id"],
            resume_id=resume["resume_id"],
            style="deep",
            tenant_id="local",
        )
    assert result["status"] == "queued"
    assert result["style"] == "deep"
    assert result["analysis_job_id"]


def test_job_tracker_manage_apply_creates_auto_followup():
    job = _make_library_job()
    result = job_tracker_manage(
        job_id=job["job_id"],
        action="apply",
        tenant_id="local",
    )
    assert result["status"] == "updated"
    assert result["action"] == "apply"
    updated = api_module._jobs.get_job("local", job["job_id"])
    assert updated["status"] == "applied"
    assert updated["next_step"] == "投递后跟进"
    assert updated["next_step_due_at"]


def test_job_tracker_manage_updates_stage_and_note():
    job = _make_library_job()
    stage_result = job_tracker_manage(
        job_id=job["job_id"],
        action="update_stage",
        stage="一面",
        tenant_id="local",
    )
    assert stage_result["status"] == "updated"
    updated = api_module._jobs.get_job("local", job["job_id"])
    assert updated["interview_stage"] == "一面"
    note_result = job_tracker_manage(
        job_id=job["job_id"],
        action="log_note",
        note="已与 HR 确认时间",
        tenant_id="local",
    )
    assert note_result["status"] == "updated"
    updated = api_module._jobs.get_job("local", job["job_id"])
    assert "已与 HR 确认时间" in updated["notes"]


def test_job_tracker_manage_rejects_unknown_action():
    job = _make_library_job()
    result = job_tracker_manage(
        job_id=job["job_id"], action="rename", tenant_id="local"
    )
    assert result["status"] == "error"
    assert "action must be" in result["error"]


def test_master_resume_query_returns_scored_fragments():
    resume = _make_master_resume(
        content="项目 A：负责 Redis 高并发缓存层。\n"
        "项目 B：负责 Java 微服务接口。\n"
        "项目 C：负责 Python 数据分析。"
    )
    items = master_resume_query(
        resume_id=resume["resume_id"],
        query="Redis 高并发",
        top_k=2,
        tenant_id="local",
    )
    assert len(items) == 1
    assert items[0]["provenance"]["resume_id"] == resume["resume_id"]
    assert "Redis" in items[0]["fragment"]
    assert items[0]["line_number"] == 1


# -- HITL events -------------------------------------------------------------


def test_emit_hitl_event_posts_when_configured():
    with patch.object(
        hitl_module, "_get_webhook_url",
        return_value="https://hooks.example.com/hitl",
    ), patch("httpx.post") as mock_post:
        hitl_module.emit_hitl_event(
            "blocker.created",
            {
                "blocker_id": "b1",
                "url": "https://x",
                "reason": "r",
                "category": "invalid_url",
            },
        )
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://hooks.example.com/hitl"
    assert kwargs["json"] == {
        "event": "blocker.created",
        "payload": {
            "blocker_id": "b1",
            "url": "https://x",
            "reason": "r",
            "category": "invalid_url",
        },
    }
    assert kwargs["timeout"] == 5.0


def test_emit_hitl_event_logs_when_not_configured():
    with patch.object(hitl_module, "_get_webhook_url", return_value=""), patch.object(
        hitl_module, "log_event"
    ) as mock_log:
        hitl_module.emit_hitl_event("blocker.created", {"blocker_id": "b1"})
    mock_log.assert_called_once()
    assert mock_log.call_args.args[1] == "blocker.created"


def test_emit_hitl_event_swallows_webhook_failure():
    with patch.object(
        hitl_module, "_get_webhook_url",
        return_value="https://hooks.example.com/hitl",
    ), patch(
        "httpx.post", side_effect=httpx.ConnectError("boom")
    ):
        hitl_module.emit_hitl_event(
            "alignment.low_confidence", {"job_id": "j1"}
        )
    # No exception propagates.


def test_fetcher_blocker_creation_emits_hitl_event():
    with patch(
        "resualign.api.services.fetcher.emit_hitl_event"
    ) as mock_emit:
        result = fetch_and_evaluate_job(
            url="ftp://example.com/jobs/1", tenant_id="local"
        )
    assert result["status"] == "blocked"
    mock_emit.assert_called_once()
    event, payload = mock_emit.call_args.args
    assert event == "blocker.created"
    assert payload["blocker_id"] == result["blocker_id"]
    assert payload["category"] == "invalid_url"
    assert payload["url"] == "ftp://example.com/jobs/1"


# -- Headless daemon ---------------------------------------------------------


def test_run_headless_round_empty_store():
    stats = run_headless_round("local")
    assert stats["blockers_seen"] == 0
    assert stats["align_candidates"] == 0
    assert stats["align_queued"] == 0


def test_run_headless_round_classifies_blockers_and_skips_without_resume():
    api_module._jobs.create_blocker(
        "local", url="https://example.com/x", reason="timeout",
        category="timeout",
    )
    _make_library_job()
    stats = run_headless_round("local")
    assert stats["blockers_seen"] == 1
    assert stats["align_candidates"] == 1
    # No master resume -> the candidate is skipped, never crashes.
    assert stats["align_queued"] == 0


def test_run_headless_round_queues_alignment():
    _make_library_job()
    _make_master_resume()
    with patch.object(
        api_module, "build_config", return_value=_test_config()
    ), patch.object(api_module, "_run_job"):
        stats = run_headless_round("local")
    assert stats["align_candidates"] == 1
    assert stats["align_queued"] == 1


def test_run_headless_single_round_does_not_crash():
    run_headless(
        interval=0,
        tenant_id="local",
        start_server=False,
        max_rounds=1,
    )


# -- CLI --headless / --agent-mode ------------------------------------------


def test_cli_parse_headless_and_agent_mode():
    from resualign.cli import _parse_args

    headless = _parse_args(["--headless"])
    assert headless.headless is True
    assert headless.agent_mode is False
    assert headless.interval == 30.0

    agent_mode = _parse_args(["--agent-mode", "--interval", "5"])
    assert agent_mode.agent_mode is True
    assert agent_mode.headless is False
    assert agent_mode.interval == 5.0


def test_cli_headless_and_agent_mode_are_mutually_exclusive():
    from resualign.cli import _parse_args

    with pytest.raises(SystemExit):
        _parse_args(["--headless", "--agent-mode"])


def test_cli_main_headless_starts_daemon():
    from resualign.cli import main

    with patch("resualign.agent.headless.run_headless") as mock_run:
        main(["--headless"])
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["interval"] == 30.0


def test_cli_main_agent_mode_starts_daemon():
    from resualign.cli import main

    with patch("resualign.agent.headless.run_headless") as mock_run:
        main(["--agent-mode"])
    mock_run.assert_called_once()
