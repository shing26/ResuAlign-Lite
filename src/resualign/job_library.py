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

JOB_STATUSES_CANONICAL = ("draft", "applied", "interview", "offer", "withdrawn")

_JOB_STATUS_ALIASES = {
    "未投递": "draft",
    "已投递": "applied",
    "面试中": "interview",
    "已拿Offer": "offer",
    "放弃": "withdrawn",
}

_STATUS_LABELS = {canonical: legacy for legacy, canonical in _JOB_STATUS_ALIASES.items()}


def canonical_status(status: str) -> str:
    """Return the canonical five-state key for a stored status value."""
    value = str(status or "").strip()
    return _JOB_STATUS_ALIASES.get(value, value)


def status_label(status: str) -> str:
    """Return the display label for a canonical or stored status value."""
    value = str(status or "").strip()
    canonical = _JOB_STATUS_ALIASES.get(value, value)
    return _STATUS_LABELS.get(canonical, canonical)


def _status_filter_values(status: str) -> tuple[str, ...]:
    """Expand a canonical or legacy status to all values that map to it."""
    value = str(status or "").strip()
    canonical = canonical_status(value)
    aliases = tuple(
        legacy
        for legacy, canon in _JOB_STATUS_ALIASES.items()
        if canon == canonical
    )
    if value not in aliases:
        aliases = aliases + (value,)
    return aliases


def _validate_status(status: str) -> str:
    value = str(status or "").strip()
    if value in JOB_STATUSES or value in JOB_STATUSES_CANONICAL:
        return value
    raise UserStoreError(f"Invalid status: {value}")


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
    applied_at TEXT,
    next_step TEXT,
    notes TEXT,
    offer_at TEXT,
    rejected_at TEXT,
    workbench_job_id TEXT,
    workbench_resume_id TEXT,
    tailor_granularity TEXT,
    tailor_focus TEXT,
    custom_prompt TEXT,
    jd_profile_json TEXT,
    gap_report_json TEXT,
    match_score REAL,
    alignment_status TEXT NOT NULL DEFAULT 'idle',
    diffs_json TEXT NOT NULL DEFAULT '[]',
    invalid_diffs_json TEXT NOT NULL DEFAULT '[]',
    draft TEXT,
    eval_score_json TEXT,
    model TEXT,
    prompt_version TEXT,
    generated_at REAL,
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

CREATE TABLE IF NOT EXISTS crawl_tasks (
    crawl_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT,
    jd_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT '',
    error TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_crawl_tasks_tenant
    ON crawl_tasks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_crawl_tasks_status
    ON crawl_tasks(status);

CREATE TABLE IF NOT EXISTS kanban_bulk_ops (
    idempotency_key TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, idempotency_key)
);
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

    def validate_status(self, status: str) -> str:
        """Return a validated stored status value for the kanban model."""
        return _validate_status(status)

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
        applied_at: str | None = None,
        next_step: str | None = None,
        notes: str | None = None,
        offer_at: str | None = None,
        rejected_at: str | None = None,
        jd_profile: dict[str, Any] | None = None,
        gap_report: dict[str, Any] | None = None,
        match_score: float | None = None,
        alignment_status: str = "idle",
        diffs: list[dict[str, Any]] | None = None,
        invalid_diffs: list[dict[str, Any]] | None = None,
        draft: str | None = None,
        eval_score: dict[str, Any] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        generated_at: float | None = None,
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
        status = _validate_status(status)
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
        if alignment_status not in (
            "idle",
            "queued",
            "running",
            "succeeded",
            "failed",
        ):
            raise UserStoreError(f"Invalid alignment_status: {alignment_status}")

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
                        "posting_date, applied_at, next_step, notes, "
                        "offer_at, rejected_at, jd_profile_json, "
                        "gap_report_json, match_score, alignment_status, "
                        "diffs_json, invalid_diffs_json, draft, "
                        "eval_score_json, model, prompt_version, "
                        "generated_at, dedupe_key, created_at, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, "
                        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                            applied_at,
                            next_step,
                            notes,
                            offer_at,
                            rejected_at,
                            json.dumps(jd_profile, ensure_ascii=False)
                            if jd_profile is not None
                            else None,
                            json.dumps(gap_report, ensure_ascii=False)
                            if gap_report is not None
                            else None,
                            match_score,
                            alignment_status,
                            json.dumps(diffs or [], ensure_ascii=False),
                            json.dumps(invalid_diffs or [], ensure_ascii=False),
                            draft,
                            json.dumps(eval_score, ensure_ascii=False)
                            if eval_score is not None
                            else None,
                            model,
                            prompt_version,
                            generated_at,
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

    def find_by_dedupe_key(
        self, tenant_id: str, dedupe_key: str
    ) -> Optional[dict[str, Any]]:
        """Return the tenant-scoped job that owns a dedupe key."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM library_jobs "
                    "WHERE tenant_id = ? AND dedupe_key = ? "
                    "ORDER BY created_at ASC LIMIT 1",
                    (tenant_id, dedupe_key),
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
            status_values = _status_filter_values(status)
            placeholders = ", ".join("?" for _ in status_values)
            conditions.append(f"status IN ({placeholders})")
            values.extend(status_values)
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
        applied_at: str | None = None,
        next_step: str | None = None,
        notes: str | None = None,
        offer_at: str | None = None,
        rejected_at: str | None = None,
        jd_profile: dict[str, Any] | None = None,
        gap_report: dict[str, Any] | None = None,
        match_score: float | None = None,
        alignment_status: str | None = None,
        diffs: list[dict[str, Any]] | None = None,
        invalid_diffs: list[dict[str, Any]] | None = None,
        draft: str | None = None,
        eval_score: dict[str, Any] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        generated_at: float | None = None,
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
        if status is not None:
            status = _validate_status(status)
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
        if applied_at is not None:
            sets.append("applied_at = ?")
            values.append(applied_at)
        if next_step is not None:
            sets.append("next_step = ?")
            values.append(next_step)
        if notes is not None:
            sets.append("notes = ?")
            values.append(notes)
        if offer_at is not None:
            sets.append("offer_at = ?")
            values.append(offer_at)
        if rejected_at is not None:
            sets.append("rejected_at = ?")
            values.append(rejected_at)
        if jd_profile is not None:
            sets.append("jd_profile_json = ?")
            values.append(
                json.dumps(jd_profile, ensure_ascii=False)
            )
        if gap_report is not None:
            sets.append("gap_report_json = ?")
            values.append(
                json.dumps(gap_report, ensure_ascii=False)
            )
        if match_score is not None:
            sets.append("match_score = ?")
            values.append(match_score)
        if alignment_status is not None:
            if alignment_status not in (
                "idle",
                "queued",
                "running",
                "succeeded",
                "failed",
            ):
                raise UserStoreError(
                    f"Invalid alignment_status: {alignment_status}"
                )
            sets.append("alignment_status = ?")
            values.append(alignment_status)
        if diffs is not None:
            sets.append("diffs_json = ?")
            values.append(json.dumps(diffs, ensure_ascii=False))
        if invalid_diffs is not None:
            sets.append("invalid_diffs_json = ?")
            values.append(json.dumps(invalid_diffs, ensure_ascii=False))
        if draft is not None:
            sets.append("draft = ?")
            values.append(draft)
        if eval_score is not None:
            sets.append("eval_score_json = ?")
            values.append(json.dumps(eval_score, ensure_ascii=False))
        if model is not None:
            sets.append("model = ?")
            values.append(model)
        if prompt_version is not None:
            sets.append("prompt_version = ?")
            values.append(prompt_version)
        if generated_at is not None:
            sets.append("generated_at = ?")
            values.append(generated_at)
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

    def save_alignment(
        self,
        tenant_id: str,
        job_id: str,
        jd_profile: dict[str, Any] | None = None,
        gap_report: dict[str, Any] | None = None,
        match_score: float | None = None,
        diffs: list[dict[str, Any]] | None = None,
        invalid_diffs: list[dict[str, Any]] | None = None,
        draft: str | None = None,
        eval_score: dict[str, Any] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        alignment_status: str = "succeeded",
    ) -> Optional[dict[str, Any]]:
        """Persist a terminal alignment product for one library job."""
        if alignment_status not in (
            "idle",
            "queued",
            "running",
            "succeeded",
            "failed",
        ):
            raise UserStoreError(f"Invalid alignment_status: {alignment_status}")
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT 1 FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                conn.execute(
                    "UPDATE library_jobs SET "
                    "jd_profile_json = ?, gap_report_json = ?, "
                    "match_score = ?, alignment_status = ?, "
                    "diffs_json = ?, invalid_diffs_json = ?, draft = ?, "
                    "eval_score_json = ?, model = ?, prompt_version = ?, "
                    "generated_at = ?, updated_at = ? "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (
                        (
                            json.dumps(jd_profile, ensure_ascii=False)
                            if jd_profile is not None
                            else None
                        ),
                        (
                            json.dumps(gap_report, ensure_ascii=False)
                            if gap_report is not None
                            else None
                        ),
                        match_score,
                        alignment_status,
                        json.dumps(diffs or [], ensure_ascii=False),
                        json.dumps(invalid_diffs or [], ensure_ascii=False),
                        draft,
                        (
                            json.dumps(eval_score, ensure_ascii=False)
                            if eval_score is not None
                            else None
                        ),
                        model,
                        prompt_version,
                        now,
                        now,
                        job_id,
                        tenant_id,
                    ),
                )
        return self.get_job(tenant_id, job_id)

    def bulk_update_status(
        self,
        tenant_id: str,
        job_ids: Sequence[str],
        status: str,
        expected_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Update many job statuses in one SQLite transaction.

        Returns per-row ``updated`` / ``not_found`` / ``conflict`` results.
        ``expected_status`` enables an optimistic lock: rows in a different
        canonical status are reported as conflicts and left unchanged.
        """
        if not job_ids:
            return []
        status = _validate_status(status)
        expected = (
            canonical_status(_validate_status(expected_status))
            if expected_status is not None
            else None
        )
        results: list[dict[str, Any]] = []
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                for job_id in job_ids:
                    row = conn.execute(
                        "SELECT * FROM library_jobs "
                        "WHERE job_id = ? AND tenant_id = ?",
                        (job_id, tenant_id),
                    ).fetchone()
                    if row is None:
                        results.append(
                            {
                                "job_id": job_id,
                                "updated": False,
                                "status": "not_found",
                                "job": None,
                            }
                        )
                        continue
                    if (
                        expected is not None
                        and canonical_status(row["status"]) != expected
                    ):
                        results.append(
                            {
                                "job_id": job_id,
                                "updated": False,
                                "status": "conflict",
                                "job": self._row_to_job(row),
                            }
                        )
                        continue
                    cursor = conn.execute(
                        "UPDATE library_jobs SET status = ?, updated_at = ? "
                        "WHERE job_id = ? AND tenant_id = ?",
                        (status, now, job_id, tenant_id),
                    )
                    if cursor.rowcount == 0:
                        results.append(
                            {
                                "job_id": job_id,
                                "updated": False,
                                "status": "conflict",
                                "job": self._row_to_job(row),
                            }
                        )
                        continue
                    updated_row = conn.execute(
                        "SELECT * FROM library_jobs "
                        "WHERE job_id = ? AND tenant_id = ?",
                        (job_id, tenant_id),
                    ).fetchone()
                    results.append(
                        {
                            "job_id": job_id,
                            "updated": True,
                            "status": "updated",
                            "job": self._row_to_job(updated_row),
                        }
                    )
        return results

    def save_bulk_status_op(
        self,
        tenant_id: str,
        idempotency_key: str,
        request_payload: dict[str, Any],
        result_payload: dict[str, Any],
    ) -> None:
        """Remember a completed bulk status operation for replay."""
        if not idempotency_key:
            return
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO kanban_bulk_ops ("
                    "idempotency_key, tenant_id, request_json, result_json, "
                    "created_at"
                    ") VALUES (?, ?, ?, ?, ?)",
                    (
                        idempotency_key,
                        tenant_id,
                        json.dumps(request_payload, ensure_ascii=False),
                        json.dumps(result_payload, ensure_ascii=False),
                        time.time(),
                    ),
                )

    def get_bulk_status_op(
        self,
        tenant_id: str,
        idempotency_key: str,
    ) -> Optional[dict[str, Any]]:
        """Return a previously completed bulk status operation."""
        if not idempotency_key:
            return None
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT request_json, result_json FROM kanban_bulk_ops "
                    "WHERE tenant_id = ? AND idempotency_key = ?",
                    (tenant_id, idempotency_key),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "request": json.loads(row["request_json"]),
                    "result": json.loads(row["result_json"]),
                }

    def delete_job(
        self, tenant_id: str, job_id: str
    ) -> tuple[bool, str | None]:
        """Delete a library job and its crawl tasks.

        Returns ``(deleted, workbench_job_id)`` so callers can also clean up
        the pinned analysis job. ``workbench_job_id`` is the analysis job id
        recorded on the deleted row, or None when no run was pinned.
        """
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT workbench_job_id FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if row is None:
                    return False, None
                workbench_job_id = row["workbench_job_id"]
                conn.execute(
                    "DELETE FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                )
                conn.execute(
                    "DELETE FROM crawl_tasks "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                )
                return True, workbench_job_id

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
        alignment_status = row["alignment_status"] or "idle"
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
            "applied_at": row["applied_at"],
            "next_step": row["next_step"],
            "notes": row["notes"],
            "offer_at": row["offer_at"],
            "rejected_at": row["rejected_at"],
            "workbench_job_id": row["workbench_job_id"],
            "workbench_resume_id": row["workbench_resume_id"],
            "tailor_granularity": row["tailor_granularity"],
            "tailor_focus": row["tailor_focus"],
            "custom_prompt": row["custom_prompt"],
            "jd_profile": (
                json.loads(row["jd_profile_json"])
                if row["jd_profile_json"]
                else None
            ),
            "gap_report": (
                json.loads(row["gap_report_json"])
                if row["gap_report_json"]
                else None
            ),
            "match_score": row["match_score"],
            "alignment_status": alignment_status,
            "diffs": json.loads(row["diffs_json"] or "[]"),
            "invalid_diffs": json.loads(row["invalid_diffs_json"] or "[]"),
            "draft": row["draft"],
            "eval_score": (
                json.loads(row["eval_score_json"])
                if row["eval_score_json"]
                else None
            ),
            "model": row["model"],
            "prompt_version": row["prompt_version"],
            "generated_at": row["generated_at"],
            "analysis_ready": alignment_status == "succeeded",
            "status_canonical": canonical_status(row["status"]),
            "status_label": status_label(row["status"]),
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
                if "jd_profile_json" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "jd_profile_json TEXT"
                    )
                if "gap_report_json" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "gap_report_json TEXT"
                    )
                if "match_score" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN match_score REAL"
                    )
                if "alignment_status" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "alignment_status TEXT NOT NULL DEFAULT 'idle'"
                    )
                if "diffs_json" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "diffs_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "invalid_diffs_json" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "invalid_diffs_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if "draft" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN draft TEXT"
                    )
                if "eval_score_json" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "eval_score_json TEXT"
                    )
                if "model" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN model TEXT"
                    )
                if "prompt_version" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN "
                        "prompt_version TEXT"
                    )
                if "generated_at" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN generated_at REAL"
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
                if "applied_at" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN applied_at TEXT"
                    )
                if "next_step" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN next_step TEXT"
                    )
                if "notes" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN notes TEXT"
                    )
                if "offer_at" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN offer_at TEXT"
                    )
                if "rejected_at" not in columns:
                    conn.execute(
                        "ALTER TABLE library_jobs ADD COLUMN rejected_at TEXT"
                    )


CRAWL_TASK_STATES = (
    "queued",
    "fetching",
    "parsing",
    "classifying",
    "succeeded",
    "failed",
)

_CRAWL_TASK_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "queued": ("fetching", "failed"),
    "fetching": ("parsing", "failed", "queued"),
    "parsing": ("classifying", "failed", "queued"),
    "classifying": ("succeeded", "failed", "queued"),
    "succeeded": (),
    "failed": ("queued",),
}


class CrawlTaskStore(_SqliteStore):
    """SQLite-backed crawl task state machine with restart recovery."""

    def create(
        self,
        tenant_id: str,
        jd_url: str,
        job_id: str | None = None,
        crawl_id: str | None = None,
    ) -> dict[str, Any]:
        url = (jd_url or "").strip()
        if not url:
            raise UserStoreError("A JD URL is required")
        task_id = crawl_id or uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO crawl_tasks ("
                    "crawl_id, tenant_id, job_id, jd_url, status, stage, "
                    "error, attempts, created_at, updated_at, finished_at"
                    ") VALUES (?, ?, ?, ?, 'queued', '', NULL, 0, ?, ?, NULL)",
                    (task_id, tenant_id, job_id, url, now, now),
                )
        task = self.get(task_id, tenant_id)
        assert task is not None
        return task

    def get(
        self, crawl_id: str, tenant_id: str | None = None
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                if tenant_id is None:
                    row = conn.execute(
                        "SELECT * FROM crawl_tasks WHERE crawl_id = ?",
                        (crawl_id,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT * FROM crawl_tasks "
                        "WHERE crawl_id = ? AND tenant_id = ?",
                        (crawl_id, tenant_id),
                    ).fetchone()
                return self._row_to_task(row) if row else None

    def update_state(
        self,
        crawl_id: str,
        status: str,
        stage: str | None = None,
        error: str | None = None,
        tenant_id: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Advance a crawl task through the state machine."""
        if status not in CRAWL_TASK_STATES:
            raise UserStoreError(f"Invalid crawl task status: {status}")
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                if tenant_id is None:
                    row = conn.execute(
                        "SELECT status, attempts FROM crawl_tasks "
                        "WHERE crawl_id = ?",
                        (crawl_id,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        "SELECT status, attempts FROM crawl_tasks "
                        "WHERE crawl_id = ? AND tenant_id = ?",
                        (crawl_id, tenant_id),
                    ).fetchone()
                if row is None:
                    return None
                current = row["status"]
                if status not in _CRAWL_TASK_TRANSITIONS[current]:
                    raise UserStoreError(
                        f"Invalid crawl transition: {current} -> {status}"
                    )
                now = time.time()
                finished_at = now if status in ("succeeded", "failed") else None
                attempts = (
                    row["attempts"] + 1
                    if status in ("queued", "fetching")
                    else row["attempts"]
                )
                sets = ["status = ?", "updated_at = ?", "attempts = ?"]
                values: list[Any] = [status, now, attempts]
                if stage is not None:
                    sets.append("stage = ?")
                    values.append(stage)
                if error is not None:
                    sets.append("error = ?")
                    values.append(error)
                if status in ("succeeded", "failed"):
                    sets.append("finished_at = ?")
                    values.append(finished_at)
                values.extend([crawl_id])
                if tenant_id is not None:
                    values.append(tenant_id)
                where = "crawl_id = ?"
                if tenant_id is not None:
                    where += " AND tenant_id = ?"
                conn.execute(
                    f"UPDATE crawl_tasks SET {', '.join(sets)} "
                    f"WHERE {where}",
                    values,
                )
        return self.get(crawl_id, tenant_id)

    def requeue_interrupted(self, crawl_id: str) -> bool:
        """Return a non-terminal crawl task to the queued state."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM crawl_tasks WHERE crawl_id = ?",
                    (crawl_id,),
                ).fetchone()
                if row is None:
                    return False
                if row["status"] not in (
                    "fetching",
                    "parsing",
                    "classifying",
                    "failed",
                ):
                    return False
                conn.execute(
                    "UPDATE crawl_tasks SET status = 'queued', "
                    "stage = 'requeued', error = NULL, finished_at = NULL, "
                    "updated_at = ? WHERE crawl_id = ?",
                    (time.time(), crawl_id),
                )
                return True

    def pending_crawl_ids(
        self, tenant_id: str | None = None
    ) -> list[str]:
        """Return queued or in-flight crawl task ids in submission order."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                if tenant_id is None:
                    rows = conn.execute(
                        "SELECT crawl_id FROM crawl_tasks "
                        "WHERE status IN "
                        "('queued','fetching','parsing','classifying') "
                        "ORDER BY created_at ASC, rowid ASC"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT crawl_id FROM crawl_tasks "
                        "WHERE tenant_id = ? AND status IN "
                        "('queued','fetching','parsing','classifying') "
                        "ORDER BY created_at ASC, rowid ASC",
                        (tenant_id,),
                    ).fetchall()
                return [row["crawl_id"] for row in rows]

    def recover_interrupted(self) -> int:
        """Requeue interrupted crawl tasks after a restart."""
        recovered = 0
        for crawl_id in self.pending_crawl_ids():
            if self.requeue_interrupted(crawl_id):
                recovered += 1
        return recovered

    def list_recent(
        self, tenant_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM crawl_tasks WHERE tenant_id = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (tenant_id, max(1, min(int(limit), 200))),
                ).fetchall()
                return [self._row_to_task(row) for row in rows]

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "crawl_id": row["crawl_id"],
            "tenant_id": row["tenant_id"],
            "job_id": row["job_id"],
            "jd_url": row["jd_url"],
            "status": row["status"],
            "stage": row["stage"],
            "error": row["error"],
            "attempts": row["attempts"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "finished_at": row["finished_at"],
        }

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_JOB_LIBRARY_SCHEMA)
