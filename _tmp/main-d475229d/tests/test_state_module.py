"""A1: api/state.py owns process state; the package re-exports it."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import resualign.api as api_module
from resualign.api import state
from resualign.batch import BatchAlignStore
from resualign.cache import ContentCache
from resualign.job_library import CrawlTaskStore, JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import ApplicationStore, MasterResumeStore, UserStore

REPO_ROOT = Path(__file__).resolve().parents[1]

STATE_NAMES = (
    "_registry",
    "_users",
    "_resumes",
    "_applications",
    "_jobs",
    "_crawl_tasks",
    "_settings_store",
    "_cache",
    "_cache_db",
    "_session_store",
    "_batch_store",
    "_auth_rate_limiter",
    "_analyze_rate_limiter",
    "_import_rate_limiter",
    "_WORKER_SEMAPHORE",
    "_MAX_IMPORT_ROWS",
    "_MAX_RESUME_UPLOAD_BYTES",
    "_MAX_BODY_BYTES",
    "_TIMELINE_FIELDS",
    "_import_batches",
    "_payloads",
    "_PERSONAL_MODE",
    "_env_settings",
)


def test_state_module_exposes_all_state_names():
    for name in STATE_NAMES:
        assert hasattr(state, name), name


def test_api_exposes_all_state_names():
    for name in STATE_NAMES:
        assert hasattr(api_module, name), name


def test_api_re_exports_state_singletons_in_fresh_interpreter():
    """At import time api_module attributes ARE the state singletons.

    Runs in a fresh interpreter because later tests swap package attributes
    (e.g. test_api.py keeps a replaced registry on purpose).
    """
    checks = "\n".join(
        f"assert api_module.{name} is state.{name}, {name!r}"
        for name in (
            "_registry",
            "_users",
            "_resumes",
            "_applications",
            "_jobs",
            "_settings_store",
            "_cache",
            "_session_store",
            "_batch_store",
        )
    )
    code = (
        "import resualign.api as api_module\n"
        "from resualign.api import state\n"
        f"{checks}\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=dict(os.environ, PYTHONPATH=str(REPO_ROOT / "src")),
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_state_singleton_types():
    assert isinstance(state._registry, JobRegistry)
    assert isinstance(state._users, UserStore)
    assert isinstance(state._resumes, MasterResumeStore)
    assert isinstance(state._applications, ApplicationStore)
    assert isinstance(state._jobs, JobLibraryStore)
    assert isinstance(state._crawl_tasks, CrawlTaskStore)
    assert isinstance(state._settings_store, SettingsStore)
    assert isinstance(state._cache, ContentCache)
    assert isinstance(state._batch_store, BatchAlignStore)


def test_swapping_package_attribute_leaves_state_untouched(tmp_path):
    """Tests replace api_module._registry; state keeps its own instance and
    routers (which resolve api_module._registry at call time) see the swap."""
    old = api_module._registry
    replacement = JobRegistry(db_path=tmp_path / "swap.db")
    try:
        api_module._registry = replacement
        assert api_module._registry is replacement
        assert state._registry is not replacement
    finally:
        api_module._registry = old


def test_recovery_helpers_remain_on_package():
    assert callable(api_module._recover_pending_jobs)
    assert callable(api_module._recover_stale_alignments)
    assert callable(api_module._run_job)
