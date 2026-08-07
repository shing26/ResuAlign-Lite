"""Per-tenant user settings persisted in SQLite."""

from __future__ import annotations

import json
import time
from typing import Any

from .appraisal import DEFAULT_WEIGHTS
from .job_library import JOB_FUNCTIONS, JOB_STATUSES, SENIORITIES
from .store_base import UserStoreError, _SqliteStore

_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_settings (
    tenant_id TEXT PRIMARY KEY,
    salary_reference_json TEXT NOT NULL DEFAULT '[]',
    appraisal_weights_json TEXT NOT NULL DEFAULT '{}',
    classification_vocabulary_json TEXT NOT NULL DEFAULT '{}',
    llm_provider TEXT,
    llm_model TEXT,
    llm_json TEXT,
    eval_default INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
"""


def default_salary_reference() -> list[dict[str, Any]]:
    """Return the built-in salary reference table (monthly CNY, p50/p75)."""
    table = [
        ("后端", "北京", 32000, 48000),
        ("后端", "上海", 30000, 45000),
        ("后端", "深圳", 30000, 46000),
        ("前端", "北京", 28000, 42000),
        ("前端", "上海", 27000, 40000),
        ("前端", "深圳", 27000, 41000),
        ("算法", "北京", 38000, 60000),
        ("算法", "上海", 36000, 55000),
        ("数据", "上海", 28000, 42000),
        ("测试", "上海", 22000, 32000),
        ("运维", "上海", 24000, 36000),
        ("产品", "上海", 26000, 38000),
        ("设计", "上海", 24000, 36000),
        ("运营", "上海", 18000, 28000),
        ("销售", "上海", 16000, 30000),
    ]
    return [
        {
            "job_function": function,
            "city": city,
            "p50": p50,
            "p75": p75,
        }
        for function, city, p50, p75 in table
    ]


def default_settings() -> dict[str, Any]:
    return {
        "salary_reference": default_salary_reference(),
        "appraisal_weights": dict(DEFAULT_WEIGHTS),
        "classification_vocabulary": {
            "job_functions": list(JOB_FUNCTIONS),
            "seniorities": list(SENIORITIES),
            "statuses": list(JOB_STATUSES),
        },
        "llm_provider": None,
        "llm_model": None,
        "eval_default": False,
        "llm": {
            "provider": None,
            "model": None,
            "api_key": None,
            "base_url": None,
        },
    }


def _repair_classification_vocabulary(
    vocabulary: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Repair the classification vocabulary against the built-in whitelists.

    ``statuses`` must be a subset of ``JOB_STATUSES``: values missing from
    the canonical five are backfilled, and any stored value outside the
    whitelist (e.g. a corrupted ``["待定", "已投递"]`` list) resets the whole
    status list to the built-in five (B1). ``job_functions``/``seniorities``
    are tenant-editable; they are only replaced when they are not usable
    (missing/empty/corrupt).

    Returns ``(repaired, changed)`` so callers can persist the repair once
    instead of re-running it on every read (idempotent self-healing).
    """
    if not isinstance(vocabulary, dict):
        return dict(default_settings()["classification_vocabulary"]), True
    builtin = default_settings()["classification_vocabulary"]
    repaired: dict[str, Any] = {}
    changed = False

    statuses = vocabulary.get("statuses")
    if isinstance(statuses, list):
        valid = [str(s) for s in statuses if str(s or "").strip() in JOB_STATUSES]
        if len(valid) != len(statuses):
            # Corrupt values present: fall back to the built-in five.
            valid = list(JOB_STATUSES)
            changed = True
        for status in JOB_STATUSES:
            if status not in valid:
                valid.append(status)
                changed = True
        repaired["statuses"] = valid
    else:
        repaired["statuses"] = list(JOB_STATUSES)
        changed = True

    for key in ("job_functions", "seniorities"):
        values = vocabulary.get(key)
        if isinstance(values, list):
            cleaned = [
                str(value)
                for value in values
                if str(value or "").strip()
            ]
            if not cleaned:
                repaired[key] = list(builtin[key])
                changed = True
            else:
                repaired[key] = cleaned
        else:
            repaired[key] = list(builtin[key])
            changed = True
    return repaired, changed


def _default_llm() -> dict[str, Any]:
    return dict(default_settings()["llm"])


class SettingsStore(_SqliteStore):
    """Store and validate editable user preferences for the workbench."""

    MIGRATIONS = (
        (1, "ALTER TABLE user_settings ADD COLUMN llm_provider TEXT"),
        (2, "ALTER TABLE user_settings ADD COLUMN llm_model TEXT"),
        (3, "ALTER TABLE user_settings ADD COLUMN llm_json TEXT"),
        (
            4,
            "ALTER TABLE user_settings ADD COLUMN "
            "eval_default INTEGER NOT NULL DEFAULT 0",
        ),
    )

    def get_settings(self, tenant_id: str) -> dict[str, Any]:
        defaults = default_settings()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT salary_reference_json, appraisal_weights_json, "
                    "classification_vocabulary_json, llm_provider, llm_model, "
                    "llm_json, eval_default "
                    "FROM user_settings "
                    "WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
        if row is None:
            return defaults
        llm = _parse_llm_json(row["llm_json"])
        # Backfill from the legacy llm_provider/llm_model columns so rows
        # written before the llm_json column existed keep working.
        if not llm.get("provider") and row["llm_provider"]:
            llm["provider"] = row["llm_provider"]
        if not llm.get("model") and row["llm_model"]:
            llm["model"] = row["llm_model"]
        settings = {
            "salary_reference": json.loads(
                row["salary_reference_json"] or "[]"
            ),
            "appraisal_weights": json.loads(
                row["appraisal_weights_json"] or "{}"
            ),
            "classification_vocabulary": json.loads(
                row["classification_vocabulary_json"] or "{}"
            ),
            "llm_provider": llm.get("provider"),
            "llm_model": llm.get("model"),
            "eval_default": bool(row["eval_default"]),
            "llm": llm,
        }
        settings = _merge_defaults(defaults, settings)
        repaired, changed = _repair_classification_vocabulary(
            settings["classification_vocabulary"]
        )
        if changed:
            # Persist the repaired vocabulary so the fix is durable without
            # a manual migration (idempotent self-healing, B1).
            settings["classification_vocabulary"] = repaired
            with self._lock:
                self._ensure_initialized()
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE user_settings SET "
                        "classification_vocabulary_json = ?, updated_at = ? "
                        "WHERE tenant_id = ?",
                        (
                            json.dumps(repaired, ensure_ascii=False),
                            time.time(),
                            tenant_id,
                        ),
                    )
        return settings

    def update_settings(
        self, tenant_id: str, updates: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge and validate partial settings updates, then persist."""
        current = self.get_settings(tenant_id)
        merged = _merge_defaults(current, updates)
        _validate_settings(merged)
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO user_settings ("
                    "tenant_id, salary_reference_json, "
                    "appraisal_weights_json, classification_vocabulary_json, "
                    "llm_provider, llm_model, llm_json, eval_default, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(tenant_id) DO UPDATE SET "
                    "salary_reference_json = excluded.salary_reference_json, "
                    "appraisal_weights_json = "
                    "excluded.appraisal_weights_json, "
                    "classification_vocabulary_json = "
                    "excluded.classification_vocabulary_json, "
                    "llm_provider = excluded.llm_provider, "
                    "llm_model = excluded.llm_model, "
                    "llm_json = excluded.llm_json, "
                    "eval_default = excluded.eval_default, "
                    "updated_at = excluded.updated_at",
                    (
                        tenant_id,
                        json.dumps(
                            merged["salary_reference"], ensure_ascii=False
                        ),
                        json.dumps(
                            merged["appraisal_weights"], ensure_ascii=False
                        ),
                        json.dumps(
                            merged["classification_vocabulary"],
                            ensure_ascii=False,
                        ),
                        merged["llm"].get("provider"),
                        merged["llm"].get("model"),
                        json.dumps(merged["llm"], ensure_ascii=False),
                        int(merged["eval_default"]),
                        now,
                    ),
                )
        return self.get_settings(tenant_id)

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_SETTINGS_SCHEMA)


def _parse_llm_json(raw: str | None) -> dict[str, Any]:
    """Parse the llm_json column, tolerating missing/corrupt values."""
    llm: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            llm = parsed
    return {key: llm.get(key) for key in _default_llm()}


def _merge_llm(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Merge llm settings with legacy llm_provider/llm_model updates.

    The ``llm`` dict (new UI) is authoritative for the keys it carries; the
    legacy top-level ``llm_provider``/``llm_model`` keys still fold in when
    the llm dict does not mention them, so older clients keep working.
    """
    merged = dict(current)
    llm_update = updates.get("llm")
    if isinstance(llm_update, dict):
        for key in merged:
            if key in llm_update:
                merged[key] = llm_update[key]
        # The llm dict is authoritative; legacy top-level keys only act as
        # aliases when they carry a real value (explicit nulls belong in the
        # llm dict).
        if "provider" not in llm_update and updates.get("llm_provider") not in (None,):
            merged["provider"] = updates["llm_provider"]
        if "model" not in llm_update and updates.get("llm_model") not in (None,):
            merged["model"] = updates["llm_model"]
    else:
        if "llm_provider" in updates:
            merged["provider"] = updates["llm_provider"]
        if "llm_model" in updates:
            merged["model"] = updates["llm_model"]
    # Normalize empty strings to None so the store keeps one canonical
    # "unset" representation and build_config can fall through to .env.
    return {key: (value if value != "" else None) for key, value in merged.items()}


def _merge_defaults(
    defaults: dict[str, Any], updates: dict[str, Any]
) -> dict[str, Any]:
    merged_llm = _merge_llm(
        defaults.get("llm") or _default_llm(), updates
    )
    eval_default = updates.get("eval_default")
    merged = {
        "salary_reference": list(
            updates.get("salary_reference", defaults["salary_reference"])
        ),
        "appraisal_weights": dict(
            defaults["appraisal_weights"],
            **updates.get("appraisal_weights", {}),
        ),
        "classification_vocabulary": {
            key: list(
                (updates.get("classification_vocabulary") or {}).get(
                    key, defaults["classification_vocabulary"].get(key, [])
                )
            )
            for key in defaults["classification_vocabulary"]
        },
        "llm_provider": merged_llm.get("provider"),
        "llm_model": merged_llm.get("model"),
        "eval_default": (
            defaults["eval_default"] if eval_default is None else eval_default
        ),
        "llm": merged_llm,
    }
    return merged


def _validate_settings(settings: dict[str, Any]) -> None:
    eval_default = settings.get("eval_default")
    if eval_default is not None and not isinstance(eval_default, bool):
        raise UserStoreError("eval_default must be a boolean")
    provider = settings.get("llm_provider")
    if provider is not None and provider not in (
        "deepseek",
        "openrouter",
        "ollama",
    ):
        raise UserStoreError(
            "llm_provider must be one of deepseek, openrouter, ollama"
        )
    model = settings.get("llm_model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise UserStoreError("llm_model must be a non-empty string")
    if model is not None and provider is None:
        raise UserStoreError("llm_provider is required when setting llm_model")

    llm = settings.get("llm") or {}
    llm_provider = llm.get("provider")
    if llm_provider is not None and llm_provider not in (
        "deepseek",
        "openrouter",
        "ollama",
    ):
        raise UserStoreError(
            "llm.provider must be one of deepseek, openrouter, ollama"
        )
    llm_model = llm.get("model")
    if llm_model is not None and (
        not isinstance(llm_model, str) or not llm_model.strip()
    ):
        raise UserStoreError("llm.model must be a non-empty string")
    if llm_model is not None and llm_provider is None:
        raise UserStoreError("llm.provider is required when setting llm.model")
    for key in ("api_key", "base_url"):
        value = llm.get(key)
        if value is not None and not isinstance(value, str):
            raise UserStoreError(f"llm.{key} must be a string or null")

    weights = settings.get("appraisal_weights") or {}
    missing = set(DEFAULT_WEIGHTS) - set(weights)
    if missing:
        raise UserStoreError(f"Missing weights: {sorted(missing)}")
    if not all(isinstance(v, (int, float)) for v in weights.values()):
        raise UserStoreError("Appraisal weights must be numbers")
    if abs(sum(weights.values()) - 100) > 1e-6:
        raise UserStoreError("Appraisal weights must sum to 100")

    reference = settings.get("salary_reference") or []
    if not isinstance(reference, list):
        raise UserStoreError("Salary reference must be a list")
    for entry in reference:
        if not isinstance(entry, dict):
            raise UserStoreError("Each salary reference row must be an object")
        if not str(entry.get("job_function") or "").strip():
            raise UserStoreError(
                "Each salary reference row needs a job_function"
            )
        if not str(entry.get("city") or "").strip():
            raise UserStoreError("Each salary reference row needs a city")
        for key in ("p50", "p75"):
            if not isinstance(entry.get(key), (int, float)):
                raise UserStoreError(
                    f"Salary reference {key} must be a number"
                )

    vocabulary = settings.get("classification_vocabulary") or {}
    for key in ("job_functions", "seniorities", "statuses"):
        values = vocabulary.get(key) or []
        if not isinstance(values, list) or not values:
            raise UserStoreError(
                f"Classification vocabulary {key} must be a non-empty list"
            )
        if any(not str(value or "").strip() for value in values):
            raise UserStoreError(
                f"Classification vocabulary {key} contains empty values"
            )
    statuses = vocabulary.get("statuses") or []
    invalid = [
        str(value)
        for value in statuses
        if str(value or "").strip() not in JOB_STATUSES
    ]
    if invalid:
        raise UserStoreError(
            "Classification vocabulary statuses contains invalid values: "
            + ", ".join(invalid)
            + f" (allowed: {', '.join(JOB_STATUSES)})"
        )
