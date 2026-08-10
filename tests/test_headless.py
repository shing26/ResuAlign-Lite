"""Sprint 6 headless daemon tests (cli --headless / --agent-mode + run_headless).

The backend agent landed ``resualign/agent/headless.py`` and the CLI flags;
these tests exercise the real contract:

* CLI: ``--headless`` / ``--agent-mode`` parse, are mutually exclusive, and
  dispatch ``main`` into ``run_headless(interval=...)`` without a resume.
* ``run_headless_round``: one daemon poll — classify pending blockers
  (keep them pending, never auto-resolve) and auto-queue alignment for
  non-terminal library jobs (``idle``/``failed``) via ``auto_align_resume``.
* ``run_headless(once=True, start_server=False)``: bounded single round that
  never binds a port (unit tests must not touch uvicorn).

Stores are isolated on tmp db files exactly like the API test fixtures.
"""

from __future__ import annotations

import time

import pytest

import resualign.api as api_module
import resualign.cli as cli_module
from resualign.agent.headless import run_headless, run_headless_round
from resualign.jobs import JobRegistry
from resualign.models import DiffItem, Report, ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
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
    db_path = tmp_path / "headless.db"
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


def _config() -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek", api_key="sk-test", model="test-model"
    )


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
        model="test-model",
    )


def _poll_job_status(job_id: str, deadline: float = 20.0) -> str:
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


# -- CLI ----------------------------------------------------------------------


def test_cli_parser_accepts_headless_flag():
    args = cli_module._parse_args(["resume.pdf", "--headless"])
    assert args.headless is True
    assert args.agent_mode is False


def test_cli_parser_accepts_agent_mode_flag():
    args = cli_module._parse_args(["resume.pdf", "--agent-mode"])
    assert args.agent_mode is True
    assert args.headless is False


def test_cli_parser_headless_and_agent_mode_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli_module._parse_args(
            ["resume.pdf", "--headless", "--agent-mode"]
        )


def test_cli_parser_accepts_headless_without_resume_positional():
    args = cli_module._parse_args(["--headless"])
    assert args.headless is True
    assert args.resume is None


def test_cli_parser_interval_flag_defaults_and_overrides():
    assert cli_module._parse_args(["r.pdf", "--headless"]).interval == 30.0
    assert (
        cli_module._parse_args(["--agent-mode", "--interval", "5"]).interval
        == 5.0
    )


def test_cli_main_dispatches_headless_to_run_headless(monkeypatch):
    captured: dict = {}

    def fake_run_headless(interval):
        captured["interval"] = interval

    monkeypatch.setattr(
        "resualign.agent.headless.run_headless", fake_run_headless
    )
    cli_module.main(["--headless", "--interval", "0.5"])
    assert captured == {"interval": 0.5}


def test_cli_main_dispatch_agent_mode_alias(monkeypatch):
    calls: list[float] = []
    monkeypatch.setattr(
        "resualign.agent.headless.run_headless",
        lambda interval: calls.append(interval),
    )
    cli_module.main(["--agent-mode"])
    assert calls == [30.0]


def test_cli_main_requires_resume_without_headless(capsys):
    with pytest.raises(SystemExit) as exc_info:
        cli_module.main([])
    assert exc_info.value.code == 2
    assert "resume file is required" in capsys.readouterr().err


# -- run_headless_round -------------------------------------------------------


def test_round_with_no_blockers_and_no_candidates():
    stats = run_headless_round(tenant_id="daemon-empty")
    assert stats == {
        "blockers_seen": 0,
        "align_candidates": 0,
        "align_queued": 0,
    }


def test_round_sees_blocker_and_keeps_it_pending():
    tenant = "daemon-blocker"
    blocker = api_module._jobs.create_blocker(
        tenant,
        url="not-a-url",
        reason="链接格式无效",
        category="invalid_url",
    )
    stats = run_headless_round(tenant_id=tenant)
    assert stats["blockers_seen"] == 1
    assert stats["align_candidates"] == 0

    # The daemon never auto-resolves a blocker: it stays pending for a human.
    stored = api_module._jobs.get_blocker(tenant, blocker["blocker_id"])
    assert stored["status"] == "pending"


def test_round_auto_queues_idle_job_alignment(monkeypatch):
    tenant = "daemon-align"
    job = api_module._jobs.create_job(
        tenant_id=tenant,
        title="后端工程师",
        jd_text="负责后端服务开发。要求 Java 经验。",
        alignment_status="idle",
    )
    api_module._resumes.create_master_resume(
        tenant, "主简历", "Python 后端开发经验。"
    )

    monkeypatch.setattr(api_module, "build_config", lambda: _config())
    monkeypatch.setattr(api_module, "run", lambda *a, **kw: _report_with_diffs())

    stats = run_headless_round(tenant_id=tenant)
    assert stats["align_candidates"] == 1
    assert stats["align_queued"] == 1

    job = api_module._jobs.get_job(tenant, job["job_id"])
    assert job["workbench_job_id"]
    assert _poll_job_status(job["workbench_job_id"]) == "succeeded"
    aligned = api_module._jobs.get_job(tenant, job["job_id"])
    assert aligned["alignment_status"] == "succeeded"
    assert (aligned.get("diffs") or [])[0]["proposed"] == "Java backend services"


def test_round_skips_succeeded_jobs(monkeypatch):
    """Jobs whose alignment is already terminal are never re-queued."""
    tenant = "daemon-done"
    api_module._jobs.create_job(
        tenant_id=tenant,
        title="后端工程师",
        jd_text="负责后端服务开发。",
        alignment_status="succeeded",
        diffs=[{"type": "modify", "proposed": "keep"}],
    )
    api_module._resumes.create_master_resume(
        tenant, "主简历", "Python 后端开发经验。"
    )

    queued: list[str] = []
    monkeypatch.setattr(
        "resualign.agent.headless.auto_align_resume",
        lambda job_id, **kw: queued.append(job_id),
    )
    stats = run_headless_round(tenant_id=tenant)
    assert stats["align_candidates"] == 0
    assert queued == []


# -- run_headless (loop) ------------------------------------------------------


def test_run_headless_once_runs_single_round_without_server():
    stats = run_headless(
        interval=0, once=True, start_server=False, tenant_id="daemon-once"
    )
    assert stats == {
        "blockers_seen": 0,
        "align_candidates": 0,
        "align_queued": 0,
    }


def test_run_headless_max_rounds_bounds_the_loop():
    stats = run_headless(
        interval=0,
        max_rounds=1,
        start_server=False,
        tenant_id="daemon-bounded",
    )
    assert stats["align_candidates"] == 0


# -- daemon internals (deterministic policy branches) -------------------------


def test_handle_blocker_policies():
    """Blockers are never auto-resolved: skip/retryable/unknown all keep them
    pending and only differ in the logged disposition."""
    from resualign.agent.headless import _handle_blocker

    tenant = "daemon-policy"
    for category in (
        "rule_rejected",
        "login_required",
        "captcha",
        "invalid_url",
        "network_error",
        "timeout",
        "site_error",
        "fetch_error",
        "no_content",
    ):
        blocker = api_module._jobs.create_blocker(
            tenant,
            url=f"https://example.com/{category}",
            reason=f"reason {category}",
            category=category,
        )
        _handle_blocker(tenant, blocker)
        assert api_module._jobs.get_blocker(
            tenant, blocker["blocker_id"]
        )["status"] == "pending"


def test_alignment_candidates_exclude_in_flight_pinned_jobs():
    """A job pinned to a queued/succeeded registry job is not a candidate
    even when its alignment_status is still idle."""
    from resualign.agent.headless import _alignment_auto_candidates

    tenant = "daemon-pinned"
    job = api_module._jobs.create_job(
        tenant_id=tenant,
        title="后端工程师",
        jd_text="负责后端服务开发。",
        alignment_status="idle",
    )
    registry_job = api_module._registry.create(
        {"resume_text": "x"}, object(), tenant_id=tenant
    )
    api_module._jobs.update_job(
        tenant, job["job_id"], workbench_job_id=registry_job.job_id
    )

    # Pinned to a queued job: not a candidate.
    assert _alignment_auto_candidates(tenant) == []
    # Pinned to a succeeded job: still not a candidate.
    api_module._registry.succeed(registry_job.job_id, {"ok": True})
    assert _alignment_auto_candidates(tenant) == []
    # Pin cleared: candidate again.
    api_module._jobs.update_job(tenant, job["job_id"], workbench_job_id="")
    assert [j["job_id"] for j in _alignment_auto_candidates(tenant)] == [
        job["job_id"]
    ]


def test_alignment_candidates_include_idle_without_pin():
    from resualign.agent.headless import _alignment_auto_candidates

    tenant = "daemon-free"
    job = api_module._jobs.create_job(
        tenant_id=tenant,
        title="后端工程师",
        jd_text="负责后端服务开发。",
        alignment_status="idle",
    )
    candidates = _alignment_auto_candidates(tenant)
    assert [j["job_id"] for j in candidates] == [job["job_id"]]


def test_resolve_host_port_uses_env_overrides(monkeypatch):
    from resualign.agent.headless import _resolve_host_port

    monkeypatch.setenv("RESUALIGN_HOST", "0.0.0.0")
    monkeypatch.setenv("RESUALIGN_PORT", "9000")
    assert _resolve_host_port() == ("0.0.0.0", 9000)

    monkeypatch.delenv("RESUALIGN_HOST", raising=False)
    monkeypatch.setenv("RESUALIGN_PORT", "not-a-port")
    assert _resolve_host_port() == ("127.0.0.1", 8000)


def test_is_port_open_probes_free_and_bound_ports():
    import socket

    from resualign.agent.headless import _is_port_open

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        assert _is_port_open("127.0.0.1", port) is True
        assert _is_port_open("127.0.0.1", 0) is False
    finally:
        listener.close()
