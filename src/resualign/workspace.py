"""SQLite-backed user identity and tenant session store."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .store_base import UserStoreError, _SqliteStore

TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

_MASTER_RESUME_SCHEMA = """
CREATE TABLE IF NOT EXISTS master_resumes (
    resume_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    latest_diagnosis_job_id TEXT,
    latest_diagnosis_json TEXT,
    latest_diagnosis_source_hash TEXT,
    profile_json TEXT,
    profile_source_sha256 TEXT,
    profile_model TEXT
);
CREATE TABLE IF NOT EXISTS resume_versions (
    version_id TEXT PRIMARY KEY,
    resume_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(resume_id, version)
);
CREATE INDEX IF NOT EXISTS idx_resume_versions_resume
    ON resume_versions(resume_id);
"""

_APPLICATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    master_resume_id TEXT NOT NULL,
    resume_version INTEGER NOT NULL,
    resume_snapshot TEXT NOT NULL,
    jd_text TEXT,
    jd_url TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    latest_job_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_applications_tenant ON applications(tenant_id);
"""

APPLICATION_STATUSES = (
    "draft",
    "applied",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "running",
    "queued",
    "succeeded",
    "failed",
    "canceled",
)

_APPLICATION_STATUS_ALIASES = {
    "未投递": "draft",
    "已投递": "applied",
    "面试中": "interview",
    "已拿Offer": "offer",
    "放弃": "withdrawn",
    "rejected": "withdrawn",
}


def application_status_canonical(status: str) -> str:
    """Map a stored application status into the unified five-state model."""
    value = str(status or "").strip()
    return _APPLICATION_STATUS_ALIASES.get(value, value)


class UserStore(_SqliteStore):
    """Thread-safe user and session store persisted in SQLite."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        clock: callable = time.time,
        token_ttl: float = TOKEN_TTL_SECONDS,
    ) -> None:
        super().__init__(db_path)
        self._clock = clock
        self._token_ttl = token_ttl

    def create_user(self, email: str, password: str) -> dict[str, Any]:
        """Create a user and return a public user dict (no secrets)."""
        email = email.strip().lower()
        self._validate_email(email)
        if len(password) < 8:
            raise UserStoreError("Password must be at least 8 characters")

        salt = secrets.token_hex(16)
        password_hash = self._hash_password(password, salt)
        user_id = uuid.uuid4().hex
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO users ("
                        "user_id, email, password_hash, salt, created_at"
                        ") VALUES (?, ?, ?, ?, ?)",
                        (user_id, email, password_hash, salt, now),
                    )
            except sqlite3.IntegrityError as exc:
                raise UserStoreError("Email already registered") from exc
        return {"user_id": user_id, "email": email, "created_at": now}

    def login(self, email: str, password: str) -> str:
        """Verify credentials and return an opaque bearer token."""
        email = email.strip().lower()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT user_id, password_hash, salt FROM users "
                    "WHERE email = ?",
                    (email,),
                ).fetchone()
                if row is None:
                    raise UserStoreError("Invalid email or password")
                expected = self._hash_password(password, row["salt"])
                if not hmac.compare_digest(expected, row["password_hash"]):
                    raise UserStoreError("Invalid email or password")
                return self._issue_token(conn, row["user_id"])

    def user_for_token(self, token: str) -> Optional[dict[str, Any]]:
        """Return the public user for a valid unexpired token, else None."""
        now = self._clock()
        token_hash = self._token_hash(token)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT u.user_id, u.email, u.created_at "
                    "FROM sessions s JOIN users u ON u.user_id = s.user_id "
                    "WHERE s.token_hash = ? AND s.expires_at > ?",
                    (token_hash, now),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "user_id": row["user_id"],
                    "email": row["email"],
                    "created_at": row["created_at"],
                }

    def revoke_token(self, token: str) -> None:
        token_hash = self._token_hash(token)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM sessions WHERE token_hash = ?",
                    (token_hash,),
                )

    def get_or_create_personal_user(
        self,
        user_id: str = "local",
        email: str = "local@resualign.local",
    ) -> dict[str, Any]:
        """Return the deterministic local personal user, creating it lazily."""
        now = self._clock()
        salt = secrets.token_hex(16)
        password_hash = self._hash_password(secrets.token_urlsafe(24), salt)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT user_id, email, created_at FROM users "
                    "WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                if row is not None:
                    return {
                        "user_id": row["user_id"],
                        "email": row["email"],
                        "created_at": row["created_at"],
                    }
                try:
                    conn.execute(
                        "INSERT INTO users ("
                        "user_id, email, password_hash, salt, created_at"
                        ") VALUES (?, ?, ?, ?, ?)",
                        (user_id, email, password_hash, salt, now),
                    )
                except sqlite3.IntegrityError:
                    row = conn.execute(
                        "SELECT user_id, email, created_at FROM users "
                        "WHERE user_id = ?",
                        (user_id,),
                    ).fetchone()
                    return {
                        "user_id": row["user_id"],
                        "email": row["email"],
                        "created_at": row["created_at"],
                    }
        return {"user_id": user_id, "email": email, "created_at": now}

    def _issue_token(self, conn: sqlite3.Connection, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (self._token_hash(token), user_id, now, now + self._token_ttl),
        )
        return token

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt.encode("utf-8"),
            n=2**14,
            r=8,
            p=1,
            dklen=32,
        )
        return derived.hex()

    @staticmethod
    def _validate_email(email: str) -> None:
        if "@" not in email or len(email) < 5:
            raise UserStoreError("A valid email is required")

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(
            _SCHEMA,
            cleanup=(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (self._clock(),),
            ),
        )


class MasterResumeStore(_SqliteStore):
    """Per-tenant master resume storage with immutable version history."""

    MIGRATIONS = (
        (
            1,
            "ALTER TABLE master_resumes "
            "ADD COLUMN latest_diagnosis_job_id TEXT",
        ),
        (
            2,
            "ALTER TABLE master_resumes "
            "ADD COLUMN latest_diagnosis_json TEXT",
        ),
        (
            3,
            "ALTER TABLE master_resumes "
            "ADD COLUMN latest_diagnosis_source_hash TEXT",
        ),
        # 4: 结构化档案（网申回填的数据源）。与 diagnosis 同款三件套：
        # JSON + 内容 sha（内容变更即过期）+ 抽取所用模型。
        (
            4,
            "ALTER TABLE master_resumes "
            "ADD COLUMN profile_json TEXT; "
            "ALTER TABLE master_resumes "
            "ADD COLUMN profile_source_sha256 TEXT; "
            "ALTER TABLE master_resumes "
            "ADD COLUMN profile_model TEXT",
        ),
    )

    def create_master_resume(
        self, tenant_id: str, title: str, content: str
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise UserStoreError("A resume title is required")
        if not content.strip():
            raise UserStoreError("Resume content cannot be empty")
        resume_id = uuid.uuid4().hex
        version_id = uuid.uuid4().hex
        now = self._clock()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO master_resumes ("
                    "resume_id, tenant_id, title, current_version, "
                    "created_at, updated_at, latest_diagnosis_job_id, "
                    "latest_diagnosis_json, latest_diagnosis_source_hash"
                    ") VALUES (?, ?, ?, 1, ?, ?, NULL, NULL, NULL)",
                    (resume_id, tenant_id, title, now, now),
                )
                conn.execute(
                    "INSERT INTO resume_versions ("
                    "version_id, resume_id, tenant_id, version, content, "
                    "created_at"
                    ") VALUES (?, ?, ?, 1, ?, ?)",
                    (version_id, resume_id, tenant_id, content, now),
                )
        return self.get_master_resume(tenant_id, resume_id)

    def get_master_resume(
        self, tenant_id: str, resume_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT resume_id, tenant_id, title, current_version, "
                    "created_at, updated_at, latest_diagnosis_job_id, "
                    "latest_diagnosis_json, latest_diagnosis_source_hash, "
                    "profile_json, profile_source_sha256, profile_model "
                    "FROM master_resumes "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                ).fetchone()
                if row is None:
                    return None
                version_rows = conn.execute(
                    "SELECT version, content, created_at FROM resume_versions "
                    "WHERE resume_id = ? AND tenant_id = ? "
                    "ORDER BY version ASC",
                    (resume_id, tenant_id),
                ).fetchall()
                versions = [
                    {
                        "version": row["version"],
                        "content": row["content"],
                        "created_at": row["created_at"],
                    }
                    for row in version_rows
                ]
                current = next(
                    (
                        v
                        for v in versions
                        if v["version"] == row["current_version"]
                    ),
                    None,
                )
                return {
                    "resume_id": row["resume_id"],
                    "title": row["title"],
                    "current_version": row["current_version"],
                    "content": current["content"] if current else "",
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "latest_diagnosis_job_id": row[
                        "latest_diagnosis_job_id"
                    ],
                    "latest_diagnosis": self._latest_diagnosis_for_row(
                        row, current["content"] if current else ""
                    ),
                    "profile": self._profile_for_row(
                        row, current["content"] if current else ""
                    ),
                    "versions": versions,
                }

    def list_master_resumes(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT resume_id, tenant_id, title, current_version, "
                    "created_at, updated_at, latest_diagnosis_job_id, "
                    "latest_diagnosis_json, latest_diagnosis_source_hash, "
                    "profile_json, profile_source_sha256, profile_model "
                    "FROM master_resumes "
                    "WHERE tenant_id = ? ORDER BY updated_at DESC",
                    (tenant_id,),
                ).fetchall()
                result = []
                for row in rows:
                    version_row = conn.execute(
                        "SELECT content FROM resume_versions "
                        "WHERE resume_id = ? AND tenant_id = ? AND version = ?",
                        (
                            row["resume_id"],
                            tenant_id,
                            row["current_version"],
                        ),
                    ).fetchone()
                    result.append(
                        {
                            "resume_id": row["resume_id"],
                            "title": row["title"],
                            "current_version": row["current_version"],
                            "content": (
                                version_row["content"] if version_row else ""
                            ),
                            "created_at": row["created_at"],
                            "updated_at": row["updated_at"],
                            "latest_diagnosis_job_id": row[
                                "latest_diagnosis_job_id"
                            ],
                            "latest_diagnosis": self._latest_diagnosis_for_row(
                                row,
                                version_row["content"] if version_row else "",
                            ),
                        }
                    )
                return result

    def update_master_resume(
        self, tenant_id: str, resume_id: str, content: str
    ) -> Optional[dict[str, Any]]:
        if not content.strip():
            raise UserStoreError("Resume content cannot be empty")
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT current_version FROM master_resumes "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                ).fetchone()
                if row is None:
                    return None
                max_row = conn.execute(
                    "SELECT MAX(version) AS max_version FROM resume_versions "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                ).fetchone()
                next_version = (max_row["max_version"] or 0) + 1
                version_id = uuid.uuid4().hex
                now = self._clock()
                conn.execute(
                    "INSERT INTO resume_versions ("
                    "version_id, resume_id, tenant_id, version, content, "
                    "created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        version_id,
                        resume_id,
                        tenant_id,
                        next_version,
                        content,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE master_resumes SET current_version = ?, "
                    "updated_at = ?, latest_diagnosis_job_id = NULL, "
                    "latest_diagnosis_json = NULL, "
                    "latest_diagnosis_source_hash = NULL "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (next_version, now, resume_id, tenant_id),
                )
        return self.get_master_resume(tenant_id, resume_id)

    def rollback_master_resume(
        self, tenant_id: str, resume_id: str, version: int
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                exists = conn.execute(
                    "SELECT 1 FROM resume_versions "
                    "WHERE resume_id = ? AND tenant_id = ? AND version = ?",
                    (resume_id, tenant_id, version),
                ).fetchone()
                if exists is None:
                    return None
                now = self._clock()
                conn.execute(
                    "UPDATE master_resumes SET current_version = ?, "
                    "updated_at = ?, latest_diagnosis_job_id = NULL, "
                    "latest_diagnosis_json = NULL, "
                    "latest_diagnosis_source_hash = NULL "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (version, now, resume_id, tenant_id),
                )
        return self.get_master_resume(tenant_id, resume_id)

    def set_latest_diagnosis_job(
        self, tenant_id: str, resume_id: str, job_id: str
    ) -> Optional[dict[str, Any]]:
        """Remember the newest diagnosis job for a master resume."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE master_resumes SET latest_diagnosis_job_id = ? "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (job_id, resume_id, tenant_id),
                )
                if cursor.rowcount == 0:
                    return None
        return self.get_master_resume(tenant_id, resume_id)

    def clear_latest_diagnosis_job(
        self, tenant_id: str, resume_id: str
    ) -> Optional[dict[str, Any]]:
        """Drop a diagnosis job reference whose analysis job no longer exists."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE master_resumes SET latest_diagnosis_job_id = NULL "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                )
                if cursor.rowcount == 0:
                    return None
        return self.get_master_resume(tenant_id, resume_id)

    def set_latest_diagnosis_snapshot(
        self,
        tenant_id: str,
        resume_id: str,
        diagnosis: dict[str, Any],
        source_hash: str,
    ) -> Optional[dict[str, Any]]:
        """Persist the latest successful diagnosis for a master resume."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE master_resumes SET latest_diagnosis_json = ?, "
                    "latest_diagnosis_source_hash = ? "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (
                        json.dumps(
                            diagnosis, ensure_ascii=False, separators=(",", ":")
                        ),
                        source_hash,
                        resume_id,
                        tenant_id,
                    ),
                )
                if cursor.rowcount == 0:
                    return None
        return self.get_master_resume(tenant_id, resume_id)

    def get_latest_diagnosis_snapshot(
        self, tenant_id: str, resume_id: str
    ) -> Optional[tuple[dict[str, Any], str]]:
        """Return (diagnosis, source_hash) when a snapshot exists."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT latest_diagnosis_json, "
                    "latest_diagnosis_source_hash FROM master_resumes "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                ).fetchone()
                if row is None or not row["latest_diagnosis_json"]:
                    return None
                try:
                    diagnosis = json.loads(row["latest_diagnosis_json"])
                except json.JSONDecodeError:
                    return None
                return diagnosis, row["latest_diagnosis_source_hash"] or ""

    def list_resume_diagnosis_refs(self) -> list[dict[str, Any]]:
        """Return every resume row for the startup snapshot backfill."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT r.resume_id, r.tenant_id, r.current_version, "
                    "r.latest_diagnosis_job_id, r.latest_diagnosis_json, "
                    "v.content FROM master_resumes r "
                    "JOIN resume_versions v ON v.resume_id = r.resume_id "
                    "AND v.version = r.current_version "
                    "WHERE r.latest_diagnosis_job_id IS NOT NULL"
                ).fetchall()
                return [
                    {
                        "resume_id": row["resume_id"],
                        "tenant_id": row["tenant_id"],
                        "latest_diagnosis_job_id": row[
                            "latest_diagnosis_job_id"
                        ],
                        "has_snapshot": bool(row["latest_diagnosis_json"]),
                        "content": row["content"] or "",
                    }
                    for row in rows
                ]

    def _profile_for_row(
        self, row: sqlite3.Row, content: str
    ) -> Optional[dict[str, Any]]:
        """Return the stored structured profile plus a staleness flag.

        ``stale`` 为 True 表示简历内容在抽取后发生过变化——网申回填消费前
        应提示重抽（与 diagnosis 的 source_hash 机制同款）。
        """
        import hashlib as _hashlib
        import json as _json

        if not row["profile_json"]:
            return None
        try:
            profile = _json.loads(row["profile_json"])
        except (TypeError, ValueError):
            return None
        sha = _hashlib.sha256((content or "").encode("utf-8")).hexdigest()
        return {
            "data": profile,
            "model": row["profile_model"],
            "stale": row["profile_source_sha256"] != sha,
        }

    def save_resume_profile(
        self,
        tenant_id: str,
        resume_id: str,
        profile: dict[str, Any],
        source_sha256: str,
        model: str,
    ) -> Optional[dict[str, Any]]:
        """Persist the structured profile for one master resume."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "UPDATE master_resumes SET profile_json = ?, "
                    "profile_source_sha256 = ?, profile_model = ?, "
                    "updated_at = ? "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (
                        json.dumps(profile, ensure_ascii=False),
                        source_sha256,
                        model,
                        time.time(),
                        resume_id,
                        tenant_id,
                    ),
                )
                if cursor.rowcount == 0:
                    return None
        return self.get_master_resume(tenant_id, resume_id)

    def _latest_diagnosis_for_row(
        self,
        row: sqlite3.Row,
        content: str,
    ) -> Optional[dict[str, Any]]:
        """Return the persisted diagnosis only when content still matches."""
        raw = row["latest_diagnosis_json"] if "latest_diagnosis_json" in row.keys() else None
        source_hash = (
            row["latest_diagnosis_source_hash"]
            if "latest_diagnosis_source_hash" in row.keys()
            else None
        )
        if not raw or not source_hash:
            return None
        if source_hash != hashlib.sha256((content or "").encode("utf-8")).hexdigest():
            return None
        try:
            diagnosis = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return diagnosis if isinstance(diagnosis, dict) else None

    def delete_master_resume(
        self, tenant_id: str, resume_id: str
    ) -> bool:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM resume_versions "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                )
                deleted = conn.execute(
                    "DELETE FROM master_resumes "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (resume_id, tenant_id),
                )
                return deleted.rowcount > 0 or cursor.rowcount > 0

    def _clock(self) -> float:
        return time.time()

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_MASTER_RESUME_SCHEMA)


class ApplicationStore(_SqliteStore):
    """Dormant per-tenant application records with pinned resume snapshots.

    ADR-0027: the job library is the single source for delivery-loop state.
    This store and its routes are retained only for legacy data compatibility
    until a dedicated cleanup ticket removes them.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        clock: callable = time.time,
    ) -> None:
        super().__init__(db_path)
        self._clock = clock

    def create_application(
        self,
        tenant_id: str,
        title: str,
        master_resume_id: str,
        jd_text: str | None = None,
        jd_url: str | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise UserStoreError("An application title is required")
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                resume = conn.execute(
                    "SELECT current_version FROM master_resumes "
                    "WHERE resume_id = ? AND tenant_id = ?",
                    (master_resume_id, tenant_id),
                ).fetchone()
                if resume is None:
                    raise UserStoreError("Master resume not found")
                version_row = conn.execute(
                    "SELECT content FROM resume_versions "
                    "WHERE resume_id = ? AND tenant_id = ? AND version = ?",
                    (master_resume_id, tenant_id, resume["current_version"]),
                ).fetchone()
                snapshot = version_row["content"] if version_row else ""
                application_id = uuid.uuid4().hex
                now = self._clock()
                conn.execute(
                    "INSERT INTO applications ("
                    "application_id, tenant_id, title, master_resume_id, "
                    "resume_version, resume_snapshot, jd_text, jd_url, status, "
                    "latest_job_id, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', NULL, ?, ?)",
                    (
                        application_id,
                        tenant_id,
                        title,
                        master_resume_id,
                        resume["current_version"],
                        snapshot,
                        jd_text,
                        jd_url,
                        now,
                        now,
                    ),
                )
        return self.get_application(tenant_id, application_id)

    def get_application(
        self, tenant_id: str, application_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT application_id, tenant_id, title, "
                    "master_resume_id, resume_version, resume_snapshot, "
                    "jd_text, jd_url, status, latest_job_id, created_at, "
                    "updated_at FROM applications "
                    "WHERE application_id = ? AND tenant_id = ?",
                    (application_id, tenant_id),
                ).fetchone()
                if row is None:
                    return None
                return self._row_to_application(row)

    def list_applications(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT application_id, tenant_id, title, "
                    "master_resume_id, resume_version, resume_snapshot, "
                    "jd_text, jd_url, status, latest_job_id, created_at, "
                    "updated_at FROM applications "
                    "WHERE tenant_id = ? ORDER BY updated_at DESC",
                    (tenant_id,),
                ).fetchall()
                return [self._row_to_application(row) for row in rows]

    def update_application(
        self,
        tenant_id: str,
        application_id: str,
        title: str | None = None,
        jd_text: str | None = None,
        jd_url: str | None = None,
        status: str | None = None,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT 1 FROM applications "
                    "WHERE application_id = ? AND tenant_id = ?",
                    (application_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                sets = ["updated_at = ?"]
                values: list[Any] = [self._clock()]
                if title is not None:
                    if not title.strip():
                        raise UserStoreError("An application title is required")
                    sets.append("title = ?")
                    values.append(title.strip())
                if jd_text is not None:
                    sets.append("jd_text = ?")
                    values.append(jd_text)
                if jd_url is not None:
                    sets.append("jd_url = ?")
                    values.append(jd_url)
                if status is not None:
                    if not str(status).strip():
                        raise UserStoreError(
                            "An application status is required"
                        )
                    sets.append("status = ?")
                    values.append(str(status).strip())
                values.extend([application_id, tenant_id])
                conn.execute(
                    f"UPDATE applications SET {', '.join(sets)} "
                    "WHERE application_id = ? AND tenant_id = ?",
                    values,
                )
        return self.get_application(tenant_id, application_id)

    def set_application_job(
        self,
        tenant_id: str,
        application_id: str,
        job_id: str,
        status: str,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT 1 FROM applications "
                    "WHERE application_id = ? AND tenant_id = ?",
                    (application_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                conn.execute(
                    "UPDATE applications SET latest_job_id = ?, status = ?, "
                    "updated_at = ? "
                    "WHERE application_id = ? AND tenant_id = ?",
                    (job_id, status, self._clock(), application_id, tenant_id),
                )
        return self.get_application(tenant_id, application_id)

    def delete_application(
        self, tenant_id: str, application_id: str
    ) -> bool:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                deleted = conn.execute(
                    "DELETE FROM applications "
                    "WHERE application_id = ? AND tenant_id = ?",
                    (application_id, tenant_id),
                )
                return deleted.rowcount > 0

    @staticmethod
    def _row_to_application(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "application_id": row["application_id"],
            "title": row["title"],
            "master_resume_id": row["master_resume_id"],
            "resume_version": row["resume_version"],
            "resume_snapshot": row["resume_snapshot"],
            "jd_text": row["jd_text"],
            "jd_url": row["jd_url"],
            "status": row["status"],
            "status_canonical": application_status_canonical(row["status"]),
            "latest_job_id": row["latest_job_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(
            _MASTER_RESUME_SCHEMA + _APPLICATION_SCHEMA
        )


_APPLICATION_TO_JOB_STATUS = {
    "draft": "未投递",
    "applied": "已投递",
    "interview": "面试中",
    "offer": "已拿Offer",
    "rejected": "放弃",
    "withdrawn": "放弃",
}

_APPLIED_CANONICAL_STATES = ("applied", "interview", "offer")


def _application_applied_at(application: dict[str, Any]) -> str | None:
    """Format an application's updated_at as the job timeline ISO string."""
    updated_at = application.get("updated_at")
    if not updated_at:
        return None
    try:
        return time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(updated_at))
        )
    except (TypeError, ValueError):
        return None


def merge_applications_into_jobs(
    application_store: ApplicationStore,
    job_store: JobLibraryStore,
    tenant_id: str,
) -> tuple[int, int]:
    """Migrate per-application pipeline state onto library jobs (G6).

    For every application of the tenant, locate the matching library job by
    normalized JD URL or JD-text dedupe key. When found and the job is still
    ``未投递``, copy the application status (and applied_at for applied
    states) onto the job. Applications without a matching library job, or
    whose job already moved past the initial state, are skipped.

    Returns ``(merged, skipped)``. Idempotent: re-running only merges
    applications whose job is still in the initial state.
    """
    merged = 0
    skipped = 0
    for application in application_store.list_applications(tenant_id):
        target = job_store.find_job_by_application_source(
            tenant_id,
            jd_url=application.get("jd_url"),
            jd_text=application.get("jd_text"),
        )
        if target is None:
            skipped += 1
            continue
        canonical = application_status_canonical(
            application.get("status") or ""
        )
        status_label = _APPLICATION_TO_JOB_STATUS.get(canonical)
        if status_label is None or canonical_status(target["status"]) != "draft":
            skipped += 1
            continue
        updates: dict[str, Any] = {"status": status_label}
        if canonical in _APPLIED_CANONICAL_STATES:
            applied_at = _application_applied_at(application)
            if applied_at is not None:
                updates["applied_at"] = applied_at
        job_store.update_job(tenant_id, target["job_id"], **updates)
        merged += 1
    return merged, skipped


# JobLibraryStore is defined in job_library.py but re-exported here so callers
# can treat the workspace module as the shared store namespace.
from .job_library import JobLibraryStore, canonical_status  # noqa: E402, F401
