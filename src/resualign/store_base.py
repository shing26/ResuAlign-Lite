"""Shared SQLite connection lifecycle and store errors."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional


class UserStoreError(Exception):
    """Raised for invalid credentials or duplicate user registration."""


def resolve_data_dir() -> Path:
    """Return the single runtime data directory for all SQLite stores.

    Priority: ``RESUALIGN_DATA_DIR`` > parent of ``RESUALIGN_JOB_DB`` >
    the repo-root ``data/`` directory. Keeps jobs, content, and caches in
    one place so backups and container mounts cover everything.
    """
    override = os.environ.get("RESUALIGN_DATA_DIR")
    if override:
        return Path(override).expanduser()
    job_db = os.environ.get("RESUALIGN_JOB_DB")
    if job_db:
        return Path(job_db).expanduser().parent
    return Path(__file__).resolve().parents[2] / "data"


def default_job_db_path() -> Path:
    """Return the configured or default SQLite database path."""
    override = os.environ.get("RESUALIGN_JOB_DB")
    if override:
        return Path(override).expanduser()
    return resolve_data_dir() / "jobs.db"


def _apply_sqlite_pragmas(
    connection: sqlite3.Connection,
    *,
    in_memory: bool = False,
) -> None:
    """Apply the package-wide SQLite connection settings."""
    connection.execute("PRAGMA foreign_keys=ON")
    if in_memory:
        return
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA synchronous=NORMAL")


class _SqliteStore:
    """Shared SQLite connection lifecycle for workspace stores.

    Subclasses provide the current ``SCHEMA_SQL`` CREATE script (fresh
    databases) and an ordered ``MIGRATIONS`` tuple of historical upgrade
    scripts. Every migration runs exactly once against old databases; fresh
    databases created from the current schema skip the ALTERs because they
    already carry the columns (a duplicate-column failure is treated as
    already-applied).
    """

    SCHEMA_SQL: str = ""
    MIGRATIONS: tuple[tuple[int, str], ...] = ()

    def __init__(
        self,
        db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._initialized = False
        self._memory_connection: Optional[sqlite3.Connection] = None
        if db_path is None:
            db_path = default_job_db_path()
        self.db_path = Path(db_path).expanduser()

    def _ensure_initialized(
        self,
        schema: str | None = None,
        cleanup: Optional[tuple[str, tuple[Any, ...]]] = None,
    ) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            if str(self.db_path) != ":memory:":
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as conn:
                schema = schema if schema is not None else self.SCHEMA_SQL
                if schema:
                    conn.executescript(schema)
                if cleanup:
                    conn.execute(cleanup[0], cleanup[1])
                self._apply_migrations(conn)
            self._initialized = True

    def _apply_migrations(self, conn: sqlite3.Connection) -> None:
        """Apply pending versioned migrations exactly once.

        A migration whose ALTER fails because the column already exists is
        recorded as applied: the current CREATE schema already carries it,
        so the historical upgrade is a no-op for this database.
        """
        migrations = type(self).MIGRATIONS or ()
        if not migrations:
            return
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        applied = {
            row["version"]
            for row in conn.execute(
                "SELECT version FROM schema_migrations"
            ).fetchall()
        }
        for version, script in sorted(migrations):
            if version in applied:
                continue
            try:
                conn.executescript(script)
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (?, ?)",
                (version, time.time()),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        in_memory = str(self.db_path) == ":memory:"
        if in_memory:
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(":memory:")
                self._memory_connection.row_factory = sqlite3.Row
            connection = self._memory_connection
        else:
            connection = sqlite3.connect(str(self.db_path), timeout=5.0)
            connection.row_factory = sqlite3.Row
        _apply_sqlite_pragmas(connection, in_memory=in_memory)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if not in_memory:
                connection.close()
