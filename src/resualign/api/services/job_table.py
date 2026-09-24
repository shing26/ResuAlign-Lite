"""Auto-sync the WorkBuddy job table (a growing daily CSV) into the library.

The user keeps one CSV that WorkBuddy appends to every day and a folder of JD
markdown bodies. This module reads that CSV from the server filesystem,
inlines each row's JD body when the CSV only references a file, and hands the
rows to the existing import pipeline (so the dedupe and preanalyze contracts
are exactly the ones the manual import uses).

A daemon loop (started from the API lifespan, same shape as the job watchdog)
re-runs the sync for tenants that enabled it, so the library catches up on new
rows without a manual import.
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ...app.context import context
from ...job_library import (
    _dedupe_key_for,
    _job_identity_key,
    _parse_salary_text,
    _text_dedupe_key,
)

logger = logging.getLogger(__name__)

SCAN_INTERVAL_S = 60
MAX_JOB_TABLE_BYTES = 8 * 1024 * 1024
_ALLOWED_SUFFIXES = (".csv", ".txt")

# Header aliases → canonical import fields. ResuAlign's own export columns win
# first so an already-converted file can be pointed at directly.
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("title", "岗位", "职位", "职位名称"),
    "company": ("company", "公司", "公司名称", "企业"),
    "location": ("location", "地点", "城市", "工作地点"),
    "salary": ("salary", "薪资", "薪水", "工资"),
    "salary_min": ("salary_min",),
    "salary_max": ("salary_max",),
    "jd_url": ("jd_url", "url", "投递入口", "投递链接", "链接"),
    "jd_text": ("jd_text", "jd", "职位描述", "岗位描述", "jd文本"),
    "jd_file": ("JD文件", "jd_file", "jd文件", "jd路径"),
}

class JobTableError(Exception):
    """The job table is not configured, not readable, or rejected by policy."""


def _header_lookup(fieldnames: list[str]) -> dict[str, str]:
    """Map canonical fields to the CSV's actual header names."""
    normalized = {
        (name or "").strip().lower(): name
        for name in fieldnames
        if (name or "").strip()
    }
    lookup: dict[str, str] = {}
    for field, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            actual = normalized.get(alias.lower())
            if actual is not None:
                lookup[field] = actual
                break
    return lookup


def _parse_salary(text: str | None) -> tuple[int | None, int | None]:
    """Best-effort parse of '4-6K/月' / '20-30K' style salary strings."""
    return _parse_salary_text(text)


def _normalize_url(raw: str | None) -> str:
    """Return a usable http(s) URL, or '' when the cell is not one."""
    value = (raw or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if "." in value and " " not in value:
        return "https://" + value
    return ""


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _job_table_dedupe_key(
    *, company: str, title: str, location: str
) -> str:
    """Stable identity for rows that carry no usable application URL.

    WorkBuddy rewrites the JD markdown body when a posting changes, so the
    generic text hash would mint a new row for an existing posting. Hashing
    company/title/location keeps the identity stable across body edits; a real
    application URL still wins because it is the strongest signal.
    """
    identity = _job_identity_key(company, title, location)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return "jobtable:" + digest


def _allowed_root() -> Path | None:
    raw = os.environ.get("RESUALIGN_JOB_TABLE_ROOT", "").strip()
    if not raw:
        return None
    try:
        return Path(raw).expanduser().resolve()
    except OSError:  # pragma: no cover - defensive
        return None


def resolve_job_table_path(raw: str | None) -> Path:
    """Validate a configured CSV path and return it, or raise JobTableError.

    Server-side file reads are a local-disk disclosure primitive if a tenant
    can point at any path, so multi-tenant deployments must declare
    ``RESUALIGN_JOB_TABLE_ROOT`` and stay inside it. Personal mode (the
    single-user desktop default) trusts the local user.
    """
    value = _text(raw).strip('"')
    if not value:
        raise JobTableError("尚未配置岗位表路径")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise JobTableError("岗位表路径必须是绝对路径")
    if path.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise JobTableError("岗位表必须是 .csv 或 .txt 文件")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise JobTableError(f"岗位表文件不存在或不可读：{path}") from exc
    if not resolved.is_file():
        raise JobTableError(f"岗位表路径不是文件：{resolved}")
    try:
        size = resolved.stat().st_size
    except OSError as exc:  # pragma: no cover - defensive
        raise JobTableError(f"岗位表文件不可读：{resolved}") from exc
    if size > MAX_JOB_TABLE_BYTES:
        raise JobTableError(
            f"岗位表超过 {MAX_JOB_TABLE_BYTES // (1024 * 1024)} MB 上限"
        )
    if not getattr(context, "_PERSONAL_MODE", True):
        root = _allowed_root()
        if root is None or not resolved.is_relative_to(root):
            raise JobTableError(
                "多租户部署需要设置 RESUALIGN_JOB_TABLE_ROOT，"
                "且岗位表必须位于该目录内"
            )
    return resolved


def _resolve_jd_body(
    reference: str,
    *,
    csv_dir: Path,
    jd_dir: Path | None,
) -> str:
    """Read a referenced JD markdown file, returning '' when unavailable."""
    value = _text(reference)
    if not value:
        return ""
    candidates = [Path(value)]
    if jd_dir is not None:
        candidates.append(jd_dir / Path(value).name)
    candidates.append(csv_dir / value)
    for candidate in candidates:
        target = candidate if candidate.is_absolute() else csv_dir / candidate
        try:
            if target.is_file():
                return target.read_text(
                    encoding="utf-8-sig", errors="replace"
                ).strip()
        except OSError:  # pragma: no cover - defensive
            continue
    return ""


def normalize_job_table_row(
    raw: dict[str, Any],
    *,
    lookup: dict[str, str],
    csv_dir: Path,
    jd_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Convert one CSV row into an import payload, or None when unusable."""
    def cell(field: str) -> Any:
        header = lookup.get(field)
        return raw.get(header) if header else None

    title = _text(cell("title"))
    company = _text(cell("company"))
    location = _text(cell("location"))
    jd_url = _normalize_url(_text(cell("jd_url")))
    jd_text = _text(cell("jd_text"))
    if not jd_text:
        jd_text = _resolve_jd_body(
            _text(cell("jd_file")),
            csv_dir=csv_dir,
            jd_dir=jd_dir,
        )
    if not jd_text:
        return None
    if not title:
        # Match what _create_job_from_source would store, so the stable
        # identity here equals the identity of the row that gets written.
        title = context._derive_title(jd_text)
    salary_min = _coerce_int(cell("salary_min"))
    salary_max = _coerce_int(cell("salary_max"))
    if salary_min is None and salary_max is None:
        salary_min, salary_max = _parse_salary(_text(cell("salary")))
    payload: dict[str, Any] = {
        "title": title,
        "company": company or None,
        "location": location or None,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "jd_text": jd_text,
    }
    if jd_url:
        payload["jd_url"] = jd_url
        payload["source_type"] = "url"
        payload["source_url"] = jd_url
    else:
        payload["source_type"] = "paste"
        payload["dedupe_key"] = _job_table_dedupe_key(
            company=company, title=title, location=location
        )
    return payload


def read_job_table_rows(
    table_path: Path,
    *,
    jd_dir: Path | None = None,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Read the job table and return import payloads for usable rows.

    ``stats`` (when given) is filled with the raw row counts so callers can
    tell the user why a 100-row table produced fewer imports: WorkBuddy adds a
    row before the JD markdown exists, and those rows carry no JD body yet.
    """
    try:
        text = table_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise JobTableError(f"岗位表读取失败：{exc}") from exc
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])
    lookup = _header_lookup(fieldnames)
    if not {"title", "jd_text", "jd_file"} & set(lookup):
        raise JobTableError(
            "无法识别岗位表表头：至少需要 title/岗位、jd_text 或 JD文件 列"
        )
    rows: list[dict[str, Any]] = []
    total = 0
    for raw in reader:
        total += 1
        payload = normalize_job_table_row(
            dict(raw),
            lookup=lookup,
            csv_dir=table_path.parent,
            jd_dir=jd_dir,
        )
        if payload is not None:
            rows.append(payload)
    if stats is not None:
        stats["total_rows"] = total
        stats["importable_rows"] = len(rows)
        stats["missing_jd"] = total - len(rows)
    return rows


def read_job_table(
    config: dict[str, Any],
    *,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Resolve the configured paths and return the importable rows."""
    table_path = resolve_job_table_path(config.get("path"))
    jd_dir_raw = _text(config.get("jd_dir"))
    jd_dir: Path | None = None
    if jd_dir_raw:
        candidate = Path(jd_dir_raw.strip('"')).expanduser()
        if not candidate.is_absolute():
            candidate = table_path.parent / candidate
        jd_dir = candidate
    return read_job_table_rows(table_path, jd_dir=jd_dir, stats=stats)


def job_table_config(user: dict[str, Any]) -> dict[str, Any]:
    """Return the stored job-table config for one tenant."""
    settings = context._settings_store.get_settings(user["user_id"])
    return dict(settings.get("job_table") or {})


def queue_job_rows(
    user: dict[str, Any],
    rows: list[dict[str, Any]],
    *,
    preanalyze: bool,
) -> dict[str, Any]:
    """Hand rows to the shared import worker, mirroring POST /api/jobs/import."""
    import_id = uuid.uuid4().hex
    context._import_batches[import_id] = {
        "user_id": user["user_id"],
        "rows": rows,
        "created": 0,
        "skipped": 0,
        "errors": [],
        "done": False,
        "preanalyze": bool(preanalyze),
        "analyzed": 0,
        "job_ids": [],
        "analyze_errors": [],
    }
    threading.Thread(
        target=context._run_import, args=(import_id,), daemon=True
    ).start()
    return {
        "queued": True,
        "import_id": import_id,
        "total": len(rows),
        "created": 0,
        "skipped": 0,
        "errors": [],
    }


def _record_sync_result(
    user_id: str,
    *,
    status: str,
    detail: str = "",
    total: int = 0,
    import_id: str | None = None,
) -> None:
    """Persist the last sync outcome so the UI can show what happened."""
    result = {
        "status": status,
        "detail": detail,
        "total": total,
        "import_id": import_id,
        "at": time.time(),
    }
    try:
        context._settings_store.update_settings(
            user_id,
            {
                "job_table": {
                    "last_sync_at": result["at"],
                    "last_result": result,
                }
            },
        )
    except Exception:  # pragma: no cover - reporting must never raise
        logger.exception("Failed to record job-table sync result")


def sync_job_table(user: dict[str, Any]) -> dict[str, Any]:
    """Read the configured job table and queue the new rows.

    Raises JobTableError (mapped to 422 by the router) when the table cannot be
    read. Duplicate rows are handled by the import worker's dedupe check, so a
    re-sync of an unchanged table costs no LLM calls.
    """
    config = job_table_config(user)
    stats: dict[str, int] = {}
    try:
        rows = read_job_table(config, stats=stats)
    except JobTableError as exc:
        _record_sync_result(user["user_id"], status="error", detail=str(exc))
        raise
    missing_jd = stats.get("missing_jd", 0)
    suffix = f"（另有 {missing_jd} 行缺少 JD 正文，未导入）" if missing_jd else ""
    rows, already_present = _drop_known_rows(user["user_id"], rows)
    if not rows:
        detail = (
            f"岗位表没有新行（{already_present} 行已在库中）{suffix}"
            if already_present
            else f"岗位表没有可导入的行{suffix}"
        )
        _record_sync_result(user["user_id"], status="empty", detail=detail)
        return {"queued": False, "total": 0, "created": 0, "skipped": 0,
                "already_present": already_present, "errors": [detail]}
    if len(rows) > context._MAX_IMPORT_ROWS:
        detail = f"岗位表超过 {context._MAX_IMPORT_ROWS} 行上限"
        _record_sync_result(user["user_id"], status="error", detail=detail)
        raise JobTableError(detail)
    queued = queue_job_rows(
        user, rows, preanalyze=bool(config.get("preanalyze"))
    )
    queued["already_present"] = already_present
    _record_sync_result(
        user["user_id"],
        status="queued",
        detail=(
            f"已提交 {len(rows)} 行，{already_present} 行已在库中{suffix}"
            if already_present
            else f"已提交 {len(rows)} 行{suffix}"
        ),
        total=len(rows),
        import_id=queued["import_id"],
    )
    return queued


def _drop_known_rows(
    tenant_id: str, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int]:
    """Split off rows the library already owns.

    Rows without an application URL carry the ADR-0055 stable identity, but
    rows imported before that ADR are keyed by their JD text hash. Checking
    the key, the legacy text hash, and the normalized company/title/location
    identity keeps the first post-upgrade sync from re-adding existing non-URL
    rows just because their identity scheme changed — including rows whose JD
    body WorkBuddy rewrote in the meantime (that is why the identity check
    exists at all).
    """
    store = context._jobs
    identities = store.list_job_identity_keys(tenant_id)
    fresh: list[dict[str, Any]] = []
    already = 0
    for row in rows:
        stable_key = row.get("dedupe_key")
        key = stable_key or _dedupe_key_for(
            row.get("source_type"),
            row.get("source_url"),
            str(row.get("jd_text") or ""),
        )
        known = store.find_by_dedupe_key(tenant_id, key) is not None
        if not known and stable_key:
            legacy_key = _text_dedupe_key(str(row.get("jd_text") or ""))
            known = store.find_by_dedupe_key(tenant_id, legacy_key) is not None
            if not known:
                known = (
                    _job_identity_key(
                        row.get("company"),
                        row.get("title"),
                        row.get("location"),
                    )
                    in identities
                )
        if known:
            already += 1
        else:
            fresh.append(row)
    return fresh, already


def _sync_due(config: dict[str, Any], *, now: float) -> bool:
    interval_minutes = _coerce_int(config.get("interval_minutes")) or 60
    interval_s = max(interval_minutes, 1) * 60
    last = config.get("last_sync_at")
    if not isinstance(last, (int, float)):
        return True
    return (now - float(last)) >= interval_s


def sync_once(*, now: float | None = None) -> int:
    """Run every due auto-sync tenant once; returns how many were queued."""
    store = getattr(context, "_settings_store", None)
    if store is None:
        return 0
    now = time.time() if now is None else now
    queued = 0
    for tenant_id, config in store.list_job_table_auto_sync():
        if not _sync_due(config, now=now):
            continue
        try:
            sync_job_table({"user_id": tenant_id})
            queued += 1
        except Exception as exc:
            # One bad path must not stop the sweep; the next tick retries.
            logger.warning(
                "Job-table sync failed for %s: %s", tenant_id, exc
            )
    return queued


def _loop(stop: threading.Event) -> None:
    while not stop.wait(SCAN_INTERVAL_S):
        try:
            sync_once()
        except Exception:  # pragma: no cover - the loop must survive
            logger.exception("job-table sync scan failed")


def start() -> threading.Event | None:
    """Start the daemon sweep; returns its stop event, or None if disabled."""
    if os.environ.get("RESUALIGN_JOB_TABLE_SYNC", "").strip() == "0":
        return None
    stop = threading.Event()
    threading.Thread(
        target=_loop, args=(stop,), daemon=True, name="resualign-job-table"
    ).start()
    return stop
