"""Small SQLite-backed content-hash cache for deterministic LLM stages."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .store_base import _apply_sqlite_pragmas


def content_sha256(text: str) -> str:
    """Return a stable SHA-256 fingerprint for cache content."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


class ContentCache:
    """Content cache keyed by tenant, model, prompt version, and SHA-256."""

    def __init__(
        self,
        db_path: Optional[str | Path] = None,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self.db_path = str(db_path or ":memory:")
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.RLock()
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            _apply_sqlite_pragmas(
                self._conn, in_memory=self.db_path == ":memory:"
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_cache (
                    tenant TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    PRIMARY KEY (tenant, model, prompt_version, content_sha256)
                )
                """
            )
            self._conn.commit()

    def get(
        self,
        tenant: str,
        model: str,
        prompt_version: str,
        content: str,
    ) -> Optional[dict[str, Any]]:
        """Return a cached payload if it exists and has not expired."""
        digest = content_sha256(content)
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT payload FROM content_cache
                WHERE tenant = ? AND model = ? AND prompt_version = ?
                  AND content_sha256 = ? AND expires_at > ?
                """,
                (tenant, model, prompt_version, digest, now),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row[0])

    def put(
        self,
        tenant: str,
        model: str,
        prompt_version: str,
        content: str,
        payload: dict[str, Any],
    ) -> None:
        """Store or replace a cached payload for the derived key."""
        digest = content_sha256(content)
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO content_cache (
                    tenant, model, prompt_version, content_sha256,
                    payload, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant,
                    model,
                    prompt_version,
                    digest,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                    now + self.ttl_seconds,
                ),
            )
            self._conn.commit()

    def clear(self) -> None:
        """Delete all cached entries."""
        with self._lock:
            self._conn.execute("DELETE FROM content_cache")
            self._conn.commit()

    def close(self) -> None:
        """Release the SQLite connection."""
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "ContentCache":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
