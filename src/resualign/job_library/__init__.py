"""Tenant-scoped Job Library store for the workbench."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import statistics
import time
import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from ..store_base import UserStoreError, _SqliteStore
from .models import (
    JOB_FUNCTIONS,
    JOB_STATUSES,
    JOB_STATUSES_CANONICAL,
    RULE_TYPES,
    SENIORITIES,
    TAILOR_FOCUSES,
    TAILOR_GRANULARITIES,
    _effective_choices,
)
from .status_lifecycle import (
    _status_filter_values,
    _validate_status,
    canonical_status,
    status_label,
    status_lifecycle_fields,
)

__all__ = [
    "JOB_FUNCTIONS",
    "JOB_STATUSES",
    "JOB_STATUSES_CANONICAL",
    "JobLibraryStore",
    "RULE_TYPES",
    "SENIORITIES",
    "TAILOR_FOCUSES",
    "TAILOR_GRANULARITIES",
    "canonical_status",
    "status_label",
    "status_lifecycle_fields",
]

# 投递结果归因枚举：记录"这份定稿投出去的结局"，用于验证对齐质量
# （对齐 vs 未对齐简历的通过率）。空串清除（ADR-0027 clear-on-empty）。
APPLICATION_RESULTS = ("screen_pass", "ats_reject", "no_response", "other")

_JOB_UPDATE_PARAMETERS = (
    "title",
    "jd_text",
    "company",
    "location",
    "salary_min",
    "salary_max",
    "salary_currency",
    "source_type",
    "source_url",
    "job_function",
    "seniority",
    "tech_tags",
    "status",
    "classification_pending",
    "final_draft",
    "final_draft_updated_at",
    "final_draft_version",
    "posting_date",
    "applied_at",
    "next_step",
    "notes",
    "offer_at",
    "rejected_at",
    "next_step_due_at",
    "interview_stage",
    "match_stale",
    "jd_profile",
    "gap_report",
    "match_score",
    "match_score_detail",
    "match_reason",
    "match_updated_at",
    "alignment_status",
    "diffs",
    "invalid_diffs",
    "draft",
    "eval_score",
    "model",
    "prompt_version",
    "generated_at",
    "workbench_job_id",
    "workbench_resume_id",
    "tailor_granularity",
    "tailor_focus",
    "custom_prompt",
    "allowed_job_functions",
    "allowed_seniorities",
    "last_alignment_error",
    "application_result",
    "deadline",
)

# Policy inputs for enum validation. They are never persisted as columns.
_JOB_UPDATE_CONSTRAINT_PARAMETERS = (
    "allowed_job_functions",
    "allowed_seniorities",
)


def _collect_job_update_fields(scope: dict[str, Any]) -> dict[str, Any]:
    """Snapshot ``update_job`` parameters plus enum-validation policy inputs."""
    fields = {name: scope[name] for name in _JOB_UPDATE_PARAMETERS}
    fields.update(
        {name: scope[name] for name in _JOB_UPDATE_CONSTRAINT_PARAMETERS}
    )
    return fields


_JOB_UPDATE_SIMPLE_FIELDS = (
    ("title", "title", lambda _store, value: value.strip() or "未命名岗位"),
    ("jd_text", "jd_text", lambda _store, value: value.strip()),
    ("company", "company", None),
    ("location", "location", None),
    ("salary_min", "salary_min", None),
    ("salary_max", "salary_max", None),
    ("salary_currency", "salary_currency", None),
    ("source_type", "source_type", None),
    ("source_url", "source_url", None),
    ("job_function", "job_function", None),
    ("seniority", "seniority", None),
    ("status", "status", None),
    ("classification_pending", "classification_pending", None),
    ("final_draft", "final_draft", None),
    ("final_draft_updated_at", "final_draft_updated_at", None),
    ("final_draft_version", "final_draft_version", None),
    ("posting_date", "posting_date", None),
    ("match_stale", "match_stale", None),
    ("match_score", "match_score", None),
    ("match_reason", "match_reason", None),
    ("match_updated_at", "match_updated_at", None),
    ("alignment_status", "alignment_status", None),
    ("draft", "draft", None),
    ("model", "model", None),
    ("prompt_version", "prompt_version", None),
    ("generated_at", "generated_at", None),
    ("workbench_job_id", "workbench_job_id", None),
    ("workbench_resume_id", "workbench_resume_id", None),
    ("tailor_granularity", "tailor_granularity", None),
    ("tailor_focus", "tailor_focus", None),
    ("custom_prompt", "custom_prompt", None),
    ("last_alignment_error", "last_alignment_error", None),
)

_JOB_UPDATE_JSON_FIELDS = (
    (
        "tech_tags",
        "tech_tags",
        lambda store, value: json.dumps(
            store._normalize_tags(value), ensure_ascii=False
        ),
    ),
    ("jd_profile", "jd_profile_json", lambda _store, value: json.dumps(
        value, ensure_ascii=False
    )),
    ("gap_report", "gap_report_json", lambda _store, value: json.dumps(
        value, ensure_ascii=False
    )),
    (
        "match_score_detail",
        "match_score_detail_json",
        lambda _store, value: json.dumps(value, ensure_ascii=False),
    ),
    ("diffs", "diffs_json", lambda _store, value: json.dumps(
        value, ensure_ascii=False
    )),
    ("invalid_diffs", "invalid_diffs_json", lambda _store, value: json.dumps(
        value, ensure_ascii=False
    )),
    ("eval_score", "eval_score_json", lambda _store, value: json.dumps(
        value, ensure_ascii=False
    )),
)

_JOB_UPDATE_CLEARABLE_FIELDS = (
    ("applied_at", "applied_at"),
    ("next_step", "next_step"),
    ("notes", "notes"),
    ("offer_at", "offer_at"),
    ("rejected_at", "rejected_at"),
    ("next_step_due_at", "next_step_due_at"),
    ("interview_stage", "interview_stage"),
    ("application_result", "application_result"),
    ("deadline", "deadline"),
)


def _validate_job_update(fields: dict[str, Any]) -> None:
    functions = _effective_choices(
        JOB_FUNCTIONS, fields.get("allowed_job_functions")
    )
    seniorities = _effective_choices(
        SENIORITIES, fields.get("allowed_seniorities")
    )
    job_function = fields.get("job_function")
    if job_function is not None and job_function not in functions:
        raise UserStoreError(f"Invalid job_function: {job_function}")
    seniority = fields.get("seniority")
    if seniority is not None and seniority not in seniorities:
        raise UserStoreError(f"Invalid seniority: {seniority}")
    if fields.get("status") is not None:
        fields["status"] = canonical_status(_validate_status(fields["status"]))
    classification_pending = fields.get("classification_pending")
    if (
        classification_pending is not None
        and classification_pending not in (0, 1)
    ):
        raise UserStoreError("classification_pending must be 0 or 1")
    final_draft = fields.get("final_draft")
    if final_draft is not None and not final_draft.strip():
        raise UserStoreError("Final draft cannot be empty")
    tailor_granularity = fields.get("tailor_granularity")
    if (
        tailor_granularity is not None
        and tailor_granularity not in TAILOR_GRANULARITIES
    ):
        raise UserStoreError(
            f"Invalid tailor_granularity: {tailor_granularity}"
        )
    tailor_focus = fields.get("tailor_focus")
    if tailor_focus is not None and tailor_focus not in TAILOR_FOCUSES:
        raise UserStoreError(f"Invalid tailor_focus: {tailor_focus}")
    if fields.get("custom_prompt") is not None:
        fields["custom_prompt"] = fields["custom_prompt"].strip()
    match_stale = fields.get("match_stale")
    if match_stale is not None and match_stale not in (0, 1):
        raise UserStoreError("match_stale must be 0 or 1")
    application_result = fields.get("application_result")
    if (
        application_result is not None
        and application_result != ""
        and application_result not in APPLICATION_RESULTS
    ):
        raise UserStoreError(
            f"Invalid application_result: {application_result}"
        )
    jd_text = fields.get("jd_text")
    if jd_text is not None and not jd_text.strip():
        raise UserStoreError("Job description text cannot be empty")
    alignment_status = fields.get("alignment_status")
    if alignment_status is not None and alignment_status not in (
        "idle",
        "queued",
        "running",
        "succeeded",
        "failed",
    ):
        raise UserStoreError(f"Invalid alignment_status: {alignment_status}")


def _resolve_job_update_lifecycle(
    store: "JobLibraryStore",
    tenant_id: str,
    job_id: str,
    fields: dict[str, Any],
) -> tuple[bool, str | None, bool]:
    """Resolve status transitions and return ``(append_only, applied_at, found)``."""
    status = fields.get("status")
    if status is None:
        return False, None, True
    current = store.get_job(tenant_id, job_id)
    if current is None:
        return False, None, False
    if (
        canonical_status(status) == "applied"
        and canonical_status(current["status"]) != "draft"
    ):
        return (
            True,
            fields.get("applied_at")
            or current.get("applied_at")
            or time.strftime("%Y-%m-%d"),
            True,
        )
    lifecycle = status_lifecycle_fields(
        current,
        status,
        provided={
            "applied_at": fields.get("applied_at"),
            "offer_at": fields.get("offer_at"),
            "rejected_at": fields.get("rejected_at"),
            "next_step": fields.get("next_step"),
            "next_step_due_at": fields.get("next_step_due_at"),
            "interview_stage": fields.get("interview_stage"),
        },
    )
    for field, value in lifecycle.items():
        if field in fields:
            fields[field] = value
    return False, None, True


def _build_job_update_assignments(
    store: "JobLibraryStore",
    fields: dict[str, Any],
    *,
    skip_status: bool,
) -> tuple[list[str], list[Any]]:
    sets = ["updated_at = ?"]
    values: list[Any] = [time.time()]
    for field, column, converter in _JOB_UPDATE_SIMPLE_FIELDS:
        value = fields.get(field)
        if value is None or (field == "status" and skip_status):
            continue
        if converter is not None:
            value = converter(store, value)
        sets.append(f"{column} = ?")
        values.append(value)
    for field, column, converter in _JOB_UPDATE_JSON_FIELDS:
        value = fields.get(field)
        if value is None:
            continue
        sets.append(f"{column} = ?")
        values.append(converter(store, value))
    for field, column in _JOB_UPDATE_CLEARABLE_FIELDS:
        value = fields.get(field)
        if value is None:
            continue
        if value == "":
            sets.append(f"{column} = NULL")
        else:
            sets.append(f"{column} = ?")
            values.append(value)
    return sets, values

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
    status TEXT NOT NULL DEFAULT 'draft',
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
    application_result TEXT,
    deadline TEXT,
    interview_stage TEXT,
    match_stale INTEGER NOT NULL DEFAULT 0,
    workbench_job_id TEXT,
    workbench_resume_id TEXT,
    tailor_granularity TEXT,
    tailor_focus TEXT,
    custom_prompt TEXT,
    jd_profile_json TEXT,
    gap_report_json TEXT,
    match_score REAL,
    match_score_detail_json TEXT,
    match_reason TEXT,
    match_updated_at REAL,
    alignment_status TEXT NOT NULL DEFAULT 'idle',
    last_alignment_error TEXT,
    diffs_json TEXT NOT NULL DEFAULT '[]',
    invalid_diffs_json TEXT NOT NULL DEFAULT '[]',
    usable_diffs INTEGER NOT NULL DEFAULT 0,
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


def _parse_due_datetime(value: str | None) -> datetime | None:
    """Parse a stored follow-up due value into an aware/local datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _due_timestamp(value: str | None) -> float | None:
    parsed = _parse_due_datetime(value)
    return parsed.timestamp() if parsed is not None else None


def _due_date_key(value: str | None) -> str | None:
    parsed = _parse_due_datetime(value)
    return parsed.date().isoformat() if parsed is not None else None


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
        (
            35,
            "ALTER TABLE library_jobs ADD COLUMN "
            "match_stale INTEGER NOT NULL DEFAULT 0",
        ),
        (37, "ALTER TABLE library_jobs ADD COLUMN match_score_detail_json TEXT"),
        (38, "ALTER TABLE library_jobs ADD COLUMN match_reason TEXT"),
        (39, "ALTER TABLE library_jobs ADD COLUMN match_updated_at REAL"),
        # Phase 3 (2026-08-30): durable failure reason so a failed alignment
        # stays diagnosable after the in-memory registry restarts. Version 42
        # (40/41 were used by removed refresh/reminder migrations already
        # applied to existing databases).
        (
            42,
            "ALTER TABLE library_jobs ADD COLUMN last_alignment_error TEXT",
        ),
        # 43: 对齐质量度量（采纳率）+ 投递结果归因（验证对齐是否有效的
        # 闭环数据）。metrics 按 tenant+日聚合，模仿 llm_daily_usage 的
        # 原子 upsert 模式；归因枚举见 APPLICATION_RESULTS。
        (
            43,
            "CREATE TABLE IF NOT EXISTS alignment_metrics ("
            "tenant_id TEXT NOT NULL, metric_date TEXT NOT NULL, "
            "runs INTEGER NOT NULL DEFAULT 0, saves INTEGER NOT NULL DEFAULT 0, "
            "diffs_total INTEGER NOT NULL DEFAULT 0, "
            "diffs_accepted INTEGER NOT NULL DEFAULT 0, "
            "updated_at REAL NOT NULL, PRIMARY KEY (tenant_id, metric_date)); "
            "ALTER TABLE library_jobs ADD COLUMN application_result TEXT;",
        ),
        # 44: 岗位截止日期（校招生死线）。DATE 文本列，clear-on-empty 与
        # next_step_due_at 一致；复盘页与看板「近 7 天截止」筛选消费。
        (
            44,
            "ALTER TABLE library_jobs ADD COLUMN deadline TEXT;",
        ),
        # 45（#111 / ADR-0041 决定 5）：usable_diffs 计数——noop 过滤与 #74
        # 门禁之后的有效 diff 数（无新状态）。驾驶舱「完成对齐」分子只数
        # usable≥1；有缺口 usable=0 的分型（failed + no_output）由调用方
        # 写前决策。存量按 diffs_json 长度回填（#110 实测：现库零-diff
        # succeeded 全属无缺口型，回填不改变其徽章语义）。
        (
            45,
            "ALTER TABLE library_jobs ADD COLUMN usable_diffs INTEGER "
            "NOT NULL DEFAULT 0; "
            "UPDATE library_jobs "
            "SET usable_diffs = json_array_length(diffs_json);",
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
        status: str = "draft",
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
        status = canonical_status(_validate_status(status))
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
                return self._row_to_library_job(row) if row else None

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
                return self._row_to_library_job(row) if row else None

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
        sort: str = "updated_at_desc",
    ) -> list[dict[str, Any]]:
        sort = sort or "updated_at_desc"
        if sort not in {
            "updated_at_desc",
            "updated_at_asc",
            "match_score_desc",
            "match_score_asc",
        }:
            raise UserStoreError(f"Invalid sort: {sort}")
        order_by = {
            "updated_at_desc": "updated_at DESC",
            "updated_at_asc": "updated_at ASC",
            "match_score_desc": "match_score IS NULL, match_score DESC",
            "match_score_asc": "match_score ASC",
        }[sort]
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
            + f" ORDER BY {order_by}"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(sql, values).fetchall()
                return [self._row_to_library_job(row) for row in rows]

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
        match_stale: int | None = None,
        jd_profile: dict[str, Any] | None = None,
        gap_report: dict[str, Any] | None = None,
        match_score: float | None = None,
        match_score_detail: dict[str, Any] | None = None,
        match_reason: str | None = None,
        match_updated_at: float | None = None,
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
        last_alignment_error: str | None = None,
        application_result: str | None = None,
        deadline: str | None = None,
    ) -> Optional[dict[str, Any]]:
        """Update editable fields. None-valued fields are left unchanged.

        Timeline fields (``applied_at``, ``next_step``, ``notes``,
        ``offer_at``, ``rejected_at``, ``next_step_due_at``,
        ``interview_stage``) follow the clear-on-empty contract: an empty
        string clears the stored value to NULL (U10), while None leaves it
        untouched.
        """
        updates = _collect_job_update_fields(locals())
        _validate_job_update(updates)
        append_only_snapshot, snapshot_applied_at, lifecycle_found = (
            _resolve_job_update_lifecycle(
                self, tenant_id, job_id, updates
            )
        )
        if not lifecycle_found:
            return None
        sets, values = _build_job_update_assignments(
            self, updates, skip_status=append_only_snapshot
        )
        dedupe_fields = (
            updates.get("jd_text"),
            updates.get("source_type"),
            updates.get("source_url"),
        )
        if not self._persist_job_update(
            tenant_id,
            job_id,
            sets,
            values,
            recompute_dedupe=any(value is not None for value in dedupe_fields),
            jd_text=dedupe_fields[0],
            source_type=dedupe_fields[1],
            source_url=dedupe_fields[2],
            append_only_snapshot=append_only_snapshot,
            snapshot_applied_at=snapshot_applied_at,
            status=updates.get("status"),
        ):
            return None
        return self.get_job(tenant_id, job_id)

    def _persist_job_update(
        self,
        tenant_id: str,
        job_id: str,
        sets: list[str],
        values: list[Any],
        *,
        recompute_dedupe: bool,
        jd_text: str | None,
        source_type: str | None,
        source_url: str | None,
        append_only_snapshot: bool,
        snapshot_applied_at: str | None,
        status: str | None,
    ) -> bool:
        """Write one job update and any applied-snapshot row atomically."""
        should_snapshot = append_only_snapshot or (
            status is not None and canonical_status(status) == "applied"
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
                    return False
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
        return True

    @staticmethod
    def _bump_alignment_metrics(
        conn: sqlite3.Connection,
        tenant_id: str,
        runs: int = 0,
        saves: int = 0,
        diffs_total: int = 0,
        diffs_accepted: int = 0,
    ) -> None:
        """Atomically upsert today's alignment quality counters."""
        metric_date = time.strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO alignment_metrics ("
            "tenant_id, metric_date, runs, saves, diffs_total, "
            "diffs_accepted, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(tenant_id, metric_date) DO UPDATE SET "
            "runs = runs + excluded.runs, "
            "saves = saves + excluded.saves, "
            "diffs_total = diffs_total + excluded.diffs_total, "
            "diffs_accepted = diffs_accepted + excluded.diffs_accepted, "
            "updated_at = excluded.updated_at",
            (
                tenant_id,
                metric_date,
                runs,
                saves,
                diffs_total,
                diffs_accepted,
                time.time(),
            ),
        )

    def record_alignment_run(self, tenant_id: str) -> None:
        """Count one alignment run that produced a result (metric A)."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                self._bump_alignment_metrics(conn, tenant_id, runs=1)

    def alignment_quality_summary(
        self, tenant_id: str, days: int = 7
    ) -> dict[str, Any]:
        """Aggregate the last ``days`` days of adoption metrics.

        ``adoption_ratio`` is accepted/total over saved drafts; None when no
        diffs were saved in the window (zero denominators are reported, not
        faked as 100%).
        """
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT runs, saves, diffs_total, diffs_accepted "
                    "FROM alignment_metrics WHERE tenant_id = ? "
                    "AND metric_date >= ?",
                    (
                        tenant_id,
                        time.strftime(
                            "%Y-%m-%d", time.localtime(time.time() - days * 86400)
                        ),
                    ),
                ).fetchall()
        totals = {
            "runs": sum(int(r["runs"] or 0) for r in rows),
            "saves": sum(int(r["saves"] or 0) for r in rows),
            "diffs_total": sum(int(r["diffs_total"] or 0) for r in rows),
            "diffs_accepted": sum(int(r["diffs_accepted"] or 0) for r in rows),
        }
        totals["window_days"] = days
        totals["adoption_ratio"] = (
            round(totals["diffs_accepted"] / totals["diffs_total"], 3)
            if totals["diffs_total"]
            else None
        )
        return totals

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
                # 采纳率埋点：save_final_draft 是唯一同时拿得到分子（accepted）
                # 与分母（diffs 总数）的持久化点；与定稿写入同事务。
                self._bump_alignment_metrics(
                    conn,
                    tenant_id,
                    saves=1,
                    diffs_total=len(diffs),
                    diffs_accepted=sum(
                        1 for diff in diffs
                        if diff.get("provenance_state") == "accepted"
                    ),
                )
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
        match_score_detail: dict[str, Any] | None = None,
        match_reason: str | None = None,
        match_updated_at: float | None = None,
        diffs: list[dict[str, Any]] | None = None,
        invalid_diffs: list[dict[str, Any]] | None = None,
        draft: str | None = None,
        eval_score: dict[str, Any] | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
        alignment_status: str = "succeeded",
        last_alignment_error: str | None = None,
        usable_diffs: int | None = None,
    ) -> Optional[dict[str, Any]]:
        """Persist a terminal alignment product for one library job.

        ``last_alignment_error`` doubles as a hint field on succeeded runs:
        a degraded tailor pass writes the reason here so the UI can show
        "诊断完成 · 改写未产出" instead of a bare zero-diff success. Pass
        None on normal runs to clear any stale hint.

        ``usable_diffs`` (#111 / ADR-0041 决定 5): count of diffs that survive
        the noop filter and #74 gate — defaults to ``len(diffs)`` because
        callers pass only kept diffs here; the caller may pass an explicit
        value when it also knows about blocked output.
        """
        if alignment_status not in (
            "idle",
            "queued",
            "running",
            "succeeded",
            "failed",
        ):
            raise UserStoreError(f"Invalid alignment_status: {alignment_status}")
        usable = len(diffs or []) if usable_diffs is None else int(usable_diffs)
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
                    "match_score = ?, match_score_detail_json = ?, "
                    "match_reason = ?, match_updated_at = ?, "
                    "alignment_status = ?, last_alignment_error = ?, "
                    "diffs_json = ?, invalid_diffs_json = ?, "
                    "usable_diffs = ?, draft = ?, "
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
                        (
                            json.dumps(match_score_detail, ensure_ascii=False)
                            if match_score_detail is not None
                            else None
                        ),
                        match_reason,
                        match_updated_at,
                        alignment_status,
                        last_alignment_error,
                        json.dumps(diffs or [], ensure_ascii=False),
                        json.dumps(invalid_diffs or [], ensure_ascii=False),
                        usable,
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
                return [self._row_to_library_job(row) for row in rows]

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
        status = canonical_status(_validate_status(status))
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
                                "job": self._row_to_library_job(row),
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
                                "job": self._row_to_library_job(row),
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
                                "job": self._row_to_library_job(row),
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
                            "job": self._row_to_library_job(updated_row),
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
        """Delete a library job and its pinned analysis job.

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
    def _row_to_library_job(row: sqlite3.Row) -> dict[str, Any]:
        tags = json.loads(row["tech_tags"] or "[]")
        alignment_status = row["alignment_status"] or "idle"
        try:
            match_score_detail = (
                json.loads(row["match_score_detail_json"])
                if row["match_score_detail_json"]
                else None
            )
        except (TypeError, ValueError):
            match_score_detail = None
        # #111 / ADR-0041 决定 5：usable_diffs 是持久列；has_gap 与
        # alignment_reason 由投影派生（无新状态）——no_gap=无缺口零产出、
        # no_output=有缺口零产出（后者终态即 failed，理由前缀在
        # last_alignment_error）。前端徽章/驾驶舱分子据此分型，不再以
        # alignment_status 单字段当「已对齐」绿灯。
        usable_diffs = int(row["usable_diffs"] or 0)
        try:
            gap_report = (
                json.loads(row["gap_report_json"])
                if row["gap_report_json"]
                else None
            )
        except (TypeError, ValueError):
            gap_report = None
        has_gap = bool(gap_report) and bool(
            (gap_report.get("missing_keywords") or [])
            or (gap_report.get("misaligned_emphasis") or [])
        )
        last_error = row["last_alignment_error"] or ""
        if alignment_status == "succeeded" and usable_diffs == 0 and not has_gap:
            alignment_reason: str | None = "no_gap"
        elif alignment_status == "failed" and last_error.startswith("no_output"):
            alignment_reason = "no_output"
        else:
            alignment_reason = None
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
            "application_result": row["application_result"] or None,
            "deadline": row["deadline"] or None,
            "match_stale": bool(row["match_stale"]),
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
            "match_score_detail": match_score_detail,
            "match_reason": row["match_reason"] or None,
            "match_updated_at": row["match_updated_at"],
            "alignment_status": alignment_status,
            "last_alignment_error": row["last_alignment_error"] or None,
            "diffs": json.loads(row["diffs_json"] or "[]"),
            "invalid_diffs": json.loads(row["invalid_diffs_json"] or "[]"),
            "usable_diffs": usable_diffs,
            "has_gap": has_gap,
            "alignment_reason": alignment_reason,
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

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_JOB_LIBRARY_SCHEMA)


# ---------------------------------------------------------------------------
# Automation rules (Sprint 3 pipeline)
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


