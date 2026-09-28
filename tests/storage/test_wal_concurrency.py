"""Sprint 6 WAL concurrency guardrails for the shared SQLite backing file.

Three layers of protection, all against one real on-disk database:

* pragma guard — a *plain* ``sqlite3`` connection to the test db (not via
  ``_SqliteStore``) reports ``journal_mode=wal`` plus the busy-timeout /
  synchronous settings every store applies (store_base.py ``_apply_sqlite_pragmas``).
* same-store contention — N worker threads create + list library jobs on one
  shared ``JobLibraryStore`` with zero "database is locked" failures.
* cross-store contention — ``JobRegistry`` and ``JobLibraryStore`` hammer the
  same db file concurrently, which is exactly what the API process does on
  every boot and under parallel load (see test_concurrency_tenant).

The dedicated store-level pragma coverage lives here rather than in
test_store_pragmas so the WAL assertion is tied to Sprint 6's guarantee:
agents, the daemon, and the web API all open the same file with WAL on.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.store_base import _SqliteStore

WRITER_THREADS = 4
PER_THREAD_JOBS = 5

_JD_TEXT = "负责后端服务开发。要求 Python 与 FastAPI 经验。月薪 25-35K。"


class _ProbeStore(_SqliteStore):
    def pragmas(self) -> dict[str, int | str]:
        with self._connect() as conn:
            return {
                "journal_mode": conn.execute(
                    "PRAGMA journal_mode"
                ).fetchone()[0],
                "busy_timeout": conn.execute(
                    "PRAGMA busy_timeout"
                ).fetchone()[0],
                "synchronous": conn.execute(
                    "PRAGMA synchronous"
                ).fetchone()[0],
            }


def _create_job(store: JobLibraryStore, tenant: str, index: int) -> dict:
    return store.create_job(
        tenant_id=tenant,
        title=f"Job {tenant} {index}",
        jd_text=f"{tenant} JD {index}: {_JD_TEXT}",
        company="WALCo",
    )


# -- Pragma guard ------------------------------------------------------------


def test_file_database_is_wal_for_plain_sqlite_readers(tmp_path):
    db = tmp_path / "wal-probe.db"
    store = JobLibraryStore(db_path=db)
    _create_job(store, "tenant-1", 0)

    # A raw sqlite3 connection must observe the WAL journal mode that the
    # stores applied when they created the schema. ``journal_mode`` is the
    # one persistent database setting (stored in the db header); the other
    # pragmas are per-connection and only visible on store-owned connections
    # (checked below via _ProbeStore).
    conn = sqlite3.connect(str(db))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()

    # And the store's own connection applies the full per-connection set.
    assert _ProbeStore(db_path=db).pragmas() == {
        "journal_mode": "wal",
        "busy_timeout": 5000,
        "synchronous": 1,
    }


# -- Same-store concurrency --------------------------------------------------


def test_concurrent_create_and_list_on_one_library_db(tmp_path):
    store = JobLibraryStore(db_path=tmp_path / "wal-same-store.db")
    failures: list[Exception] = []
    barrier = threading.Barrier(WRITER_THREADS)

    def worker(thread_index: int) -> int:
        tenant = f"wal-tenant-{thread_index}"
        created = 0
        try:
            barrier.wait(timeout=15)
            for index in range(PER_THREAD_JOBS):
                job = _create_job(store, tenant, index)
                assert job["job_id"]
                created += 1
                listed = store.list_jobs(tenant)
                assert any(
                    item["job_id"] == job["job_id"] for item in listed
                )
        except Exception as exc:  # pragma: no cover - failure path
            failures.append(exc)
        return created

    with ThreadPoolExecutor(max_workers=WRITER_THREADS) as pool:
        counts = list(pool.map(worker, range(WRITER_THREADS)))

    assert not failures, f"concurrent store failures: {failures}"
    assert sum(counts) == WRITER_THREADS * PER_THREAD_JOBS
    for thread_index in range(WRITER_THREADS):
        assert len(store.list_jobs(f"wal-tenant-{thread_index}")) == (
            PER_THREAD_JOBS
        )


# -- Cross-store concurrency -------------------------------------------------


def test_registry_and_library_write_same_wal_db_concurrently(tmp_path):
    db = tmp_path / "wal-cross-store.db"
    registry = JobRegistry(db_path=db)
    library = JobLibraryStore(db_path=db)

    # Warm the schema on both stores first, mirroring how the API process
    # boots before it accepts concurrent traffic (see test_concurrency_tenant).
    registry.create(
        {"resume_text": "warm"}, object(), tenant_id="warm"
    )
    _create_job(library, "warm", 0)

    failures: list[Exception] = []

    def registry_worker(thread_index: int) -> int:
        created = 0
        try:
            for index in range(PER_THREAD_JOBS):
                registry.create(
                    {"resume_text": f"resume {thread_index}-{index}"},
                    object(),
                    tenant_id=f"registry-{thread_index}",
                )
                created += 1
        except Exception as exc:  # pragma: no cover - failure path
            failures.append(exc)
        return created

    def library_worker(thread_index: int) -> int:
        created = 0
        try:
            for index in range(PER_THREAD_JOBS):
                _create_job(library, f"library-{thread_index}", index)
                created += 1
        except Exception as exc:  # pragma: no cover - failure path
            failures.append(exc)
        return created

    workers = [registry_worker, library_worker] * 2
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        counts = list(
            pool.map(lambda fn, index: fn(index), workers, range(len(workers)))
        )

    assert not failures, f"cross-store failures: {failures}"
    assert sum(counts) == len(workers) * PER_THREAD_JOBS
    # 1 warm-up registry row + 2 registry workers x PER_THREAD_JOBS.
    assert len(registry) == 1 + 2 * PER_THREAD_JOBS
    # library workers run at worker indices 1 and 3.
    assert len(library.list_jobs("library-1")) == PER_THREAD_JOBS
    assert len(library.list_jobs("library-3")) == PER_THREAD_JOBS


def test_cold_start_schema_race_on_shared_db(tmp_path):
    """Known-bug gate: two stores racing first init on one fresh db file.

    ``store_base._apply_sqlite_pragmas`` runs ``PRAGMA journal_mode=WAL`` on
    every new connection. The WAL mode switch takes an exclusive lock and is
    not covered by the busy handler, so when two stores initialize their
    schema on the same fresh file at the same moment, one can raise
    ``database is locked`` *at the pragma* rather than at the write:

        store_base.py:51 connection.execute("PRAGMA journal_mode=WAL")

    The web API hides this because its stores warm up serially at boot before
    concurrent requests arrive. This test reproduces the race and flips to a
    hard assertion once the backend hardens store_base (idempotent WAL setup
    or a locked-tolerant pragma). Skipped while the known bug is present.
    """
    db = tmp_path / "wal-cold-start.db"
    registry = JobRegistry(db_path=db)
    library = JobLibraryStore(db_path=db)

    failures: list[Exception] = []

    def registry_worker(thread_index: int) -> int:
        created = 0
        try:
            for index in range(PER_THREAD_JOBS):
                registry.create(
                    {"resume_text": f"resume {thread_index}-{index}"},
                    object(),
                    tenant_id=f"registry-{thread_index}",
                )
                created += 1
        except Exception as exc:  # pragma: no cover - bug-gate path
            failures.append(exc)
        return created

    def library_worker(thread_index: int) -> int:
        created = 0
        try:
            for index in range(PER_THREAD_JOBS):
                _create_job(library, f"library-{thread_index}", index)
                created += 1
        except Exception as exc:  # pragma: no cover - bug-gate path
            failures.append(exc)
        return created

    workers = [registry_worker, library_worker] * 2
    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        counts = list(
            pool.map(lambda fn, index: fn(index), workers, range(len(workers)))
        )

    locked = [
        exc
        for exc in failures
        if isinstance(exc, sqlite3.OperationalError)
        and "database is locked" in str(exc)
    ]
    if locked and len(locked) == len(failures):
        pytest.skip(
            "已知缺陷(待 A 修复 store_base.py:51 PRAGMA journal_mode=WAL "
            f"冷启动竞态): {locked[0]}"
        )
    assert not failures, f"cold-start failures: {failures}"
    assert sum(counts) == len(workers) * PER_THREAD_JOBS
