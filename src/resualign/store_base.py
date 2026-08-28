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


def resolve_upload_dir() -> Path:
    """Return the runtime upload directory for parsed resume files.

    ``RESUALIGN_UPLOAD_DIR`` wins when set; otherwise uploads live under
    the resolved data directory as ``<DataDir>/uploads/`` so one backup
    snapshot covers both SQLite data and uploaded originals.
    """
    override = os.environ.get("RESUALIGN_UPLOAD_DIR")
    if override:
        return Path(override).expanduser()
    return resolve_data_dir() / "uploads"


def _apply_sqlite_pragmas(
    connection: sqlite3.Connection,
    *,
    in_memory: bool = False,
) -> None:
    """Apply the package-wide SQLite connection settings."""
    connection.execute("PRAGMA foreign_keys=ON")
    if in_memory:
        return
    _set_wal_with_retry(connection)
    connection.execute("PRAGMA busy_timeout=5000")
    connection.execute("PRAGMA synchronous=NORMAL")


def _set_wal_with_retry(connection) -> None:
    """Switch to WAL journal mode, tolerating first-open contention.

    ``PRAGMA journal_mode=WAL`` requires an exclusive lock and does NOT
    honor ``busy_timeout``, so when two stores first initialize the same
    fresh database concurrently one of them can hit ``database is locked``.
    WAL mode persists in the db header, so retrying briefly is safe.
    """
    for attempt in range(3):
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))


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
        # Per-thread pooled connections. Opening a SQLite file and applying
        # the PRAGMA set costs ~95 ms on Windows (bare connect is 0.7 ms), so
        # doing it per query made even an 11-row list_jobs take ~1.4 s.
        self._local = threading.local()
        self._open_connections: list[sqlite3.Connection] = []
        self._conn_guard = threading.Lock()
        if db_path is None:
            db_path = default_job_db_path()
        self.db_path = Path(db_path).expanduser()

    # -- connection pool -------------------------------------------------
    def _acquire_connection(self) -> sqlite3.Connection:
        """Return this thread's pooled connection, creating it on first use.

        SQLite connections are bound to the creating thread by default, so
        the pool is keyed by thread. A connection whose file was replaced or
        closed behind our back is detected with a cheap ``SELECT 1`` probe
        and recreated.
        """
        connection: Optional[sqlite3.Connection] = getattr(
            self._local, "conn", None
        )
        if connection is not None:
            try:
                connection.execute("SELECT 1").fetchone()
                return connection
            except sqlite3.Error:
                self.close_thread_connection()
        connection = sqlite3.connect(str(self.db_path), timeout=5.0)
        connection.row_factory = sqlite3.Row
        _apply_sqlite_pragmas(connection, in_memory=False)
        self._local.conn = connection
        with self._conn_guard:
            self._open_connections.append(connection)
        return connection

    def close_thread_connection(self) -> None:
        """Close the calling thread's pooled connection (no-op if none)."""
        connection: Optional[sqlite3.Connection] = getattr(
            self._local, "conn", None
        )
        if connection is None:
            return
        self._local.conn = None
        with self._conn_guard:
            if connection in self._open_connections:
                self._open_connections.remove(connection)
        try:
            connection.close()
        except sqlite3.Error:
            pass

    def close_all_connections(self) -> None:
        """Close every pooled connection across all threads."""
        with self._conn_guard:
            connections = list(self._open_connections)
            self._open_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except sqlite3.Error:
                pass

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
        """Apply pending versioned migrations exactly once, per store.

        Every store's MIGRATIONS are numbered from 1, so the migration
        journal is scoped by store name. A migration whose ALTER fails
        because the column already exists is recorded as applied: the
        current CREATE schema already carries it, so the historical
        upgrade is a no-op for this database.

        Legacy journals (single shared ``version`` primary key, no store
        column) are rebuilt: old rows cannot be attributed to a store, and
        replaying them is safe because every script is idempotent
        (``CREATE ... IF NOT EXISTS`` or duplicate-column swallowing).
        """
        migrations = type(self).MIGRATIONS or ()
        if not migrations:
            return
        store = type(self).__name__
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "store TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL, "
            "applied_at REAL NOT NULL, PRIMARY KEY (store, version))"
        )
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(schema_migrations)"
            ).fetchall()
        }
        if "store" not in columns:
            conn.execute(
                "ALTER TABLE schema_migrations "
                "RENAME TO schema_migrations_legacy"
            )
            conn.execute(
                "CREATE TABLE schema_migrations ("
                "store TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL, "
                "applied_at REAL NOT NULL, PRIMARY KEY (store, version))"
            )
            conn.execute("DROP TABLE schema_migrations_legacy")
        applied = {
            row["version"]
            for row in conn.execute(
                "SELECT version FROM schema_migrations WHERE store = ?",
                (store,),
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
                "INSERT INTO schema_migrations (store, version, applied_at) "
                "VALUES (?, ?, ?)",
                (store, version, time.time()),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        in_memory = str(self.db_path) == ":memory:"
        if in_memory:
            if self._memory_connection is None:
                self._memory_connection = sqlite3.connect(":memory:")
                self._memory_connection.row_factory = sqlite3.Row
            connection = self._memory_connection
            _apply_sqlite_pragmas(connection, in_memory=True)
        else:
            # Pooled per thread: PRAGMAs are applied once, at creation.
            connection = self._acquire_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        # NOTE: the pooled connection is intentionally left open; it is
        # closed by close_thread_connection()/close_all_connections() or
        # when the owning thread exits and the store is garbage collected.
