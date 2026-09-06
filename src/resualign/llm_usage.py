"""Persistent per-tenant daily LLM usage and cost guardrails (MVP-10)."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
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
    reserves INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (tenant_id, usage_date)
);
"""

# 2026-09-06（安全审查 P1-1）：新增 reserves 列——任务入队时原子条件预留
# 一个调用名额（WHERE calls + reserves < cap），堵住 check-then-spend 竞态
# （N 个并发请求整体击穿每日 cap）。真实调用发生时 record_call 消费一个
# 预留；任务结束仍未消费的预留由调用方释放，未释放的随「当日」边界过期。
_LLM_USAGE_MIGRATIONS = (
    (
        1,
        "ALTER TABLE llm_daily_usage ADD COLUMN reserves INTEGER NOT NULL DEFAULT 0",
    ),
    (
        2,
        "ALTER TABLE llm_daily_usage ADD COLUMN tokens_in INTEGER NOT NULL DEFAULT 0",
    ),
    (
        3,
        "ALTER TABLE llm_daily_usage ADD COLUMN tokens_out INTEGER NOT NULL DEFAULT 0",
    ),
)

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
    MIGRATIONS: tuple[tuple[int, str], ...] = _LLM_USAGE_MIGRATIONS

    def _ensure_initialized(self) -> None:
        super()._ensure_initialized(_LLM_USAGE_SCHEMA)

    def reserve_call(
        self,
        tenant_id: str,
        cap: int,
        usage_date: str | None = None,
    ) -> bool:
        """Atomically claim one daily call slot (P1-1 race fix).

        Claims only when ``calls + reserves < cap``; returns ``False`` when
        today's cap is exhausted. The claim is consumed by the next
        :meth:`record_call` or returned via :meth:`release_call`.
        """
        if cap <= 0:
            return False
        day = usage_day(usage_date)
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO llm_daily_usage ("
                    "tenant_id, usage_date, calls, estimated_cost, "
                    "reserves, updated_at"
                    ") VALUES (?, ?, 0, 0, 1, ?) "
                    "ON CONFLICT(tenant_id, usage_date) DO UPDATE SET "
                    "reserves = reserves + 1, "
                    "updated_at = excluded.updated_at "
                    "WHERE llm_daily_usage.calls + llm_daily_usage.reserves < ?",
                    (tenant_id, day, now, cap),
                )
                return cursor.rowcount > 0

    def release_call(
        self,
        tenant_id: str,
        usage_date: str | None = None,
    ) -> None:
        """Return one unconsumed reservation (floor at zero)."""
        day = usage_day(usage_date)
        now = time.time()
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "UPDATE llm_daily_usage SET "
                    "reserves = MAX(reserves - 1, 0), updated_at = ? "
                    "WHERE tenant_id = ? AND usage_date = ?",
                    (now, tenant_id, day),
                )

    def record_call(
        self,
        tenant_id: str,
        usage_date: str | None = None,
        estimated_cost: float = 0.0,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        """Increment the tenant's daily call counter once per logical call.

        Each recorded call consumes one outstanding reservation (P1-1):
        reservations only shift *when* a call is counted, never double-count.
        Real token counts (P2 #78) are accumulated when the provider reports
        them, replacing the fixed 2000/1000 estimate for cost accuracy.
        """
        day = usage_day(usage_date)
        now = time.time()
        tokens_in = max(0, int(tokens_in or 0))
        tokens_out = max(0, int(tokens_out or 0))
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO llm_daily_usage ("
                    "tenant_id, usage_date, calls, estimated_cost, "
                    "reserves, tokens_in, tokens_out, updated_at"
                    ") VALUES (?, ?, 1, ?, 0, ?, ?, ?) "
                    "ON CONFLICT(tenant_id, usage_date) DO UPDATE SET "
                    "calls = calls + 1, "
                    "estimated_cost = estimated_cost + excluded.estimated_cost, "
                    "reserves = MAX(reserves - 1, 0), "
                    "tokens_in = tokens_in + excluded.tokens_in, "
                    "tokens_out = tokens_out + excluded.tokens_out, "
                    "updated_at = excluded.updated_at",
                    (
                        tenant_id,
                        day,
                        max(0.0, estimated_cost),
                        tokens_in,
                        tokens_out,
                        now,
                    ),
                )

    def get_usage(
        self,
        tenant_id: str,
        usage_date: str | None = None,
    ) -> dict[str, Any]:
        """Return today's call count and estimated cost for a tenant."""
        day = usage_day(usage_date)
        with self._lock:
            self._ensure_initialized()
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT calls, estimated_cost, reserves, tokens_in, "
                    "tokens_out FROM llm_daily_usage "
                    "WHERE tenant_id = ? AND usage_date = ?",
                    (tenant_id, day),
                ).fetchone()
        return {
            "usage_date": day,
            "calls": int(row["calls"] or 0) if row else 0,
            "estimated_cost": float(row["estimated_cost"] or 0.0)
            if row
            else 0.0,
            "reserves": int(row["reserves"] or 0) if row else 0,
            "tokens_in": int(row["tokens_in"] or 0) if row else 0,
            "tokens_out": int(row["tokens_out"] or 0) if row else 0,
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
            "reserves": usage["reserves"],
        }


def usage_day(usage_date: str | None = None) -> str:
    """Return the UTC day key for usage accounting (P2-5: fixed boundary)."""
    if usage_date:
        return usage_date
    return datetime.now(timezone.utc).date().isoformat()


def estimate_call_cost(
    cost_per_1k_in: float | None,
    cost_per_1k_out: float | None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> float:
    """Estimate one call's cost from configured per-1k prices.

    When the provider reported real token counts (P2 #78), they replace the
    fixed ESTIMATED_INPUT/OUTPUT_TOKENS placeholders (up to ~3x drift).
    """
    price_in = max(0.0, float(cost_per_1k_in or 0.0))
    price_out = max(0.0, float(cost_per_1k_out or 0.0))
    real_in = tokens_in if tokens_in and tokens_in > 0 else ESTIMATED_INPUT_TOKENS
    real_out = (
        tokens_out if tokens_out and tokens_out > 0 else ESTIMATED_OUTPUT_TOKENS
    )
    return round(
        (real_in / 1000.0) * price_in + (real_out / 1000.0) * price_out,
        6,
    )
