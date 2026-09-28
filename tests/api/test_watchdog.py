"""Watchdog tests (ticket #102 / plan §3).

Sweeps are driven at the service seam with an injected clock and env cap —
no sleeps, no framework. The state-machine guard is asserted at its weakest
point: a hung worker's late terminal write must never overwrite the
watchdog's result.
"""

from __future__ import annotations

import logging
import threading

import pytest

import resualign.api as api_module
from resualign.api.services import watchdog
from resualign.jobs import JobRegistry
from resualign.workspace import JobLibraryStore

NOW = {"t": 1_000.0}


@pytest.fixture(autouse=True)
def temp_stores(tmp_path, monkeypatch):
    saved_registry = api_module._registry
    saved_jobs = api_module._jobs
    saved_payloads = api_module._payloads
    monkeypatch.setenv("RESUALIGN_JOB_MAX_RUNTIME_S", "10")
    NOW["t"] = 1_000.0
    api_module._registry = JobRegistry(
        db_path=tmp_path / "jobs.db", clock=lambda: NOW["t"]
    )
    api_module._jobs = JobLibraryStore(db_path=tmp_path / "lib.db")
    api_module._payloads = {}
    yield
    api_module._registry = saved_registry
    api_module._jobs = saved_jobs
    api_module._payloads = saved_payloads


def _running_job(payload=None, tenant="t1"):
    job = api_module._registry.create(payload or {"resume_text": "x"}, None, tenant_id=tenant)
    assert api_module._registry.claim_running(job.job_id)
    return job


class TestSweep:
    def test_stale_running_is_forced_failed(self):
        job = _running_job()
        NOW["t"] = 1_011.0
        forced = watchdog.scan_once(now=1_011.0)
        assert forced == [job.job_id]
        snap = api_module._registry.snapshot(job.job_id)
        assert snap["status"] == "failed"
        assert "超时" in snap["error"]

    def test_fresh_running_untouched(self):
        job = _running_job()
        assert watchdog.scan_once(now=1_005.0) == []
        assert api_module._registry.snapshot(job.job_id)["status"] == "running"

    def test_queued_and_terminal_rows_never_touched(self):
        q = api_module._registry.create({"x": 1}, None, tenant_id="t1")
        done = _running_job()
        NOW["t"] = 1_011.0
        api_module._registry.succeed(done.job_id, {"ok": True})
        assert watchdog.scan_once(now=1_011.0) == []
        assert api_module._registry.snapshot(q.job_id)["status"] == "queued"

    def test_disabled_cap(self, monkeypatch):
        monkeypatch.setenv("RESUALIGN_JOB_MAX_RUNTIME_S", "0")
        job = _running_job()
        assert watchdog.scan_once(now=99_999.0) == []
        assert api_module._registry.snapshot(job.job_id)["status"] == "running"

    def test_invalid_cap_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("RESUALIGN_JOB_MAX_RUNTIME_S", "banana")
        assert watchdog.max_runtime_seconds() == watchdog.DEFAULT_MAX_RUNTIME_S
        job = _running_job()
        assert watchdog.scan_once(now=1_500.0) == []  # < 1800s default
        assert watchdog.scan_once(now=3_000.0) == [job.job_id]


class TestNoDoubleTerminal:
    def test_hung_worker_late_write_cannot_overwrite(self):
        job = _running_job()
        NOW["t"] = 1_011.0
        assert watchdog.scan_once(now=1_011.0) == [job.job_id]
        # The "hung thread" finally wakes and completes: its succeed must be
        # rejected by the same conditional UPDATE that guards all races.
        api_module._registry.succeed(job.job_id, {"late": True})
        snap = api_module._registry.snapshot(job.job_id)
        assert snap["status"] == "failed"
        assert "超时" in snap["error"]


class TestLibraryMirror:
    def test_alignment_badge_and_error_synced(self):
        lib = api_module._jobs.create_job(
            tenant_id="t1", title="Backend", jd_text="Python."
        )
        _running_job(payload={"library_job_id": lib["job_id"]})
        NOW["t"] = 1_011.0
        assert watchdog.scan_once(now=1_011.0)
        refreshed = api_module._jobs.get_job("t1", lib["job_id"])
        assert refreshed["alignment_status"] == "failed"
        assert "超时" in (refreshed["last_alignment_error"] or "")

    def test_watchdog_event_logged(self, caplog):
        job = _running_job()
        NOW["t"] = 1_011.0
        with caplog.at_level(logging.WARNING, logger="resualign.api.watchdog"):
            watchdog.scan_once(now=1_011.0)
        msgs = [
            rec.getMessage()
            for rec in caplog.records
            if '"job.watchdog_timeout"' in rec.getMessage()
        ]
        assert msgs and job.job_id in msgs[0] and '"cap_s": 10' in msgs[0]


class TestLifecycle:
    def test_start_returns_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("RESUALIGN_JOB_MAX_RUNTIME_S", "0")
        assert watchdog.start() is None

    def test_start_thread_stops_promptly(self, monkeypatch):
        monkeypatch.setenv("RESUALIGN_JOB_MAX_RUNTIME_S", "10")
        stop = watchdog.start()
        assert stop is not None
        threads = [t for t in threading.enumerate() if t.name == "resualign-watchdog"]
        assert threads
        stop.set()
        threads[0].join(5)
        assert not threads[0].is_alive()
