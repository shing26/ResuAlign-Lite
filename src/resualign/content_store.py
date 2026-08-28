"""SQLite-backed content blob store with ref-counted deduplication.

The public retrieval API returns bytes, never Python strings, so callers cannot
accidentally serialize blob content as an API response through this module.
``get_text`` is an explicit internal convenience for CLI/local use only and must
not be used to build API responses.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

from .store_base import _apply_sqlite_pragmas

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_TTL_SECONDS = 30 * 24 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content_blobs (
    sha256 TEXT PRIMARY KEY,
    content BLOB NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    ref_count INTEGER NOT NULL DEFAULT 1 CHECK (ref_count >= 0),
    created_at REAL NOT NULL,
    last_accessed_at REAL NOT NULL,
    expires_at REAL
);
CREATE INDEX IF NOT EXISTS idx_content_blobs_expires
    ON content_blobs(expires_at);
CREATE INDEX IF NOT EXISTS idx_content_blobs_last_accessed
    ON content_blobs(last_accessed_at);
"""

_Content = Union[str, bytes, bytearray, memoryview]


def default_content_db_path() -> Path:
    """Return the default SQLite database path for stored content."""
    from .jobs import resolve_data_dir

    return resolve_data_dir() / "content.db"


class ContentStore:
    """Tenant-agnostic SQLite blob store with reference counting and pruning."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        default_ttl_seconds: float | None = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if default_ttl_seconds is not None and default_ttl_seconds <= 0:
            raise ValueError("default_ttl_seconds must be positive")
        if db_path is None:
            db_path = default_content_db_path()
        self.db_path = Path(db_path).expanduser()
        self.max_bytes = max_bytes
        self.default_ttl_seconds = default_ttl_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._initialized = False
        self._memory_connection: Optional[sqlite3.Connection] = None
        # Per-thread pooled connections (see store_base._SqliteStore): the
        # PRAGMA setup costs ~95 ms per fresh connection on Windows.
        self._local = threading.local()
        self._open_connections: list[sqlite3.Connection] = []
        self._conn_guard = threading.Lock()

    # -- connection pool -------------------------------------------------
    def _acquire_connection(self) -> sqlite3.Connection:
        """Return this thread's pooled connection, creating it on first use."""
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

    def put(
        self,
        sha256: str,
        content: _Content,
        content_type: str,
        *,
        ttl_seconds: float | None = None,
    ) -> str:
        """Store content once and claim one reference for this call.

        Identical content is stored once; every successful put increments the
        reference count and every delete releases one reference.
        """
        payload = self._payload(sha256, content)
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        now = self._clock()
        expires_at = self._expires_at(now, ttl_seconds)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                self._prune_expired_locked(conn, now)
                row = conn.execute(
                    "SELECT content FROM content_blobs WHERE sha256 = ?",
                    (sha256,),
                ).fetchone()
                if row is not None:
                    if row["content"] != payload:
                        raise ValueError("sha256 collision")
                    conn.execute(
                        "UPDATE content_blobs SET content_type = ?, "
                        "ref_count = ref_count + 1, last_accessed_at = ?, "
                        "expires_at = ? WHERE sha256 = ?",
                        (content_type, now, expires_at, sha256),
                    )
                else:
                    conn.execute(
                        "INSERT INTO content_blobs ("
                        "sha256, content, content_type, size_bytes, ref_count, "
                        "created_at, last_accessed_at, expires_at"
                        ") VALUES (?, ?, ?, ?, 1, ?, ?, ?)",
                        (
                            sha256,
                            payload,
                            content_type,
                            len(payload),
                            now,
                            now,
                            expires_at,
                        ),
                    )
                self._enforce_size_cap_locked(conn, now)
        return sha256

    def get(self, sha256: str) -> Optional[bytes]:
        """Return blob content as bytes, or None when absent or expired."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                self._prune_expired_locked(conn, now)
                row = conn.execute(
                    "SELECT content FROM content_blobs "
                    "WHERE sha256 = ? AND "
                    "(expires_at IS NULL OR expires_at > ?)",
                    (sha256, now),
                ).fetchone()
                if row is None:
                    return None
                conn.execute(
                    "UPDATE content_blobs SET last_accessed_at = ? "
                    "WHERE sha256 = ?",
                    (now, sha256),
                )
                return bytes(row["content"])

    def get_text(
        self,
        sha256: str,
        *,
        encoding: str = "utf-8",
    ) -> Optional[str]:
        """Decode blob content for CLI/internal use only.

        API response paths must use ``get`` and keep content as bytes.
        """
        content = self.get(sha256)
        return content.decode(encoding) if content is not None else None

    def delete(self, sha256: str) -> bool:
        """Release one reference; remove the blob when none remain."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                self._prune_expired_locked(conn, now)
                row = conn.execute(
                    "SELECT ref_count FROM content_blobs WHERE sha256 = ?",
                    (sha256,),
                ).fetchone()
                if row is None:
                    return False
                if row["ref_count"] <= 1:
                    conn.execute(
                        "DELETE FROM content_blobs WHERE sha256 = ?",
                        (sha256,),
                    )
                else:
                    conn.execute(
                        "UPDATE content_blobs SET ref_count = ref_count - 1 "
                        "WHERE sha256 = ?",
                        (sha256,),
                    )
                return True

    def exists(self, sha256: str) -> bool:
        """Return whether unexpired content is currently stored."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                self._prune_expired_locked(conn, now)
                row = conn.execute(
                    "SELECT 1 FROM content_blobs "
                    "WHERE sha256 = ? AND "
                    "(expires_at IS NULL OR expires_at > ?)",
                    (sha256, now),
                ).fetchone()
                return row is not None

    def ref_count(self, sha256: str) -> int:
        """Return the current reference count for a stored blob."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT ref_count FROM content_blobs WHERE sha256 = ?",
                    (sha256,),
                ).fetchone()
                return int(row["ref_count"]) if row is not None else 0

    def total_size(self) -> int:
        """Return total bytes stored, including duplicate references once."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(size_bytes), 0) "
                    "FROM content_blobs"
                ).fetchone()
                return int(row[0])

    def prune(self) -> int:
        """Remove expired and over-cap blobs, returning the count removed."""
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                removed = self._prune_expired_locked(conn, now)
                removed += self._enforce_size_cap_locked(conn, now)
                return removed

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
            self._initialized = True

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
            connection = self._acquire_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        # Pooled connection intentionally left open (see _acquire_connection).

    @staticmethod
    def _payload(sha256: str, content: _Content) -> bytes:
        if isinstance(content, str):
            payload = content.encode("utf-8")
        else:
            payload = bytes(content)
        if hashlib.sha256(payload).hexdigest() != sha256:
            raise ValueError("sha256 does not match content")
        return payload

    def _expires_at(
        self,
        now: float,
        ttl_seconds: float | None,
    ) -> Optional[float]:
        ttl = (
            ttl_seconds
            if ttl_seconds is not None
            else self.default_ttl_seconds
        )
        return now + ttl if ttl is not None else None

    def _prune_expired_locked(self, conn: sqlite3.Connection, now: float) -> int:
        cursor = conn.execute(
            "DELETE FROM content_blobs "
            "WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        return cursor.rowcount

    def _enforce_size_cap_locked(
        self,
        conn: sqlite3.Connection,
        now: float,
    ) -> int:
        removed = 0
        while True:
            total = int(
                conn.execute(
                    "SELECT COALESCE(SUM(size_bytes), 0) "
                    "FROM content_blobs"
                ).fetchone()[0]
            )
            if total <= self.max_bytes:
                return removed
            row = conn.execute(
                "SELECT sha256 FROM content_blobs "
                "ORDER BY last_accessed_at ASC, created_at ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return removed
            conn.execute(
                "DELETE FROM content_blobs WHERE sha256 = ?",
                (row["sha256"],),
            )
            removed += 1
