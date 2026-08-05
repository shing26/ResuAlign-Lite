"""Shared SQLite connection lifecycle and store errors."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from .jobs import default_job_db_path


class UserStoreError(Exception):
    """Raised for invalid credentials or duplicate user registration."""


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
    """Shared SQLite connection lifecycle for workspace stores."""

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
        schema: str,
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
                conn.executescript(schema)
                if cleanup:
                    conn.execute(cleanup[0], cleanup[1])
            self._initialized = True

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
