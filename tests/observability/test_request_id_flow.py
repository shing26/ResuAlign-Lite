"""request_id propagation tests (ticket #101 / plan §2).

Proves the correlation chain at the highest seams only:
- the job row persists the middleware-bound request id (API-created jobs);
- response header == stored id == snapshot echo (three-way match);
- worker-thread job events carry the stored id (ContextVar restore);
- log_event auto-reads the ContextVar (explicit wins, unbound emits none);
- startup requeue mints a NEW id, replaces the column, marks recovered;
- the jobs-table migration adds request_id to legacy databases idempotently.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.jobs import JobRegistry
from resualign.observability import (
    current_request_id,
    log_event,
    reset_request_id,
    set_request_id,
)

client = TestClient(api_module.app)


@pytest.fixture(autouse=True)
def _pin_personal_mode():
    """Anonymous /api/* access must not depend on ambient test ordering.

    Other modules flip api_module._PERSONAL_MODE; pin it True (local tenant)
    for this file and restore whatever we found.
    """
    saved = api_module._PERSONAL_MODE
    api_module._PERSONAL_MODE = True
    try:
        yield
    finally:
        api_module._PERSONAL_MODE = saved


def _rid_messages(caplog, needle: str) -> list[str]:
    return [
        rec.getMessage()
        for rec in caplog.records
        if needle in rec.getMessage() and rec.getMessage().startswith("{")
    ]


class TestRegistryPersistence:
    def test_create_persists_bound_request_id(self, tmp_path):
        reg = JobRegistry(db_path=tmp_path / "jobs.db")
        token = set_request_id("aaaa1111bbbb")
        try:
            job = reg.create({"x": 1}, None, tenant_id="t1")
        finally:
            reset_request_id(token)
        assert job.request_id == "aaaa1111bbbb"
        assert reg.request_id_for(job.job_id) == "aaaa1111bbbb"
        assert reg.snapshot(job.job_id)["request_id"] == "aaaa1111bbbb"

    def test_create_without_request_context_stores_empty(self, tmp_path):
        reg = JobRegistry(db_path=tmp_path / "jobs.db")
        assert current_request_id() is None
        job = reg.create({"x": 1}, None)
        assert job.request_id == ""
        assert reg.request_id_for(job.job_id) is None


class TestApiThreeWayMatch:
    def test_header_db_snapshot_agree(self):
        rid = "feedfacecafe"
        r = client.post(
            "/api/analyze",
            json={"resume_text": "Python developer resume."},
            headers={"X-Request-Id": rid},
        )
        assert r.status_code == 202
        assert r.headers["X-Request-Id"] == rid
        job_id = r.json()["job_id"]
        snap = client.get(f"/api/jobs/{job_id}").json()
        assert snap["request_id"] == rid
        assert api_module._registry.request_id_for(job_id) == rid

    def test_worker_job_events_carry_stored_id(self, monkeypatch, caplog):
        """job.claimed/job.stage run on a worker thread, far from any request.

        The only way their log lines carry our request id is the _run_job
        ContextVar restore from the persisted row (ticket #101). The engine
        is stubbed so the assertion never depends on real LLM latency.
        """
        import threading
        from types import SimpleNamespace

        rid = "b0b0deadbeef"
        token = set_request_id(rid)
        try:
            job = api_module._registry.create(
                {"resume_text": "x"}, None, tenant_id="t-rid"
            )
        finally:
            reset_request_id(token)
        api_module._payloads[job.job_id] = (
            {"resume_text": "x"},
            SimpleNamespace(is_llm_configured=True),
            None,
            "t-rid",
        )

        def fake_run(*args, **kwargs):
            api_module._registry.update_progress(job.job_id, "stage-x", "mid")
            return {"score": 1, "skills": [], "issues": [], "diffs": []}

        monkeypatch.setattr(api_module, "run", fake_run)
        with caplog.at_level(logging.INFO, logger="resualign.jobs"):
            worker = threading.Thread(
                target=api_module._run_job, args=(job.job_id,)
            )
            worker.start()
            worker.join(30)
        msgs = _rid_messages(caplog, rid)
        assert any('"job.claimed"' in m for m in msgs), msgs
        assert any('"job.stage"' in m for m in msgs)
        assert any('"job.finished"' in m for m in msgs)


class TestLogEventAutoRead:
    def test_log_event_reads_context_var_when_not_explicit(self, caplog):
        token = set_request_id("cccc2222dddd")
        try:
            log_event(logging.getLogger("test.rid"), "unit.event", extra={"a": 1})
        finally:
            reset_request_id(token)
        msgs = _rid_messages(caplog, "cccc2222dddd")
        assert any('"unit.event"' in m for m in msgs)

    def test_explicit_request_id_wins(self):
        logger = logging.getLogger("test.rid.explicit")
        logger.propagate = False
        sink: list[str] = []
        logger.addHandler(_Sink(sink))
        token = set_request_id("bound-id-123")
        try:
            log_event(logger, "unit.event2", request_id="explicit-id")
        finally:
            reset_request_id(token)
            logger.handlers.clear()
        payload = json.loads(sink[0])
        assert payload["request_id"] == "explicit-id"

    def test_no_field_when_unbound(self, caplog):
        assert current_request_id() is None
        log_event(logging.getLogger("test.rid"), "unit.event3")
        msgs = [
            m for m in (rec.getMessage() for rec in caplog.records)
            if '"unit.event3"' in m
        ]
        assert msgs and "request_id" not in json.loads(msgs[0])


class _Sink(logging.Handler):
    def __init__(self, sink: list[str]):
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record.getMessage())


class TestRecoveredRequeue:
    def test_requeue_mints_new_id_and_marks_recovered(self, tmp_path, caplog):
        reg = JobRegistry(db_path=tmp_path / "jobs.db")
        token = set_request_id("original-rid")
        try:
            job = reg.create({"x": 1}, None, tenant_id="t")
        finally:
            reset_request_id(token)
        assert reg.claim_running(job.job_id)
        with caplog.at_level(logging.INFO, logger="resualign.jobs"):
            assert reg.requeue_interrupted(job.job_id, request_id="recovered-1") is True
        assert reg.request_id_for(job.job_id) == "recovered-1"
        msgs = _rid_messages(caplog, "recovered-1")
        assert any('"job.requeued"' in m and '"recovered": true' in m for m in msgs)

    def test_requeue_of_queued_row_is_noop(self, tmp_path):
        reg = JobRegistry(db_path=tmp_path / "jobs.db")
        job = reg.create({"x": 1}, None)
        assert reg.requeue_interrupted(job.job_id, request_id="whatever") is False
        assert reg.request_id_for(job.job_id) is None  # untouched ''


class TestMigrationIdempotent:
    """A pre-#101 database (no request_id column) upgrades exactly once."""

    _OLD_SCHEMA = """
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        stage TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        tenant_id TEXT NOT NULL DEFAULT '',
        created_at REAL NOT NULL,
        started_at REAL,
        finished_at REAL,
        result_json TEXT,
        error TEXT
    );
    """

    def _legacy_db(self, tmp_path: Path) -> tuple[Path, str]:
        db = tmp_path / "legacy-jobs.db"
        conn = sqlite3.connect(db)
        conn.executescript(self._OLD_SCHEMA)
        conn.execute(
            "INSERT INTO jobs (job_id, status, stage, message, tenant_id, "
            "created_at) VALUES ('legacy1', 'queued', '', '', '', 1.0)",
        )
        conn.commit()
        conn.close()
        return db, "legacy1"

    def test_legacy_database_gains_column(self, tmp_path):
        db, legacy_id = self._legacy_db(tmp_path)
        reg = JobRegistry(db_path=db)
        # First touch triggers _ensure_initialized + migrations.
        assert reg.request_id_for(legacy_id) is None
        # New writes carry ids through the migrated table.
        token = set_request_id("after-migration")
        try:
            job = reg.create({"x": 1}, None)
        finally:
            reset_request_id(token)
        assert reg.request_id_for(job.job_id) == "after-migration"

    def test_migration_reruns_cleanly(self, tmp_path):
        db, _ = self._legacy_db(tmp_path)
        reg = JobRegistry(db_path=db)
        reg.snapshot("legacy1")  # force init/migration
        # Re-opening the same database must not re-apply or fail.
        reg2 = JobRegistry(db_path=db)
        assert reg2.request_id_for("legacy1") is None
