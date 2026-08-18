"""Persistent per-tenant daily LLM usage and cost guardrails (MVP-10)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date
from typing import Any, Iterator

from .store_base import _SqliteStore

# Estimated tokens per logical LLM call when the provider does not expose
# usage. Used only for the cost estimate; the call counter is exact.
ESTIMATED_INPUT_TOKENS = 2000
ESTIMATED_OUTPUT_TOKENS = 1000

_LLM_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_daily_usage (
    tenant_id TEXT NOT NULL,
    usage_date TEXT NOT NULL,
    calls INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    PRIMARY KEY (tenant_id, usage_date)
);
"""

_LLM_TENANT: ContextVar[str] = ContextVar(
    "resualign_llm_tenant",
    default="",
)


def current_llm_tenant() -> str:
    """Return the tenant currently issuing an LLM call."""
    return _LLM_TENANT.get()


def set_llm_tenant(tenant_id: str):
    """Set the current LLM tenant and return the reset token."""
    return _LLM_TENANT.set(tenant_id)


def reset_llm_tenant(token) -> None:
    """Restore the previous LLM tenant context."""
    _LLM_TENANT.reset(token)


@contextmanager
def llm_tenant_context(tenant_id: str) -> Iterator[None]:
    """Bind an LLM call to a tenant for the duration of a block."""
    token = _LLM_TENANT.set(tenant_id)
    try:
        yield
    finally:
        _LLM_TENANT.reset(token)


class LLMUsageStore(_SqliteStore):
    """SQLite-backed daily call counter shared across process restarts."""

    SCHEMA_SQL = _LLM_USAGE_SCHEMA
    MIGRATIONS: tuple[tuple[int, str], ...] = ()

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_LLM_USAGE_SCHEMA)

    def record_call(
        self,
        tenant_id: str,
        usage_date: str | None = None,
        estimated_cost: float = 0.0,
    ) -> None:
        """Increment the tenant's daily call counter once per logical call."""
        day = usage_date or date.today().isoformat()
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO llm_daily_usage ("
                    "tenant_id, usage_date, calls, estimated_cost, updated_at"
                    ") VALUES (?, ?, 1, ?, ?) "
                    "ON CONFLICT(tenant_id, usage_date) DO UPDATE SET "
                    "calls = calls + 1, "
                    "estimated_cost = estimated_cost + excluded.estimated_cost, "
                    "updated_at = excluded.updated_at",
                    (tenant_id, day, max(0.0, estimated_cost), now),
                )

    def get_usage(
        self,
        tenant_id: str,
        usage_date: str | None = None,
    ) -> dict[str, Any]:
        """Return today's call count and estimated cost for a tenant."""
        day = usage_date or date.today().isoformat()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT calls, estimated_cost FROM llm_daily_usage "
                    "WHERE tenant_id = ? AND usage_date = ?",
                    (tenant_id, day),
                ).fetchone()
        return {
            "usage_date": day,
            "calls": int(row["calls"] or 0) if row else 0,
            "estimated_cost": float(row["estimated_cost"] or 0.0)
            if row
            else 0.0,
        }

    def snapshot(
        self,
        tenant_id: str,
        usage_date: str | None = None,
    ) -> dict[str, Any]:
        """Return the full daily status for /api/ops/metrics."""
        usage = self.get_usage(tenant_id, usage_date)
        return {
            "date": usage["usage_date"],
            "calls": usage["calls"],
            "estimated_cost": round(usage["estimated_cost"], 4),
        }


def estimate_call_cost(
    cost_per_1k_in: float | None,
    cost_per_1k_out: float | None,
) -> float:
    """Estimate one logical call's cost from configured per-1k prices."""
    price_in = max(0.0, float(cost_per_1k_in or 0.0))
    price_out = max(0.0, float(cost_per_1k_out or 0.0))
    return round(
        (ESTIMATED_INPUT_TOKENS / 1000.0) * price_in
        + (ESTIMATED_OUTPUT_TOKENS / 1000.0) * price_out,
        6,
    )
