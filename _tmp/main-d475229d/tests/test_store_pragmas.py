"""Tests for unified SQLite pragmas and durable job claims."""

from resualign.jobs import JobRegistry
from resualign.store_base import _SqliteStore


class _ProbeStore(_SqliteStore):
    def pragmas(self):
        with self._connect() as conn:
            return {
                "journal_mode": conn.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0],
                "busy_timeout": conn.execute(
                    "PRAGMA busy_timeout"
                ).fetchone()[0],
                "foreign_keys": conn.execute(
                    "PRAGMA foreign_keys"
                ).fetchone()[0],
                "synchronous": conn.execute(
                    "PRAGMA synchronous"
                ).fetchone()[0],
            }


def test_file_store_uses_wal_and_unified_pragmas(tmp_path):
    store = _ProbeStore(db_path=tmp_path / "probe.db")

    first = store.pragmas()
    second = store.pragmas()

    assert first == second
    assert first["journal_mode"] == "wal"
    assert first["busy_timeout"] == 5000
    assert first["foreign_keys"] == 1
    assert first["synchronous"] == 1


def test_memory_store_keeps_single_connection_and_foreign_keys():
    store = _ProbeStore(db_path=":memory:")

    pragmas = store.pragmas()

    assert pragmas["journal_mode"] == "memory"
    assert pragmas["foreign_keys"] == 1
    with store._connect() as first:
        first_id = id(first)
    with store._connect() as second:
        assert id(second) == first_id


def test_job_registry_file_connections_use_wal(tmp_path):
    registry = JobRegistry(db_path=tmp_path / "jobs.db")
    registry.create({"resume_text": "resume"}, object())

    with registry._connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1


def test_claim_running_prevents_double_start(tmp_path):
    registry = JobRegistry(db_path=tmp_path / "jobs.db")
    job = registry.create({"resume_text": "resume"}, object())

    assert registry.claim_running(job.job_id) is True
    assert registry.get(job.job_id).status == "running"

    assert registry.claim_running(job.job_id) is False
    assert registry.get(job.job_id).status == "running"

    assert registry.mark_running(job.job_id) is None
    assert registry.get(job.job_id).status == "running"
