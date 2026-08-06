"""SQLite-backed job store for the async analysis API."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .observability import log_event
from .store_base import (
    _SqliteStore,
    default_job_db_path,  # noqa: F401  (re-exported for external callers)
    resolve_data_dir,  # noqa: F401  (re-exported for external callers)
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_JOBS = 100
DEFAULT_JOB_TTL_SECONDS = 60 * 60
INTERRUPTED_BY_RESTART = "Job interrupted by server restart"

_SCHEMA = """
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
CREATE TABLE IF NOT EXISTS job_payloads (
    job_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    application_id TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
);
"""

_INDEX_SQL = "CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON jobs(tenant_id)"

_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS job_payloads (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            application_id TEXT,
            created_at REAL NOT NULL,
            FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        """,
    ),
)

_JOB_COLUMNS = (
    "job_id, status, stage, message, tenant_id, created_at, started_at, "
    "finished_at, result_json, error"
)


@dataclass
class AnalysisJob:
    job_id: str
    payload: Optional[dict[str, Any]] = None
    config: Any = None
    status: str = "queued"
    stage: str = ""
    message: str = ""
    tenant_id: str = ""
    created_at: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class JobRegistry(_SqliteStore):
    """Thread-safe registry persisted in SQLite with TTL and a size cap."""

    MIGRATIONS = _MIGRATIONS

    def __init__(
        self,
        max_jobs: int = DEFAULT_MAX_JOBS,
        ttl_seconds: float = DEFAULT_JOB_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        db_path: str | Path | None = None,
    ) -> None:
        super().__init__(db_path)
        self.max_jobs = max_jobs
        self.ttl_seconds = ttl_seconds
        self._clock = clock

    def create(
        self,
        payload: dict[str, Any],
        config: Any,
        tenant_id: str | None = None,
        application_id: str | None = None,
    ) -> AnalysisJob:
        """Create a queued job, purging expired entries first."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            self._purge_expired(now)
            job = AnalysisJob(
                job_id=uuid.uuid4().hex,
                payload=dict(payload),
                config=config,
                tenant_id=tenant_id or "",
                created_at=now,
            )
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO jobs ("
                    "job_id, status, stage, message, tenant_id, created_at, "
                    "started_at, finished_at, result_json, error"
                    ") VALUES (?, 'queued', '', '', ?, ?, NULL, NULL, NULL, NULL)",
                    (job.job_id, job.tenant_id, now),
                )
                conn.execute(
                    "INSERT INTO job_payloads ("
                    "job_id, tenant_id, payload_json, application_id, created_at"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (
                        job.job_id,
                        job.tenant_id,
                        json.dumps(
                            payload, ensure_ascii=False, separators=(",", ":")
                        ),
                        application_id,
                        now,
                    ),
                )
            self._enforce_cap()
            log_event(
                logger,
                "job.queued",
                extra={"job_id": job.job_id, "tenant_id": job.tenant_id},
            )
            return job

    def get_payload(
        self, job_id: str
    ) -> Optional[tuple[dict[str, Any], str, Optional[str]]]:
        """Return (payload, tenant_id, application_id) or None."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT tenant_id, payload_json, application_id "
                    "FROM job_payloads WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
                if row is None:
                    return None
                return (
                    json.loads(row["payload_json"]),
                    row["tenant_id"],
                    row["application_id"],
                )

    def delete_payload(self, job_id: str) -> None:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM job_payloads WHERE job_id = ?", (job_id,)
                )

    def pending_job_ids(self) -> list[str]:
        """Return queued/running job ids in submission order."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_id FROM jobs "
                    "WHERE status IN ('queued', 'running') "
                    "ORDER BY created_at ASC, rowid ASC"
                ).fetchall()
                return [row["job_id"] for row in rows]

    def get(
        self, job_id: str, tenant_id: str | None = None
    ) -> Optional[AnalysisJob]:
        """Return the job or None when it is unknown or expired."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            return self._get_current(job_id, now, tenant_id=tenant_id)

    def claim_running(self, job_id: str) -> bool:
        """Atomically claim a queued job and return True on success."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'running', started_at = ? "
                    "WHERE job_id = ? AND status = 'queued'",
                    (now, job_id),
                )
                claimed = cursor.rowcount > 0
            if claimed:
                log_event(logger, "job.claimed", extra={"job_id": job_id})
            return claimed

    def mark_running(self, job_id: str) -> None:
        """Backward-compatible running transition that ignores double claims."""
        self.claim_running(job_id)

    def requeue_interrupted(self, job_id: str) -> bool:
        """Requeue a running job left by a dead process; queued stays queued."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'queued', started_at = NULL "
                    "WHERE job_id = ? AND status = 'running'",
                    (job_id,),
                )
                requeued = cursor.rowcount > 0
            if requeued:
                log_event(logger, "job.requeued", extra={"job_id": job_id})
            return requeued

    def update_progress(self, job_id: str, stage: str, message: str) -> None:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET stage = ?, message = ? "
                    "WHERE job_id = ? AND status = 'running'",
                    (stage, message, job_id),
                )
                updated = cursor.rowcount > 0
            if updated:
                log_event(
                    logger,
                    "job.stage",
                    extra={"job_id": job_id, "stage": stage, "message": message},
                )

    def succeed(self, job_id: str, result: dict[str, Any]) -> None:
        now = self._clock()
        result_json = (
            json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            if result is not None
            else None
        )
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'succeeded', result_json = ?, "
                    "finished_at = ? "
                    "WHERE job_id = ? AND status IN ('queued', 'running')",
                    (result_json, now, job_id),
                )
                updated = cursor.rowcount > 0
            if updated:
                log_event(
                    logger,
                    "job.finished",
                    extra={"job_id": job_id, "outcome": "succeeded"},
                )

    def fail(self, job_id: str, error: str, stage: str | None = None) -> None:
        """Mark a job failed, optionally recording the failing pipeline stage."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'failed', error = ?, "
                    "finished_at = ? "
                    "WHERE job_id = ? AND status IN ('queued', 'running')",
                    (error, now, job_id),
                )
                updated = cursor.rowcount > 0
                if updated and stage:
                    conn.execute(
                        "UPDATE jobs SET stage = ? WHERE job_id = ?",
                        (stage, job_id),
                    )
            if updated:
                log_event(
                    logger,
                    "job.finished",
                    extra={
                        "job_id": job_id,
                        "outcome": "failed",
                        "error": error,
                    },
                )

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued job; running/finished jobs cannot be canceled."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE jobs SET status = 'canceled', "
                    "error = 'Canceled by user', finished_at = ? "
                    "WHERE job_id = ? AND status = 'queued'",
                    (now, job_id),
                )
                canceled = cursor.rowcount > 0
            if canceled:
                log_event(
                    logger,
                    "job.finished",
                    extra={"job_id": job_id, "outcome": "canceled"},
                )
            return canceled

    def delete(self, job_id: str, tenant_id: str | None = None) -> bool:
        """Delete a job and its payload, scoped to the tenant."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                if tenant_id:
                    row = conn.execute(
                        "SELECT 1 FROM jobs WHERE job_id = ? AND tenant_id = ?",
                        (job_id, tenant_id),
                    ).fetchone()
                    if row is None:
                        return False
                conn.execute(
                    "DELETE FROM job_payloads WHERE job_id = ?", (job_id,)
                )
                cursor = conn.execute(
                    "DELETE FROM jobs WHERE job_id = ?", (job_id,)
                )
                return cursor.rowcount > 0

    def snapshot(
        self, job_id: str, tenant_id: str | None = None
    ) -> Optional[dict[str, Any]]:
        """Return the public job payload, or None for unknown/expired jobs."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            job = self._get_current(job_id, now, tenant_id=tenant_id)
            if job is None:
                return None
            return {
                "job_id": job.job_id,
                "status": job.status,
                "stage": job.stage,
                "message": job.message,
                "elapsed_seconds": self._elapsed(job, now),
                "result": job.result if job.status == "succeeded" else None,
                "error": job.error
                if job.status in ("failed", "canceled")
                else None,
            }

    def clear(self) -> None:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute("DELETE FROM job_payloads")
                conn.execute("DELETE FROM jobs")

    def __len__(self) -> int:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                return int(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def queue_depth(self) -> int:
        """Return the number of queued or running jobs."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM jobs "
                    "WHERE status IN ('queued', 'running')"
                ).fetchone()
                return int(row[0])

    def oldest_waiting_seconds(self) -> Optional[float]:
        """Seconds the oldest queued job has been waiting, or None."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT created_at FROM jobs WHERE status = 'queued' "
                    "ORDER BY created_at ASC, rowid ASC LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                return round(max(0.0, now - row["created_at"]), 1)

    def outcome_stats(self) -> dict[str, int]:
        """Count jobs grouped by status for /api/ops/metrics."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
                ).fetchall()
                return {row["status"]: int(row["n"]) for row in rows}

    def ping(self) -> bool:
        """Readiness probe: True when the underlying database is readable."""
        try:
            with self._lock:
                self._ensure_initialized()
                with self._connect() as conn:
                    conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            if str(self.db_path) != ":memory:":
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                conn.executescript(_SCHEMA)
                columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
                }
                if "tenant_id" not in columns:
                    conn.execute(
                        "ALTER TABLE jobs ADD COLUMN tenant_id TEXT NOT NULL "
                        "DEFAULT ''"
                    )
                conn.execute(_INDEX_SQL)
                self._apply_migrations(conn)
            self._initialized = True

    def _get_current(
        self,
        job_id: str,
        now: float,
        tenant_id: str | None = None,
    ) -> Optional[AnalysisJob]:
        with self._connect() as conn:
            if tenant_id is None:
                row = conn.execute(
                    f"SELECT {_JOB_COLUMNS} FROM jobs WHERE job_id = ?",
                    (job_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT {_JOB_COLUMNS} FROM jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
            if row is None:
                return None
            if self._is_expired(row["created_at"], now):
                conn.execute(
                    "DELETE FROM job_payloads WHERE job_id = ?", (job_id,)
                )
                conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                return None
            return self._row_to_job(row)

    def _row_to_job(self, row: sqlite3.Row) -> AnalysisJob:
        result = (
            json.loads(row["result_json"])
            if row["result_json"] is not None
            else None
        )
        return AnalysisJob(
            job_id=row["job_id"],
            status=row["status"],
            stage=row["stage"],
            message=row["message"],
            tenant_id=row["tenant_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result=result,
            error=row["error"],
        )

    def _elapsed(self, job: AnalysisJob, now: float) -> float:
        if job.started_at is None:
            return 0.0
        end = job.finished_at if job.finished_at is not None else now
        return round(end - job.started_at, 1)

    def _is_expired(self, created_at: float, now: float) -> bool:
        return now - created_at > self.ttl_seconds

    def _purge_expired(self, now: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM job_payloads WHERE job_id IN ("
                "SELECT job_id FROM jobs WHERE created_at < ?)",
                (now - self.ttl_seconds,),
            )
            conn.execute(
                "DELETE FROM jobs WHERE created_at < ?",
                (now - self.ttl_seconds,),
            )

    def _enforce_cap(self) -> None:
        with self._connect() as conn:
            while True:
                count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
                if count <= self.max_jobs:
                    break
                row = conn.execute(
                    "SELECT job_id FROM jobs "
                    "WHERE status NOT IN ('queued', 'running') "
                    "ORDER BY created_at ASC, rowid ASC LIMIT 1"
                ).fetchone()
                if row is None:
                    # Never evict in-flight or pending work.
                    break
                conn.execute(
                    "DELETE FROM job_payloads WHERE job_id = ?",
                    (row["job_id"],),
                )
                conn.execute(
                    "DELETE FROM jobs WHERE job_id = ?",
                    (row["job_id"],),
                )
