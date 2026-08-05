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
    }


class SettingsStore(_SqliteStore):
    """Store and validate editable user preferences for the workbench."""

    MIGRATIONS = (
        (1, "ALTER TABLE user_settings ADD COLUMN llm_provider TEXT"),
        (2, "ALTER TABLE user_settings ADD COLUMN llm_model TEXT"),
    )

    def get_settings(self, tenant_id: str) -> dict[str, Any]:
        defaults = default_settings()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT salary_reference_json, appraisal_weights_json, "
                    "classification_vocabulary_json, llm_provider, llm_model "
                    "FROM user_settings "
                    "WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
        if row is None:
            return defaults
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
            "llm_provider": row["llm_provider"],
            "llm_model": row["llm_model"],
        }
        return _merge_defaults(defaults, settings)

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
                    "llm_provider, llm_model, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(tenant_id) DO UPDATE SET "
                    "salary_reference_json = excluded.salary_reference_json, "
                    "appraisal_weights_json = "
                    "excluded.appraisal_weights_json, "
                    "classification_vocabulary_json = "
                    "excluded.classification_vocabulary_json, "
                    "llm_provider = excluded.llm_provider, "
                    "llm_model = excluded.llm_model, "
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
                        merged.get("llm_provider"),
                        merged.get("llm_model"),
                        now,
                    ),
                )
        return self.get_settings(tenant_id)

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_SETTINGS_SCHEMA)


def _merge_defaults(
    defaults: dict[str, Any], updates: dict[str, Any]
) -> dict[str, Any]:
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
        "llm_provider": updates.get(
            "llm_provider", defaults.get("llm_provider")
        ),
        "llm_model": updates.get("llm_model", defaults.get("llm_model")),
    }
    return merged


def _validate_settings(settings: dict[str, Any]) -> None:
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
