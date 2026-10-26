"""SQLite-backed vector index for resume x job ranking (ADR-0065).

Storage only: no embedding model, no HTTP, no gate. Vectors are float32
little-endian blobs, L2-normalised by the writer; search is a brute-force
cosine scan. ADR-0065 decision 7 deliberately stops at 5k vectors: above that
an ANN index gets its own ADR instead of a new dependency here.

Tables match migration 47 in job_library; they are also created lazily here so
benchmarks and tests can use the index without booting the API.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from .store_base import _SqliteStore

VECTOR_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS job_embeddings (
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    text_sha256 TEXT NOT NULL,
    skills_json TEXT NOT NULL DEFAULT '[]',
    vec BLOB NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, job_id, model)
);
CREATE INDEX IF NOT EXISTS idx_job_embeddings_model
    ON job_embeddings(tenant_id, model);

CREATE TABLE IF NOT EXISTS resume_embeddings (
    tenant_id TEXT NOT NULL,
    resume_id TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    text_sha256 TEXT NOT NULL,
    vec BLOB NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, resume_id, model)
);
CREATE INDEX IF NOT EXISTS idx_resume_embeddings_model
    ON resume_embeddings(tenant_id, model);
"""


class VectorIndex(_SqliteStore):
    """Tenant-scoped float32 vector store on the shared jobs database."""

    SCHEMA_SQL = VECTOR_TABLES_SQL

    # ADR-0065 decision 7: above this, evaluate an ANN index in a new ADR.
    MAX_VECTORS = 5000

    def __init__(self, db_path: str | Path | None = None) -> None:
        super().__init__(db_path)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def text_sha256(text: str | None) -> str:
        return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()

    @staticmethod
    def l2_normalize(vector: Sequence[float]) -> list[float]:
        norm = math.sqrt(sum(float(value) * float(value) for value in vector))
        if norm <= 0.0:
            raise ValueError("cannot store a zero vector")
        return [float(value) / norm for value in vector]

    @staticmethod
    def _pack(vector: Sequence[float]) -> bytes:
        return struct.pack("<%df" % len(vector), *[float(v) for v in vector])

    @staticmethod
    def _unpack(blob: bytes) -> list[float]:
        count = len(blob) // 4
        return list(struct.unpack("<%df" % count, blob))

    def ensure_ready(self) -> None:
        """Create the tables if this is the first user of the database."""
        self._ensure_initialized()

    # -- writes ----------------------------------------------------------
    def upsert_job(
        self,
        tenant_id: str,
        job_id: str,
        vector: Sequence[float],
        *,
        model: str,
        text_sha256: str | None = None,
        skills: Sequence[str] | None = None,
    ) -> bool:
        """Insert or update one job vector; returns False when sha is unchanged.

        skills = the JD's own canonical skill names (resume-independent), stored
        so the keyword co-recall can run as a set intersection instead of
        re-scanning every JD with regex on each request.
        """
        return self._upsert(
            "job_embeddings",
            "job_id",
            tenant_id,
            job_id,
            vector,
            model,
            text_sha256,
            skills=skills,
        )

    def upsert_resume(
        self,
        tenant_id: str,
        resume_id: str,
        vector: Sequence[float],
        *,
        model: str,
        text_sha256: str | None = None,
    ) -> bool:
        return self._upsert(
            "resume_embeddings",
            "resume_id",
            tenant_id,
            resume_id,
            vector,
            model,
            text_sha256,
        )

    def _upsert(
        self,
        table: str,
        id_column: str,
        tenant_id: str,
        row_id: str,
        vector: Sequence[float],
        model: str,
        text_sha256: str | None,
        skills: Sequence[str] | None = None,
    ) -> bool:
        if not tenant_id or not row_id:
            raise ValueError("tenant_id and id are required")
        if not model:
            raise ValueError("model is required")
        normalized = self.l2_normalize(vector)
        sha = text_sha256 if text_sha256 is not None else ""
        self.ensure_ready()
        with self._lock, self._connect() as conn:
            if sha:
                row = conn.execute(
                    "SELECT text_sha256 FROM " + table + " WHERE tenant_id = ? AND "
                    + id_column + " = ? AND model = ?",
                    (tenant_id, row_id, model),
                ).fetchone()
                if row is not None and row["text_sha256"] == sha:
                    return False
            if table == "job_embeddings":
                skills_json = json.dumps(list(skills or []), ensure_ascii=False)
                conn.execute(
                    "INSERT INTO " + table + " (tenant_id, " + id_column + ", model, "
                    "dim, text_sha256, skills_json, vec, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(tenant_id, " + id_column + ", model) DO UPDATE SET "
                    "dim = excluded.dim, text_sha256 = excluded.text_sha256, "
                    "skills_json = excluded.skills_json, "
                    "vec = excluded.vec, created_at = excluded.created_at",
                    (
                        tenant_id,
                        row_id,
                        model,
                        len(normalized),
                        sha,
                        skills_json,
                        self._pack(normalized),
                        time.time(),
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO " + table + " (tenant_id, " + id_column + ", model, "
                    "dim, text_sha256, vec, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(tenant_id, " + id_column + ", model) DO UPDATE SET "
                    "dim = excluded.dim, text_sha256 = excluded.text_sha256, "
                    "vec = excluded.vec, created_at = excluded.created_at",
                    (
                        tenant_id,
                        row_id,
                        model,
                        len(normalized),
                        sha,
                        self._pack(normalized),
                        time.time(),
                    ),
                )
        return True

    def delete_job(self, tenant_id: str, job_id: str) -> None:
        self._delete("job_embeddings", "job_id", tenant_id, job_id)

    def delete_resume(self, tenant_id: str, resume_id: str) -> None:
        self._delete("resume_embeddings", "resume_id", tenant_id, resume_id)

    def _delete(self, table: str, id_column: str, tenant_id: str, row_id: str) -> None:
        self.ensure_ready()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM " + table + " WHERE tenant_id = ? AND "
                + id_column + " = ?",
                (tenant_id, row_id),
            )

    def clear(self, tenant_id: str) -> int:
        """Delete every vector of one tenant; returns rows removed."""
        self.ensure_ready()
        removed = 0
        with self._connect() as conn:
            for table in ("job_embeddings", "resume_embeddings"):
                cursor = conn.execute(
                    "DELETE FROM " + table + " WHERE tenant_id = ?", (tenant_id,)
                )
                removed += cursor.rowcount
        return removed

    # -- reads -----------------------------------------------------------
    def get_job(
        self, tenant_id: str, job_id: str, *, model: str | None = None
    ) -> list[float] | None:
        return self._get("job_embeddings", "job_id", tenant_id, job_id, model)

    def get_resume(
        self, tenant_id: str, resume_id: str, *, model: str | None = None
    ) -> list[float] | None:
        return self._get("resume_embeddings", "resume_id", tenant_id, resume_id, model)

    def _get(
        self,
        table: str,
        id_column: str,
        tenant_id: str,
        row_id: str,
        model: str | None,
    ) -> list[float] | None:
        self.ensure_ready()
        sql = (
            "SELECT vec FROM " + table + " WHERE tenant_id = ? AND "
            + id_column + " = ?"
        )
        params: list[Any] = [tenant_id, row_id]
        if model:
            sql += " AND model = ?"
            params.append(model)
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return None if row is None else self._unpack(row["vec"])

    def search_jobs(
        self,
        tenant_id: str,
        vector: Sequence[float],
        *,
        model: str | None = None,
        k: int = 10,
        job_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float]]:
        return self._search(
            "job_embeddings", "job_id", tenant_id, vector, model, k, job_ids
        )

    def search_resumes(
        self,
        tenant_id: str,
        vector: Sequence[float],
        *,
        model: str | None = None,
        k: int = 3,
        resume_ids: Iterable[str] | None = None,
    ) -> list[tuple[str, float]]:
        return self._search(
            "resume_embeddings",
            "resume_id",
            tenant_id,
            vector,
            model,
            k,
            resume_ids,
        )

    def _search(
        self,
        table: str,
        id_column: str,
        tenant_id: str,
        vector: Sequence[float],
        model: str | None,
        k: int,
        ids: Iterable[str] | None,
    ) -> list[tuple[str, float]]:
        if k <= 0:
            return []
        query = self.l2_normalize(vector)
        dim = len(query)
        self.ensure_ready()
        sql = (
            "SELECT " + id_column + " AS row_id, vec FROM " + table
            + " WHERE tenant_id = ? AND dim = ?"
        )
        params: list[Any] = [tenant_id, dim]
        if model:
            sql += " AND model = ?"
            params.append(model)
        if ids is not None:
            id_list = list(ids)
            if not id_list:
                return []
            sql += " AND " + id_column + " IN (" + ",".join("?" for _ in id_list) + ")"
            params.extend(id_list)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        scored = [
            (
                row["row_id"],
                sum(a * b for a, b in zip(query, self._unpack(row["vec"]))),
            )
            for row in rows
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:k]

    def job_shas(self, tenant_id: str, *, model: str) -> dict[str, str]:
        """Return job_id -> text_sha256 for one model (incremental rebuild)."""
        self.ensure_ready()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id, text_sha256 FROM job_embeddings "
                "WHERE tenant_id = ? AND model = ?",
                (tenant_id, model),
            ).fetchall()
        return {row["job_id"]: row["text_sha256"] for row in rows}

    def job_skills(self, tenant_id: str, *, model: str) -> dict[str, list[str]]:
        """job_id -> JD skill names captured at index time (fusion input)."""
        self.ensure_ready()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id, skills_json FROM job_embeddings "
                "WHERE tenant_id = ? AND model = ?",
                (tenant_id, model),
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            try:
                parsed = json.loads(row["skills_json"] or "[]")
            except ValueError:
                parsed = []
            result[row["job_id"]] = [str(item) for item in parsed] if isinstance(parsed, list) else []
        return result

    def resume_sha(self, tenant_id: str, resume_id: str, *, model: str) -> str | None:
        self.ensure_ready()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT text_sha256 FROM resume_embeddings WHERE tenant_id = ? "
                "AND resume_id = ? AND model = ?",
                (tenant_id, resume_id, model),
            ).fetchone()
        return None if row is None else row["text_sha256"]

    def stats(self, tenant_id: str, *, model: str | None = None) -> dict[str, Any]:
        """Counts plus a needs_rebuild flag for model/dim drift."""
        self.ensure_ready()
        with self._connect() as conn:
            job_rows = conn.execute(
                "SELECT model, dim, COUNT(*) AS n FROM job_embeddings "
                "WHERE tenant_id = ? GROUP BY model, dim",
                (tenant_id,),
            ).fetchall()
            resume_rows = conn.execute(
                "SELECT model, dim, COUNT(*) AS n FROM resume_embeddings "
                "WHERE tenant_id = ? GROUP BY model, dim",
                (tenant_id,),
            ).fetchall()

        def summarise(rows: list[sqlite3.Row]) -> dict[str, Any]:
            return {
                "count": sum(row["n"] for row in rows),
                "models": sorted({row["model"] for row in rows}),
                "dims": sorted({row["dim"] for row in rows}),
            }

        jobs = summarise(job_rows)
        resumes = summarise(resume_rows)
        models = set(jobs["models"]) | set(resumes["models"])
        dims = set(jobs["dims"]) | set(resumes["dims"])
        return {
            "jobs": jobs,
            "resumes": resumes,
            "model": model,
            "needs_rebuild": len(models) > 1 or len(dims) > 1,
            "over_limit": jobs["count"] > self.MAX_VECTORS,
        }

    def missing_job_ids(
        self, tenant_id: str, job_ids: Sequence[str], *, model: str
    ) -> list[str]:
        """Job ids without a vector for this model (used by the index builder)."""
        if not job_ids:
            return []
        self.ensure_ready()
        present: set[str] = set()
        with self._connect() as conn:
            for start in range(0, len(job_ids), 500):
                chunk = list(job_ids[start : start + 500])
                rows = conn.execute(
                    "SELECT job_id FROM job_embeddings WHERE tenant_id = ? AND "
                    "model = ? AND job_id IN (" + ",".join("?" for _ in chunk) + ")",
                    (tenant_id, model, *chunk),
                ).fetchall()
                present.update(row["job_id"] for row in rows)
        return [job_id for job_id in job_ids if job_id not in present]
