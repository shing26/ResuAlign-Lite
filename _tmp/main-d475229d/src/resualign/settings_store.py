"""Per-tenant user settings persisted in SQLite."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

from .job_library import JOB_FUNCTIONS, JOB_STATUSES, SENIORITIES
from .store_base import UserStoreError, _SqliteStore

_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_settings (
    tenant_id TEXT PRIMARY KEY,
    classification_vocabulary_json TEXT NOT NULL DEFAULT '{}',
    llm_provider TEXT,
    llm_model TEXT,
    llm_json TEXT,
    eval_default INTEGER NOT NULL DEFAULT 0,
    local_ingest_token TEXT,
    reminder_json TEXT,
    daily_llm_cap INTEGER,
    llm_cost_per_1k_in REAL,
    llm_cost_per_1k_out REAL,
    updated_at REAL NOT NULL
);
"""


def default_settings() -> dict[str, Any]:
    return {
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
        "reminder": {
            "enabled": False,
            "auto_followup_reminder": True,
            "provider": "generic",
            "smtp_host": None,
            "smtp_port": None,
            "smtp_user": None,
            "smtp_from": None,
            "smtp_to": None,
        },
        "daily_llm_cap": None,
        "llm_cost_per_1k_in": None,
        "llm_cost_per_1k_out": None,
        "local_ingest_token": None,
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
        (
            5,
            "ALTER TABLE user_settings ADD COLUMN local_ingest_token TEXT; "
            "CREATE INDEX IF NOT EXISTS "
            "idx_user_settings_local_ingest_token "
            "ON user_settings(local_ingest_token)",
        ),
        (
            6,
            "CREATE INDEX IF NOT EXISTS "
            "idx_user_settings_local_ingest_token "
            "ON user_settings(local_ingest_token)",
        ),
        (7, "ALTER TABLE user_settings ADD COLUMN reminder_json TEXT"),
        (8, "ALTER TABLE user_settings ADD COLUMN daily_llm_cap INTEGER"),
        (
            9,
            "ALTER TABLE user_settings ADD COLUMN "
            "llm_cost_per_1k_in REAL",
        ),
        (
            10,
            "ALTER TABLE user_settings ADD COLUMN "
            "llm_cost_per_1k_out REAL",
        ),
    )

    def get_or_create_local_ingest_token(self, tenant_id: str) -> str:
        """Return the tenant's token, generating and persisting one lazily."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT local_ingest_token FROM user_settings "
                    "WHERE tenant_id = ?",
                    (tenant_id,),
                ).fetchone()
                if row is not None and row["local_ingest_token"]:
                    return row["local_ingest_token"]
                return self._upsert_local_ingest_token(conn, tenant_id)

    def reset_local_ingest_token(self, tenant_id: str) -> str:
        """Replace the tenant's token and invalidate the old value."""
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                return self._upsert_local_ingest_token(conn, tenant_id)

    def find_tenant_by_local_ingest_token(
        self, token: str | None
    ) -> str | None:
        """Return the tenant owning a local-ingest token, or None."""
        token = (token or "").strip()
        if not token:
            return None
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT tenant_id FROM user_settings "
                    "WHERE local_ingest_token = ? LIMIT 1",
                    (token,),
                ).fetchone()
                return row["tenant_id"] if row else None

    @staticmethod
    def _upsert_local_ingest_token(conn, tenant_id: str) -> str:
        """Insert or replace a token row and return the token."""
        token = secrets.token_urlsafe(32)
        now = time.time()
        conn.execute(
            "INSERT INTO user_settings ("
            "tenant_id, classification_vocabulary_json, "
            "llm_provider, llm_model, llm_json, eval_default, "
            "local_ingest_token, updated_at"
            ") VALUES (?, '{}', NULL, NULL, NULL, 0, ?, ?) "
            "ON CONFLICT(tenant_id) DO UPDATE SET "
            "local_ingest_token = excluded.local_ingest_token, "
            "updated_at = excluded.updated_at",
            (tenant_id, token, now),
        )
        return token

    def get_settings(self, tenant_id: str) -> dict[str, Any]:
        defaults = default_settings()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT classification_vocabulary_json, llm_provider, "
                    "llm_model, llm_json, eval_default, local_ingest_token, "
                    "reminder_json, daily_llm_cap, "
                    "llm_cost_per_1k_in, llm_cost_per_1k_out "
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
        reminder = _parse_reminder_json(row["reminder_json"])
        settings = {
            "classification_vocabulary": json.loads(
                row["classification_vocabulary_json"] or "{}"
            ),
            "llm_provider": llm.get("provider"),
            "llm_model": llm.get("model"),
            "eval_default": bool(row["eval_default"]),
            "llm": llm,
            "reminder": reminder,
            "daily_llm_cap": row["daily_llm_cap"],
            "llm_cost_per_1k_in": row["llm_cost_per_1k_in"],
            "llm_cost_per_1k_out": row["llm_cost_per_1k_out"],
            "local_ingest_token": row["local_ingest_token"],
        }
        settings = _merge_defaults(defaults, settings)
        settings["local_ingest_token"] = row["local_ingest_token"]
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
        # The token is managed only by get/reset endpoints; regular settings
        # updates and reset must never clear a persisted token.
        token = updates.get("local_ingest_token")
        merged["local_ingest_token"] = (
            token if token else current.get("local_ingest_token")
        )
        _validate_settings(merged)
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO user_settings ("
                    "tenant_id, classification_vocabulary_json, "
                    "llm_provider, llm_model, llm_json, eval_default, updated_at"
                    ", local_ingest_token, reminder_json, daily_llm_cap, "
                    "llm_cost_per_1k_in, llm_cost_per_1k_out"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(tenant_id) DO UPDATE SET "
                    "classification_vocabulary_json = "
                    "excluded.classification_vocabulary_json, "
                    "llm_provider = excluded.llm_provider, "
                    "llm_model = excluded.llm_model, "
                    "llm_json = excluded.llm_json, "
                    "eval_default = excluded.eval_default, "
                    "local_ingest_token = excluded.local_ingest_token, "
                    "reminder_json = excluded.reminder_json, "
                    "daily_llm_cap = excluded.daily_llm_cap, "
                    "llm_cost_per_1k_in = excluded.llm_cost_per_1k_in, "
                    "llm_cost_per_1k_out = excluded.llm_cost_per_1k_out, "
                    "updated_at = excluded.updated_at",
                    (
                        tenant_id,
                        json.dumps(
                            merged["classification_vocabulary"],
                            ensure_ascii=False,
                        ),
                        merged["llm"].get("provider"),
                        merged["llm"].get("model"),
                        json.dumps(merged["llm"], ensure_ascii=False),
                        int(merged["eval_default"]),
                        now,
                        merged.get("local_ingest_token"),
                        json.dumps(
                            merged.get("reminder") or {},
                            ensure_ascii=False,
                        ),
                        merged.get("daily_llm_cap"),
                        merged.get("llm_cost_per_1k_in"),
                        merged.get("llm_cost_per_1k_out"),
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


def _parse_reminder_json(raw: str | None) -> dict[str, Any]:
    """Parse the reminder_json column, tolerating missing/corrupt values."""
    reminder: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            reminder = parsed
    defaults = default_settings()["reminder"]
    return {key: reminder.get(key, defaults.get(key)) for key in defaults}


def _merge_reminder(
    current: dict[str, Any],
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Merge a partial reminder update, normalizing blanks to None."""
    merged = dict(current)
    reminder_update = updates.get("reminder")
    if isinstance(reminder_update, dict):
        for key in merged:
            if key in reminder_update:
                merged[key] = reminder_update[key]
    return {
        key: (value if value != "" else None)
        for key, value in merged.items()
    }


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
    merged_reminder = _merge_reminder(
        defaults.get("reminder") or default_settings()["reminder"],
        updates,
    )
    eval_default = updates.get("eval_default")
    merged = {
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
        "reminder": merged_reminder,
        "daily_llm_cap": updates.get(
            "daily_llm_cap", defaults.get("daily_llm_cap")
        ),
        "llm_cost_per_1k_in": updates.get(
            "llm_cost_per_1k_in", defaults.get("llm_cost_per_1k_in")
        ),
        "llm_cost_per_1k_out": updates.get(
            "llm_cost_per_1k_out", defaults.get("llm_cost_per_1k_out")
        ),
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

    reminder = settings.get("reminder") or {}
    enabled = reminder.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise UserStoreError("reminder.enabled must be a boolean")
    auto_followup = reminder.get("auto_followup_reminder")
    if auto_followup is not None and not isinstance(auto_followup, bool):
        raise UserStoreError(
            "reminder.auto_followup_reminder must be a boolean"
        )
    provider = reminder.get("provider")
    if provider is not None and provider not in (
        "generic",
        "feishu",
        "wecom",
        "telegram",
    ):
        raise UserStoreError(
            "reminder.provider must be one of generic, feishu, wecom, telegram"
        )
    smtp_port = reminder.get("smtp_port")
    if smtp_port is not None:
        try:
            smtp_port = int(smtp_port)
        except (TypeError, ValueError):
            raise UserStoreError("reminder.smtp_port must be an integer") from None
        if not 1 <= smtp_port <= 65535:
            raise UserStoreError("reminder.smtp_port must be between 1 and 65535")
    for key in ("smtp_host", "smtp_user", "smtp_from", "smtp_to"):
        value = reminder.get(key)
        if value is not None and not isinstance(value, str):
            raise UserStoreError(f"reminder.{key} must be a string or null")

    daily_cap = settings.get("daily_llm_cap")
    if daily_cap is not None:
        try:
            daily_cap = int(daily_cap)
        except (TypeError, ValueError):
            raise UserStoreError("daily_llm_cap must be an integer or null") from None
        if daily_cap < 0:
            raise UserStoreError("daily_llm_cap must be a non-negative integer")
    for key in ("llm_cost_per_1k_in", "llm_cost_per_1k_out"):
        value = settings.get(key)
        if value is not None:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                raise UserStoreError(
                    f"{key} must be a non-negative number or null"
                ) from None
            if parsed < 0:
                raise UserStoreError(
                    f"{key} must be a non-negative number or null"
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
