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


def status_lifecycle_fields(
    current: dict[str, Any] | None,
    target_status: str,
    today: str | None = None,
    provided: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return timeline field writes for a status transition (ADR-0027).

    Values follow ``update_job``'s clear-on-empty contract: ``""`` clears a
    field, a string sets it, and omitted keys leave it unchanged. Forward
    moves fill the stage's missing timestamp with ``today``; terminal states
    keep historical timestamps while clearing follow-up fields.
    """
    target = canonical_status(target_status)
    if target not in JOB_STATUSES_CANONICAL:
        return {}
    today = today or time.strftime("%Y-%m-%d")
    current = current or {}
    provided = provided or {}
    out: dict[str, str] = {}

    def pick(field: str, fallback: str) -> str:
        value = provided.get(field)
        return fallback if value is None else value

    if target == "draft":
        for field in (
            "applied_at",
            "offer_at",
            "rejected_at",
            "next_step",
            "next_step_due_at",
            "interview_stage",
        ):
            out[field] = ""
        return out

    if target == "applied":
        out["applied_at"] = pick("applied_at", current.get("applied_at") or today)
        for field in ("offer_at", "rejected_at", "interview_stage"):
            out[field] = ""
        return out

    if target == "interview":
        out["applied_at"] = pick("applied_at", current.get("applied_at") or today)
        for field in ("offer_at", "rejected_at"):
            out[field] = ""
        return out

    if target == "offer":
        out["offer_at"] = pick("offer_at", today)
        out["rejected_at"] = ""
        for field in ("next_step", "next_step_due_at", "interview_stage"):
            out[field] = ""
        return out

    if target == "withdrawn":
        out["rejected_at"] = pick("rejected_at", today)
        for field in ("next_step", "next_step_due_at", "interview_stage"):
            out[field] = ""
        return out

    return out


RULE_TYPES = ("blacklist", "city_whitelist", "min_salary")

BLOCKER_CATEGORIES = (
    "captcha",
    "login_required",
    "no_content",
    "parse_error",
    "fetch_error",
    "rule_rejected",
    "timeout",
    "network_error",
    "site_error",
    "invalid_url",
)

BLOCKER_STATUSES = ("pending", "resolved", "ignored")

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
    next_step_due_at TEXT,
    interview_stage TEXT,
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

CREATE TABLE IF NOT EXISTS automation_rules (
    rule_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_automation_rules_tenant
    ON automation_rules(tenant_id);

CREATE TABLE IF NOT EXISTS blocker_queue (
    blocker_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    job_id TEXT,
    url TEXT,
    title TEXT,
    reason TEXT,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    manual_text TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_blocker_queue_tenant
    ON blocker_queue(tenant_id);
CREATE INDEX IF NOT EXISTS idx_blocker_queue_status
    ON blocker_queue(status);

CREATE TABLE IF NOT EXISTS application_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    version_index INTEGER NOT NULL,
    final_draft TEXT NOT NULL,
    match_score REAL,
    master_resume_id TEXT,
    applied_at TEXT NOT NULL,
    created_at REAL NOT NULL,
    UNIQUE(tenant_id, job_id, version_index)
);
CREATE INDEX IF NOT EXISTS idx_application_snapshots_job
    ON application_snapshots(tenant_id, job_id, created_at DESC);
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

    # Historical single-column upgrades, one version per ALTER. Fresh
    # databases already carry these columns in _JOB_LIBRARY_SCHEMA; the
    # shared migrator records them as applied on duplicate-column failures.
    MIGRATIONS = (
        (1, "ALTER TABLE library_jobs ADD COLUMN workbench_job_id TEXT"),
        (2, "ALTER TABLE library_jobs ADD COLUMN workbench_resume_id TEXT"),
        (3, "ALTER TABLE library_jobs ADD COLUMN tailor_granularity TEXT"),
        (4, "ALTER TABLE library_jobs ADD COLUMN tailor_focus TEXT"),
        (5, "ALTER TABLE library_jobs ADD COLUMN custom_prompt TEXT"),
        (6, "ALTER TABLE library_jobs ADD COLUMN jd_profile_json TEXT"),
        (7, "ALTER TABLE library_jobs ADD COLUMN gap_report_json TEXT"),
        (8, "ALTER TABLE library_jobs ADD COLUMN match_score REAL"),
        (
            9,
            "ALTER TABLE library_jobs ADD COLUMN "
            "alignment_status TEXT NOT NULL DEFAULT 'idle'",
        ),
        (
            10,
            "ALTER TABLE library_jobs ADD COLUMN "
            "diffs_json TEXT NOT NULL DEFAULT '[]'",
        ),
        (
            11,
            "ALTER TABLE library_jobs ADD COLUMN "
            "invalid_diffs_json TEXT NOT NULL DEFAULT '[]'",
        ),
        (12, "ALTER TABLE library_jobs ADD COLUMN draft TEXT"),
        (13, "ALTER TABLE library_jobs ADD COLUMN eval_score_json TEXT"),
        (14, "ALTER TABLE library_jobs ADD COLUMN model TEXT"),
        (15, "ALTER TABLE library_jobs ADD COLUMN prompt_version TEXT"),
        (16, "ALTER TABLE library_jobs ADD COLUMN generated_at REAL"),
        (
            17,
            "ALTER TABLE library_jobs ADD COLUMN "
            "classification_pending INTEGER NOT NULL DEFAULT 0",
        ),
        (18, "ALTER TABLE library_jobs ADD COLUMN final_draft TEXT"),
        (19, "ALTER TABLE library_jobs ADD COLUMN final_draft_updated_at REAL"),
        (
            20,
            "ALTER TABLE library_jobs ADD COLUMN "
            "final_draft_version INTEGER NOT NULL DEFAULT 0",
        ),
        (21, "ALTER TABLE library_jobs ADD COLUMN applied_at TEXT"),
        (22, "ALTER TABLE library_jobs ADD COLUMN next_step TEXT"),
        (23, "ALTER TABLE library_jobs ADD COLUMN notes TEXT"),
        (24, "ALTER TABLE library_jobs ADD COLUMN offer_at TEXT"),
        (25, "ALTER TABLE library_jobs ADD COLUMN rejected_at TEXT"),
        (
            26,
            "ALTER TABLE library_jobs ADD COLUMN next_step_due_at TEXT",
        ),
        (
            27,
            "ALTER TABLE library_jobs ADD COLUMN interview_stage TEXT",
        ),
        # Sprint 3: pipeline fetch automation rules + blocker queue. The
        # tables also live in _JOB_LIBRARY_SCHEMA (fresh databases), so these
        # CREATE IF NOT EXISTS migrations are no-ops there and only create the
        # tables on databases predating Sprint 3.
        (
            28,
            "CREATE TABLE IF NOT EXISTS automation_rules ("
            "rule_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "rule_type TEXT NOT NULL, value TEXT NOT NULL, label TEXT, "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL)",
        ),
        (
            29,
            "CREATE TABLE IF NOT EXISTS blocker_queue ("
            "blocker_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, "
            "job_id TEXT, url TEXT, title TEXT, reason TEXT, "
            "category TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
            "manual_text TEXT, created_at REAL NOT NULL, "
            "updated_at REAL NOT NULL)",
        ),
        (
            30,
            "CREATE TABLE IF NOT EXISTS application_snapshots ("
            "snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tenant_id TEXT NOT NULL, job_id TEXT NOT NULL, "
            "version_index INTEGER NOT NULL, "
            "final_draft TEXT NOT NULL, match_score REAL, "
            "master_resume_id TEXT, applied_at TEXT NOT NULL, "
            "created_at REAL NOT NULL, "
            "UNIQUE(tenant_id, job_id, version_index)); "
            "CREATE INDEX IF NOT EXISTS idx_application_snapshots_job "
            "ON application_snapshots(tenant_id, job_id, created_at DESC)",
        ),
    )

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
        next_step_due_at: str | None = None,
        interview_stage: str | None = None,
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
        dedupe_key: str | None = None,
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

        if dedupe_key is None:
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
        else:
            dedupe_key = dedupe_key.strip()
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
                        "offer_at, rejected_at, next_step_due_at, "
                        "interview_stage, jd_profile_json, "
                        "gap_report_json, match_score, alignment_status, "
                        "diffs_json, invalid_diffs_json, draft, "
                        "eval_score_json, model, prompt_version, "
                        "generated_at, dedupe_key, created_at, updated_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, "
                        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                            next_step_due_at,
                            interview_stage,
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

    def find_job_by_application_source(
        self,
        tenant_id: str,
        jd_url: str | None = None,
        jd_text: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Return the library job matching an application's JD source (G6).

        Matches by normalized source URL first, then by the tenant-scoped
        dedupe key of the JD text. Returns the oldest match; None when no
        library job corresponds to this application.
        """
        url = (jd_url or "").strip()
        text = (jd_text or "").strip()
        if not url and not text:
            return None
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_id, source_url, dedupe_key "
                    "FROM library_jobs WHERE tenant_id = ? "
                    "ORDER BY created_at ASC",
                    (tenant_id,),
                ).fetchall()
        if url:
            normalized_url = _normalize_source_url(url)
            for row in rows:
                if row["source_url"] and (
                    _normalize_source_url(row["source_url"]) == normalized_url
                ):
                    return self.get_job(tenant_id, row["job_id"])
        if text:
            key = _text_dedupe_key(text)
            for row in rows:
                if row["dedupe_key"] == key:
                    return self.get_job(tenant_id, row["job_id"])
        return None

    def append_application_snapshot(
        self,
        tenant_id: str,
        job_id: str,
        *,
        final_draft: str | None = None,
        match_score: float | None = None,
        master_resume_id: str | None = None,
        applied_at: str | None = None,
        created_at: float | None = None,
    ) -> Optional[dict[str, Any]]:
        """Append an immutable applied-draft snapshot for one job.

        ``version_index`` continues 1, 2, 3... within a job. Missing jobs
        and empty drafts return None without creating a row.
        """
        if not final_draft or not final_draft.strip():
            return None
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT final_draft, match_score, workbench_resume_id, "
                    "applied_at FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if row is None:
                    return None
                if match_score is None:
                    match_score = row["match_score"]
                if master_resume_id is None:
                    master_resume_id = row["workbench_resume_id"]
                if not applied_at:
                    applied_at = row["applied_at"] or time.strftime(
                        "%Y-%m-%d"
                    )
                snapshot = self._insert_application_snapshot(
                    conn,
                    tenant_id,
                    job_id,
                    final_draft=final_draft or row["final_draft"],
                    match_score=match_score,
                    master_resume_id=master_resume_id,
                    applied_at=applied_at,
                    created_at=created_at,
                )
                return snapshot

    def list_application_snapshots(
        self, tenant_id: str, job_id: str
    ) -> list[dict[str, Any]]:
        """Return a job's immutable applied-draft snapshots, newest first."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM application_snapshots "
                    "WHERE tenant_id = ? AND job_id = ? "
                    "ORDER BY created_at DESC, version_index DESC",
                    (tenant_id, job_id),
                ).fetchall()
                return [self._row_to_snapshot(row) for row in rows]

    def get_application_snapshot(
        self, tenant_id: str, snapshot_id: int
    ) -> Optional[dict[str, Any]]:
        """Return one immutable applied-draft snapshot."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM application_snapshots "
                    "WHERE tenant_id = ? AND snapshot_id = ?",
                    (tenant_id, snapshot_id),
                ).fetchone()
                return self._row_to_snapshot(row) if row else None

    @staticmethod
    def _insert_application_snapshot(
        conn,
        tenant_id: str,
        job_id: str,
        *,
        final_draft: str,
        match_score: float | None,
        master_resume_id: str | None,
        applied_at: str,
        created_at: float | None = None,
    ) -> Optional[dict[str, Any]]:
        """Insert the next snapshot version inside an existing transaction."""
        if not final_draft or not final_draft.strip():
            return None
        if not applied_at:
            applied_at = time.strftime("%Y-%m-%d")
        created_at = time.time() if created_at is None else created_at
        version_row = conn.execute(
            "SELECT COALESCE(MAX(version_index), 0) + 1 AS next_version "
            "FROM application_snapshots "
            "WHERE tenant_id = ? AND job_id = ?",
            (tenant_id, job_id),
        ).fetchone()
        version_index = int(version_row["next_version"])
        cursor = conn.execute(
            "INSERT INTO application_snapshots ("
            "tenant_id, job_id, version_index, final_draft, "
            "match_score, master_resume_id, applied_at, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                job_id,
                version_index,
                final_draft,
                match_score,
                master_resume_id,
                applied_at,
                created_at,
            ),
        )
        return {
            "snapshot_id": cursor.lastrowid,
            "tenant_id": tenant_id,
            "job_id": job_id,
            "version_index": version_index,
            "final_draft": final_draft,
            "match_score": match_score,
            "master_resume_id": master_resume_id,
            "applied_at": applied_at,
            "created_at": created_at,
        }

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "snapshot_id": row["snapshot_id"],
            "tenant_id": row["tenant_id"],
            "job_id": row["job_id"],
            "version_index": row["version_index"],
            "final_draft": row["final_draft"],
            "match_score": row["match_score"],
            "master_resume_id": row["master_resume_id"],
            "applied_at": row["applied_at"],
            "created_at": row["created_at"],
        }

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

    def list_dashboard_jobs(
        self, tenant_id: str
    ) -> list[dict[str, Any]]:
        """Return a lean per-job projection for dashboard aggregation.

        The dashboard only needs status, historical pipeline timestamps,
        follow-up due dates, alignment state, and the JD profile's must-have
        skills. This avoids loading ``jd_text``/drafts/diffs for every library
        row, which would be wasteful for large libraries (100k+ entities).
        """
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT job_id, title, company, status, jd_profile_json, "
                    "alignment_status, applied_at, offer_at, "
                    "next_step_due_at, updated_at "
                    "FROM library_jobs WHERE tenant_id = ? "
                    "ORDER BY updated_at DESC",
                    (tenant_id,),
                ).fetchall()
        return [
            {
                "job_id": row["job_id"],
                "title": row["title"],
                "company": row["company"],
                "status": row["status"],
                "status_canonical": canonical_status(row["status"]),
                "jd_profile": (
                    json.loads(row["jd_profile_json"])
                    if row["jd_profile_json"]
                    else None
                ),
                "alignment_status": row["alignment_status"] or "idle",
                "applied_at": row["applied_at"] or None,
                "offer_at": row["offer_at"] or None,
                "next_step_due_at": row["next_step_due_at"] or None,
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

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
        next_step_due_at: str | None = None,
        interview_stage: str | None = None,
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
        """Update editable fields. None-valued fields are left unchanged.

        Timeline fields (``applied_at``, ``next_step``, ``notes``,
        ``offer_at``, ``rejected_at``, ``next_step_due_at``,
        ``interview_stage``) follow the clear-on-empty contract: an empty
        string clears the stored value to NULL (U10), while None leaves it
        untouched.
        """
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

        lifecycle: dict[str, str] = {}
        append_only_snapshot = False
        snapshot_applied_at: str | None = None
        if status is not None:
            current = self.get_job(tenant_id, job_id)
            if current is None:
                return None
            if (
                canonical_status(status) == "applied"
                and canonical_status(current["status"]) != "draft"
            ):
                # Re-recording an already-submitted job appends a new
                # immutable snapshot without downgrading status or rewriting
                # the existing timeline history (ADR-0028).
                append_only_snapshot = True
                snapshot_applied_at = (
                    applied_at
                    or current.get("applied_at")
                    or time.strftime("%Y-%m-%d")
                )
            else:
                lifecycle = status_lifecycle_fields(
                    current,
                    status,
                    provided={
                        "applied_at": applied_at,
                        "offer_at": offer_at,
                        "rejected_at": rejected_at,
                        "next_step": next_step,
                        "next_step_due_at": next_step_due_at,
                        "interview_stage": interview_stage,
                    },
                )
                for field, value in lifecycle.items():
                    if field == "applied_at":
                        applied_at = value
                    elif field == "offer_at":
                        offer_at = value
                    elif field == "rejected_at":
                        rejected_at = value
                    elif field == "next_step":
                        next_step = value
                    elif field == "next_step_due_at":
                        next_step_due_at = value
                    elif field == "interview_stage":
                        interview_stage = value

        if append_only_snapshot:
            # The status and every timeline field stay untouched on append.
            applied_at = None
            next_step = None
            notes = None
            offer_at = None
            rejected_at = None
            next_step_due_at = None
            interview_stage = None

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
        if status is not None and not append_only_snapshot:
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
        # Timeline fields: None = unchanged, "" = clear to NULL (U10).
        if applied_at is not None:
            if applied_at == "":
                sets.append("applied_at = NULL")
            else:
                sets.append("applied_at = ?")
                values.append(applied_at)
        if next_step is not None:
            if next_step == "":
                sets.append("next_step = NULL")
            else:
                sets.append("next_step = ?")
                values.append(next_step)
        if notes is not None:
            if notes == "":
                sets.append("notes = NULL")
            else:
                sets.append("notes = ?")
                values.append(notes)
        if offer_at is not None:
            if offer_at == "":
                sets.append("offer_at = NULL")
            else:
                sets.append("offer_at = ?")
                values.append(offer_at)
        if rejected_at is not None:
            if rejected_at == "":
                sets.append("rejected_at = NULL")
            else:
                sets.append("rejected_at = ?")
                values.append(rejected_at)
        if next_step_due_at is not None:
            if next_step_due_at == "":
                sets.append("next_step_due_at = NULL")
            else:
                sets.append("next_step_due_at = ?")
                values.append(next_step_due_at)
        if interview_stage is not None:
            if interview_stage == "":
                sets.append("interview_stage = NULL")
            else:
                sets.append("interview_stage = ?")
                values.append(interview_stage)
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
                should_snapshot = append_only_snapshot or (
                    status is not None
                    and canonical_status(status) == "applied"
                )
                if should_snapshot:
                    snapshot_row = conn.execute(
                        "SELECT final_draft, match_score, "
                        "workbench_resume_id, applied_at "
                        "FROM library_jobs "
                        "WHERE job_id = ? AND tenant_id = ?",
                        (job_id, tenant_id),
                    ).fetchone()
                    if snapshot_row is not None and (
                        snapshot_row["final_draft"] or ""
                    ).strip():
                        self._insert_application_snapshot(
                            conn,
                            tenant_id,
                            job_id,
                            final_draft=snapshot_row["final_draft"],
                            match_score=snapshot_row["match_score"],
                            master_resume_id=snapshot_row[
                                "workbench_resume_id"
                            ],
                            applied_at=(
                                snapshot_applied_at
                                if append_only_snapshot
                                else (
                                    snapshot_row["applied_at"]
                                    or time.strftime("%Y-%m-%d")
                                )
                            ),
                        )
        return self.get_job(tenant_id, job_id)

    def save_final_draft(
        self,
        tenant_id: str,
        job_id: str,
        draft: str,
        accepted_diff_ids: list[str] | None = None,
    ) -> Optional[dict[str, Any]]:
        """Persist a job's final draft and increment its saved version."""
        if not draft or not draft.strip():
            raise UserStoreError("Final draft cannot be empty")
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                current = conn.execute(
                    "SELECT final_draft_version, diffs_json FROM library_jobs "
                    "WHERE job_id = ? AND tenant_id = ?",
                    (job_id, tenant_id),
                ).fetchone()
                if current is None:
                    return None
                version = int(current["final_draft_version"] or 0) + 1
                accepted_ids = set(accepted_diff_ids or [])
                diffs = json.loads(current["diffs_json"] or "[]")
                changed = False
                for diff in diffs:
                    if (
                        diff.get("diff_id") in accepted_ids
                        and diff.get("provenance_state") != "accepted"
                    ):
                        diff["provenance_state"] = "accepted"
                        changed = True
                if changed:
                    conn.execute(
                        "UPDATE library_jobs SET diffs_json = ? "
                        "WHERE job_id = ? AND tenant_id = ?",
                        (
                            json.dumps(diffs, ensure_ascii=False),
                            job_id,
                            tenant_id,
                        ),
                    )
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

    def list_alignment_pending(
        self, tenant_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Return library jobs whose alignment is queued/running (O3 recovery).

        These records are normally transient while a workbench analysis is in
        flight. Startup recovery scans them to detect the crash window where
        the registry job reached a terminal state but the alignment product
        was never persisted.
        """
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                if tenant_id is None:
                    rows = conn.execute(
                        "SELECT * FROM library_jobs "
                        "WHERE alignment_status IN ('queued', 'running') "
                        "ORDER BY created_at ASC"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM library_jobs "
                        "WHERE tenant_id = ? "
                        "AND alignment_status IN ('queued', 'running') "
                        "ORDER BY created_at ASC",
                        (tenant_id,),
                    ).fetchall()
                return [self._row_to_job(row) for row in rows]

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
                    if (
                        canonical_status(status) == "applied"
                        and canonical_status(row["status"]) != "draft"
                    ):
                        # Append-only re-record: keep the existing status and
                        # timeline, and only freeze a new snapshot version.
                        self._insert_application_snapshot(
                            conn,
                            tenant_id,
                            job_id,
                            final_draft=row["final_draft"],
                            match_score=row["match_score"],
                            master_resume_id=row["workbench_resume_id"],
                            applied_at=(
                                row["applied_at"]
                                or time.strftime("%Y-%m-%d")
                            ),
                        )
                        results.append(
                            {
                                "job_id": job_id,
                                "updated": True,
                                "status": "updated",
                                "job": self._row_to_job(row),
                            }
                        )
                        continue
                    timeline = status_lifecycle_fields(
                        dict(row),
                        status,
                    )
                    if timeline:
                        columns = ["status = ?", "updated_at = ?"]
                        params: list[Any] = [status, now]
                        for field, value in timeline.items():
                            columns.append(f"{field} = ?")
                            params.append(value or None)
                    else:
                        columns = ["status = ?", "updated_at = ?"]
                        params = [status, now]
                    params.extend([job_id, tenant_id])
                    cursor = conn.execute(
                        f"UPDATE library_jobs SET {', '.join(columns)} "
                        "WHERE job_id = ? AND tenant_id = ?",
                        params,
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
                    if canonical_status(status) == "applied":
                        self._insert_application_snapshot(
                            conn,
                            tenant_id,
                            job_id,
                            final_draft=updated_row["final_draft"],
                            match_score=updated_row["match_score"],
                            master_resume_id=updated_row[
                                "workbench_resume_id"
                            ],
                            applied_at=(
                                updated_row["applied_at"]
                                or time.strftime("%Y-%m-%d")
                            ),
                        )
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
                conn.execute(
                    "DELETE FROM application_snapshots "
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
            "applied_at": row["applied_at"] or None,
            "next_step": row["next_step"] or None,
            "notes": row["notes"] or None,
            "offer_at": row["offer_at"] or None,
            "rejected_at": row["rejected_at"] or None,
            "next_step_due_at": row["next_step_due_at"] or None,
            "interview_stage": row["interview_stage"] or None,
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

    # -- Automation rules (Sprint 3 pipeline) --------------------------------

    def create_rule(
        self,
        tenant_id: str,
        rule_type: str,
        value: str,
        label: str | None = None,
        enabled: int | bool = 1,
    ) -> dict[str, Any]:
        """Create one enabled automation rule for a tenant."""
        rule_type = str(rule_type or "").strip()
        if rule_type not in RULE_TYPES:
            raise UserStoreError(f"Invalid rule_type: {rule_type}")
        value = (value or "").strip()
        if not value:
            raise UserStoreError("Rule value is required")
        if rule_type == "min_salary":
            _validate_min_salary_value(value)
        rule_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO automation_rules ("
                    "rule_id, tenant_id, rule_type, value, label, enabled, "
                    "created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        rule_id,
                        tenant_id,
                        rule_type,
                        value,
                        label,
                        1 if enabled else 0,
                        now,
                        now,
                    ),
                )
        rule = self.get_rule(tenant_id, rule_id)
        assert rule is not None
        return rule

    def get_rule(
        self, tenant_id: str, rule_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM automation_rules "
                    "WHERE rule_id = ? AND tenant_id = ?",
                    (rule_id, tenant_id),
                ).fetchone()
                return self._row_to_rule(row) if row else None

    def list_rules(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return a tenant's automation rules in creation order."""
        sql = "SELECT * FROM automation_rules WHERE tenant_id = ?"
        values: list[Any] = [tenant_id]
        if enabled_only:
            sql += " AND enabled = 1"
        sql += " ORDER BY created_at ASC, rowid ASC"
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(sql, values).fetchall()
                return [self._row_to_rule(row) for row in rows]

    def update_rule(
        self,
        tenant_id: str,
        rule_id: str,
        value: str | None = None,
        label: str | None = None,
        enabled: int | bool | None = None,
    ) -> Optional[dict[str, Any]]:
        """Partially update a rule; None-valued fields stay unchanged."""
        sets = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        current = self.get_rule(tenant_id, rule_id)
        if current is None:
            return None
        if value is not None:
            value = (value or "").strip()
            if not value:
                raise UserStoreError("Rule value cannot be empty")
            if current["rule_type"] == "min_salary":
                _validate_min_salary_value(value)
            sets.append("value = ?")
            values.append(value)
        if label is not None:
            sets.append("label = ?")
            values.append(label)
        if enabled is not None:
            sets.append("enabled = ?")
            values.append(1 if enabled else 0)
        values.extend([rule_id, tenant_id])
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE automation_rules SET {', '.join(sets)} "
                    "WHERE rule_id = ? AND tenant_id = ?",
                    values,
                )
        return self.get_rule(tenant_id, rule_id)

    def delete_rule(self, tenant_id: str, rule_id: str) -> bool:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM automation_rules "
                    "WHERE rule_id = ? AND tenant_id = ?",
                    (rule_id, tenant_id),
                )
                return cursor.rowcount > 0

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "rule_id": row["rule_id"],
            "tenant_id": row["tenant_id"],
            "rule_type": row["rule_type"],
            "value": row["value"],
            "label": row["label"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # -- Blocker queue (Sprint 3 pipeline) -----------------------------------

    def create_blocker(
        self,
        tenant_id: str,
        url: str | None = None,
        title: str | None = None,
        reason: str | None = None,
        category: str = "fetch_error",
        job_id: str | None = None,
        manual_text: str | None = None,
    ) -> dict[str, Any]:
        """Record one blocked fetch for a tenant's pending queue."""
        category = str(category or "").strip() or "fetch_error"
        if category not in BLOCKER_CATEGORIES:
            raise UserStoreError(f"Invalid blocker category: {category}")
        blocker_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO blocker_queue ("
                    "blocker_id, tenant_id, job_id, url, title, reason, "
                    "category, status, manual_text, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                    (
                        blocker_id,
                        tenant_id,
                        job_id,
                        url,
                        title,
                        reason,
                        category,
                        manual_text,
                        now,
                        now,
                    ),
                )
        blocker = self.get_blocker(tenant_id, blocker_id)
        assert blocker is not None
        return blocker

    def get_blocker(
        self, tenant_id: str, blocker_id: str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM blocker_queue "
                    "WHERE blocker_id = ? AND tenant_id = ?",
                    (blocker_id, tenant_id),
                ).fetchone()
                return self._row_to_blocker(row) if row else None

    def list_blockers(
        self,
        tenant_id: str,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return a tenant's blocker queue, newest first.

        status 参数缺省时返回全部状态（含 pending/ignored/resolved）；统计与展示请显式传 status=pending。
        """
        if status is not None and status not in BLOCKER_STATUSES:
            raise UserStoreError(f"Invalid blocker status: {status}")
        sql = "SELECT * FROM blocker_queue WHERE tenant_id = ?"
        values: list[Any] = [tenant_id]
        if status is not None:
            sql += " AND status = ?"
            values.append(status)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        values.append(max(1, min(int(limit), 500)))
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(sql, values).fetchall()
                return [self._row_to_blocker(row) for row in rows]

    def ignore_blocker(
        self, tenant_id: str, blocker_id: str
    ) -> Optional[dict[str, Any]]:
        """Mark a pending blocker ignored; non-pending blockers are a no-op."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM blocker_queue "
                    "WHERE blocker_id = ? AND tenant_id = ?",
                    (blocker_id, tenant_id),
                ).fetchone()
                if row is None:
                    return None
                if row["status"] != "pending":
                    return self.get_blocker(tenant_id, blocker_id)
                conn.execute(
                    "UPDATE blocker_queue SET status = 'ignored', "
                    "updated_at = ? WHERE blocker_id = ? AND tenant_id = ?",
                    (time.time(), blocker_id, tenant_id),
                )
        return self.get_blocker(tenant_id, blocker_id)

    def resolve_blocker(
        self,
        tenant_id: str,
        blocker_id: str,
        job_id: str,
        manual_text: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Mark a pending blocker resolved and link its created job."""
        if not job_id:
            raise UserStoreError("job_id is required to resolve a blocker")
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT status FROM blocker_queue "
                    "WHERE blocker_id = ? AND tenant_id = ?",
                    (blocker_id, tenant_id),
                ).fetchone()
                if row is None:
                    return None
                if row["status"] != "pending":
                    raise UserStoreError(
                        "Only pending blockers can be resolved"
                    )
                now = time.time()
                sets = [
                    "status = 'resolved'",
                    "job_id = ?",
                    "updated_at = ?",
                ]
                values: list[Any] = [job_id, now]
                if manual_text is not None:
                    sets.append("manual_text = ?")
                    values.append(manual_text)
                values.extend([blocker_id, tenant_id])
                conn.execute(
                    f"UPDATE blocker_queue SET {', '.join(sets)} "
                    "WHERE blocker_id = ? AND tenant_id = ?",
                    values,
                )
        return self.get_blocker(tenant_id, blocker_id)

    @staticmethod
    def _row_to_blocker(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "blocker_id": row["blocker_id"],
            "tenant_id": row["tenant_id"],
            "job_id": row["job_id"],
            "url": row["url"],
            "title": row["title"],
            "reason": row["reason"],
            "category": row["category"],
            "status": row["status"],
            "manual_text": row["manual_text"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_JOB_LIBRARY_SCHEMA)


# ---------------------------------------------------------------------------
# Automation rules + blocker queue (Sprint 3 pipeline)
#
# These rows live in the same database as library_jobs, so they are exposed
# as methods on JobLibraryStore (one store, one migration journal) rather
# than a separate store class that would replay a second migration series.
# ---------------------------------------------------------------------------


def _split_rule_value(value: str) -> list[str]:
    """Split a rule value into keyword/city tokens on ASCII/CN commas."""
    return [
        token.strip()
        for token in re.split(r"[,，\s]+", (value or "").strip())
        if token.strip()
    ]


def _validate_min_salary_value(value: str) -> float:
    try:
        threshold = float((value or "").strip())
    except (TypeError, ValueError) as exc:
        raise UserStoreError(
            "min_salary rule value must be a number"
        ) from exc
    if threshold <= 0:
        raise UserStoreError("min_salary rule value must be positive")
    return threshold


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
