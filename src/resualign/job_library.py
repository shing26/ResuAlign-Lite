"""Tenant-scoped Job Library store for the workbench."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
import time
import uuid
from typing import Any, Optional, Sequence

from .store_base import UserStoreError, _SqliteStore

JOB_FUNCTIONS = (
    "后端",
    "前端",
    "算法",
    "数据",
    "测试",
    "运维",
    "产品",
    "设计",
    "运营",
    "销售",
    "其他",
)

SENIORITIES = (
    "初级",
    "中级",
    "高级",
    "资深",
    "未知",
)

JOB_STATUSES = (
    "未投递",
    "已投递",
    "面试中",
    "已拿Offer",
    "放弃",
)

TAILOR_GRANULARITIES = ("fine", "medium", "coarse")
TAILOR_FOCUSES = ("balanced", "quantified", "skills")


def _effective_choices(
    base: Sequence[str],
    extra: Sequence[str] | None,
) -> list[str]:
    """Merge tenant vocabulary into the built-in controlled choices."""
    choices = list(base)
    for choice in extra or []:
        choice = str(choice).strip()
        if choice and choice not in choices:
            choices.append(choice)
    return choices


_JOB_LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS library_jobs (
    job_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    jd_text TEXT NOT NULL,
    company TEXT,
    location TEXT,
    salary_min REAL,
    salary_max REAL,
    salary_currency TEXT NOT NULL DEFAULT 'CNY',
    source_type TEXT NOT NULL DEFAULT 'paste',
    source_url TEXT,
    job_function TEXT,
    seniority TEXT,
    tech_tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT '未投递',
    classification_pending INTEGER NOT NULL DEFAULT 0,
    final_draft TEXT,
    final_draft_updated_at REAL,
    final_draft_version INTEGER NOT NULL DEFAULT 0,
    posting_date TEXT,
    workbench_job_id TEXT,
    workbench_resume_id TEXT,
    tailor_granularity TEXT,
    tailor_focus TEXT,
    custom_prompt TEXT,
    dedupe_key TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(tenant_id, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_library_jobs_tenant
    ON library_jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_library_jobs_function
    ON library_jobs(job_function);
CREATE INDEX IF NOT EXISTS idx_library_jobs_status
    ON library_jobs(status);
"""


def _normalize_source_url(url: str) -> str:
    """Return a stable normalization of a source URL for dedupe."""
    value = (url or "").strip()
    value = re.sub(r"[?#].*$", "", value).rstrip("/")
    return value.lower()


def _normalize_jd_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _text_dedupe_key(text: str) -> str:
    normalized = _normalize_jd_text(text)
    return "text:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class JobLibraryStore(_SqliteStore):
    """SQLite-backed, tenant-scoped storage for job postings."""

    def create_job(
        self,
        tenant_id: str,
        title: str | None = None,
        jd_text: str | None = None,
        company: str | None = None,
        location: str | None = None,
        salary_min: float | None = None,
        salary_max: float | None = None,
        salary_currency: str = "CNY",
        source_type: str = "paste",
        source_url: str | None = None,
        job_function: str | None = None,
        seniority: str | None = None,
        tech_tags: list[str] | None = None,
        status: str = "未投递",
        classification_pending: int = 0,
        final_draft: str | None = None,
        final_draft_updated_at: float | None = None,
        final_draft_version: int | None = None,
        posting_date: str | None = None,
        allowed_job_functions: Sequence[str] | None = None,
        allowed_seniorities: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Create one library job, rejecting tenant-scoped duplicates."""
        text = (jd_text or "").strip()
        if not text:
            raise UserStoreError("Job description text is required")
        functions = _effective_choices(JOB_FUNCTIONS, allowed_job_functions)
        seniorities = _effective_choices(SENIORITIES, allowed_seniorities)
        if job_function is not None and job_function not in functions:
            raise UserStoreError(f"Invalid job_function: {job_function}")
        if seniority is not None and seniority not in seniorities:
            raise UserStoreError(f"Invalid seniority: {seniority}")
        if status not in JOB_STATUSES:
            raise UserStoreError(f"Invalid status: {status}")
        if classification_pending not in (0, 1):
            raise UserStoreError(
                "classification_pending must be 0 or 1"
            )
        if final_draft is not None and not final_draft.strip():
            raise UserStoreError("Final draft cannot be empty")
        if final_draft is not None:
            if final_draft_updated_at is None:
                final_draft_updated_at = time.time()
            if final_draft_version is None:
                final_draft_version = 1
        else:
            final_draft_version = 0

        normalized_url = (
            _normalize_source_url(source_url)
            if source_type == "url" and source_url
            else ""
        )
        dedupe_key = (
            "url:" + normalized_url
            if normalized_url
            else _text_dedupe_key(text)
        )
        job_id = uuid.uuid4().hex
        now = time.time()
        tags = self._normalize_tags(tech_tags)
        with self._lock:
            self._ensure_initialized()
            try:
                with self._connect() as conn:
                    conn.execute(
                        "INSERT INTO library_jobs ("
                        "job_id, tenant_id, title, jd_text, company, "
                        "location, "
                        "salary_min, salary_max, salary_currency, "
                        "source_type, "
                        "source_url, job_function, seniority, tech_tags, "
                        "status, "
                        "classification_pending, final_draft, "
                        "final_draft_updated_at, final_draft_version, "
                        "posting_date, dedupe_key, created_at, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            job_id,
                            tenant_id,
                            (title or "未命名岗位").strip() or "未命名岗位",
                            text,
                            company,
                            location,
                            salary_min,
                            salary_max,
                            salary_currency or "CNY",
                            source_type,
                            source_url,
                            job_function,
                            seniority,
                            json.dumps(tags, ensure_ascii=False),
                            status,
                            classification_pending,
                            final_draft,
                            final_draft_updated_at,
                            final_draft_version,
                            posting_date,
                            dedupe_key,
                            now,
                            now,
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise UserStoreError("Duplicate job already exists") from exc
        return self.get_job(tenant_id, job_id)

    def get_job(
        self, tenant_id: str, job_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                return self._row_to_job(row) if row else None

    def list_jobs(
        self,
        tenant_id: str,
        job_function: str | None = None,
        seniority: str | None = None,
        status: str | None = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions = ["tenant_id = ?"]
        values: list[Any] = [tenant_id]
        if job_function:
            conditions.append("job_function = ?")
            values.append(job_function)
        if seniority:
            conditions.append("seniority = ?")
            values.append(seniority)
        if status:
            conditions.append("status = ?")
            values.append(status)
        if search and search.strip():
            conditions.append(
                "(title LIKE ? OR company LIKE ? OR location LIKE ? "
                "OR jd_text LIKE ?)"
            )
            pattern = f"%{search.strip()}%"
            values.extend([pattern, pattern, pattern, pattern])
        sql = (
            "SELECT * FROM library_jobs WHERE "
            + " AND ".join(conditions)
            + " ORDER BY updated_at DESC"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(sql, values).fetchall()
                return [self._row_to_job(row) for row in rows]

    def update_job(
        self,
        tenant_id: str,
        job_id: str,
        title: str | None = None,
        jd_text: str | None = None,
        company: str | None = None,
        location: str | None = None,
        salary_min: float | None = None,
        salary_max: float | None = None,
        salary_currency: str | None = None,
        source_type: str | None = None,
        source_url: str | None = None,
        job_function: str | None = None,
        seniority: str | None = None,
        tech_tags: list[str] | None = None,
        status: str | None = None,
        classification_pending: int | None = None,
        final_draft: str | None = None,
        final_draft_updated_at: float | None = None,
        final_draft_version: int | None = None,
        posting_date: str | None = None,
        workbench_job_id: str | None = None,
        workbench_resume_id: str | None = None,
        tailor_granularity: str | None = None,
        tailor_focus: str | None = None,
        custom_prompt: str | None = None,
        allowed_job_functions: Sequence[str] | None = None,
        allowed_seniorities: Sequence[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        """Update editable fields. None-valued fields are left unchanged."""
        functions = _effective_choices(JOB_FUNCTIONS, allowed_job_functions)
        seniorities = _effective_choices(SENIORITIES, allowed_seniorities)
        if job_function is not None and job_function not in functions:
            raise UserStoreError(f"Invalid job_function: {job_function}")
        if seniority is not None and seniority not in seniorities:
            raise UserStoreError(f"Invalid seniority: {seniority}")
        if status is not None and status not in JOB_STATUSES:
            raise UserStoreError(f"Invalid status: {status}")
        if (
            classification_pending is not None
            and classification_pending not in (0, 1)
        ):
            raise UserStoreError(
                "classification_pending must be 0 or 1"
            )
        if final_draft is not None and not final_draft.strip():
            raise UserStoreError("Final draft cannot be empty")
        if (
            tailor_granularity is not None
            and tailor_granularity not in TAILOR_GRANULARITIES
        ):
            raise UserStoreError(
                f"Invalid tailor_granularity: {tailor_granularity}"
            )
        if tailor_focus is not None and tailor_focus not in TAILOR_FOCUSES:
            raise UserStoreError(f"Invalid tailor_focus: {tailor_focus}")
        if custom_prompt is not None:
            custom_prompt = custom_prompt.strip()
        if jd_text is not None and not jd_text.strip():
            raise UserStoreError("Job description text cannot be empty")

        sets = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if title is not None:
            sets.append("title = ?")
            values.append(title.strip() or "未命名岗位")
        if jd_text is not None:
            sets.append("jd_text = ?")
            values.append(jd_text.strip())
        if company is not None:
            sets.append("company = ?")
            values.append(company)
        if location is not None:
            sets.append("location = ?")
            values.append(location)
        if salary_min is not None:
            sets.append("salary_min = ?")
            values.append(salary_min)
        if salary_max is not None:
            sets.append("salary_max = ?")
            values.append(salary_max)
        if salary_currency is not None:
            sets.append("salary_currency = ?")
            values.append(salary_currency)
        if source_type is not None:
            sets.append("source_type = ?")
            values.append(source_type)
        if source_url is not None:
            sets.append("source_url = ?")
            values.append(source_url)
        if job_function is not None:
            sets.append("job_function = ?")
            values.append(job_function)
        if seniority is not None:
            sets.append("seniority = ?")
            values.append(seniority)
        if tech_tags is not None:
            sets.append("tech_tags = ?")
            values.append(
                json.dumps(self._normalize_tags(tech_tags), ensure_ascii=False)
            )
        if status is not None:
            sets.append("status = ?")
            values.append(status)
        if classification_pending is not None:
            sets.append("classification_pending = ?")
            values.append(classification_pending)
        if final_draft is not None:
            sets.append("final_draft = ?")
            values.append(final_draft)
        if final_draft_updated_at is not None:
            sets.append("final_draft_updated_at = ?")
            values.append(final_draft_updated_at)
        if final_draft_version is not None:
            sets.append("final_draft_version = ?")
            values.append(final_draft_version)
        if posting_date is not None:
            sets.append("posting_date = ?")
            values.append(posting_date)
        if workbench_job_id is not None:
            sets.append("workbench_job_id = ?")
            values.append(workbench_job_id)
        if workbench_resume_id is not None:
            sets.append("workbench_resume_id = ?")
            values.append(workbench_resume_id)
        if tailor_granularity is not None:
            sets.append("tailor_granularity = ?")
            values.append(tailor_granularity)
        if tailor_focus is not None:
            sets.append("tailor_focus = ?")
            values.append(tailor_focus)
        if custom_prompt is not None:
            sets.append("custom_prompt = ?")
            values.append(custom_prompt)
        recompute_dedupe = (
            jd_text is not None
            or source_type is not None
            or source_url is not None
        )

        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT jd_text, source_type, source_url "
                    "FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                if recompute_dedupe:
                    effective_text = (
                        jd_text.strip()
                        if jd_text is not None
                        else current["jd_text"]
                    )
                    effective_type = (
                        source_type
                        if source_type is not None
                        else current["source_type"]
                    )
                    effective_url = (
                        source_url
                        if source_url is not None
                        else current["source_url"]
                    )
                    normalized_url = (
                        _normalize_source_url(effective_url)
                        if effective_type == "url" and effective_url
                        else ""
                    )
                    dedupe_key = (
                        "url:" + normalized_url
                        if normalized_url
                        else _text_dedupe_key(effective_text)
                    )
                    sets.append("dedupe_key = ?")
                    values.append(dedupe_key)
                values.extend([job_id, tenant_id])
                try:
                    cursor = conn.execute(
                        f"UPDATE library_jobs SET {', '.join(sets)} "
                        "WHERE job_id = ? AND tenant_id = ?",
                        values,
                    )
                except sqlite3.IntegrityError as exc:
                    raise UserStoreError(
                        "Duplicate job already exists"
                    ) from exc
                if cursor.rowcount == 0:
                    return None
        return self.get_job(tenant_id, job_id)

    def save_final_draft(
        self,
        tenant_id: str,
        job_id: str,
        draft: str,
    ) -> Optional[dict[str, Any]]:
        """Persist a job's final draft and increment its saved version."""
        if not draft or not draft.strip():
            raise UserStoreError("Final draft cannot be empty")
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT final_draft_version FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                version = int(current["final_draft_version"] or 0) + 1
                now = time.time()
                conn.execute(
                    "UPDATE library_jobs SET final_draft = ?, "
                    "final_draft_updated_at = ?, final_draft_version = ?, "
                    "updated_at = ? "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (draft, now, version, now, job_id, tenant_id),
                )
        return {
            "draft": draft,
            "version": version,
            "updated_at": now,
        }

    def delete_job(self, tenant_id: str, job_id: str) -> bool:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                )
                return cursor.rowcount > 0

    def salary_median(
        self, tenant_id: str, job_function: str | None = None
    ) -> Optional[float]:
        """Return the median salary_min for the tenant's jobs, or None.

        When no function is given, the library's dominant job function is
        used as the default reference segment.
        """
        conditions = [
            "tenant_id = ?",
            "salary_min IS NOT NULL",
        ]
        values: list[Any] = [tenant_id]
        resolved_function = job_function
        if resolved_function is None:
            resolved_function = self._dominant_function(
                tenant_id, values
            )
        if resolved_function:
            conditions.append("job_function = ?")
            values.append(resolved_function)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT salary_min FROM library_jobs WHERE "
                    + " AND ".join(conditions),
                    values,
                ).fetchall()
        salaries = [float(row["salary_min"]) for row in rows]
        if not salaries:
            return None
        return float(statistics.median(salaries))

    def _dominant_function(
        self, tenant_id: str, values: list[Any]
    ) -> Optional[str]:
        """Return the most common non-null job function, or None."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_function, COUNT(*) AS count FROM library_jobs "
                    "WHERE tenant_id = ? AND salary_min IS NOT NULL "
                    "AND job_function IS NOT NULL "
                    "GROUP BY job_function ORDER BY count DESC, "
                    "MIN(created_at) ASC LIMIT 1",
                    values,
                ).fetchone()
                return rows["job_function"] if rows else None

    @staticmethod
    def _normalize_tags(tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        seen: list[str] = []
        for tag in tags:
            value = str(tag).strip()
            if value and value not in seen:
                seen.append(value)
        return seen

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
        tags = json.loads(row["tech_tags"] or "[]")
        return {
            "job_id": row["job_id"],
            "tenant_id": row["tenant_id"],
            "title": row["title"],
            "jd_text": row["jd_text"],
            "company": row["company"],
            "location": row["location"],
            "salary_min": row["salary_min"],
            "salary_max": row["salary_max"],
            "salary_currency": row["salary_currency"],
            "source_type": row["source_type"],
            "source_url": row["source_url"],
            "job_function": row["job_function"],
            "seniority": row["seniority"],
            "tech_tags": tags,
            "status": row["status"],
            "classification_pending": row["classification_pending"],
            "final_draft": row["final_draft"],
            "final_draft_updated_at": row["final_draft_updated_at"],
            "final_draft_version": row["final_draft_version"],
            "posting_date": row["posting_date"],
            "workbench_job_id": row["workbench_job_id"],
            "workbench_resume_id": row["workbench_resume_id"],
            "tailor_granularity": row["tailor_granularity"],
            "tailor_focus": row["tailor_focus"],
            "custom_prompt": row["custom_prompt"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_JOB_LIBRARY_SCHEMA)
        with self._lock:
            with self._connect() as conn:
                columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(library_jobs)"
                    ).fetchall()
                }
                if "workbench_job_id" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "workbench_job_id TEXT"
                    )
                if "workbench_resume_id" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "workbench_resume_id TEXT"
                    )
                if "tailor_granularity" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "tailor_granularity TEXT"
                    )
                if "tailor_focus" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "tailor_focus TEXT"
                    )
                if "custom_prompt" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "custom_prompt TEXT"
                    )
                if "classification_pending" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "classification_pending INTEGER NOT NULL DEFAULT 0"
                    )
                if "final_draft" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "final_draft TEXT"
                    )
                if "final_draft_updated_at" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "final_draft_updated_at REAL"
                    )
                if "final_draft_version" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "final_draft_version INTEGER NOT NULL DEFAULT 0"
                    )
