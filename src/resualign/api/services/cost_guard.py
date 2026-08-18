"""Daily LLM cost guardrail enforcement shared by API routes."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

import resualign.api as api_module

from ...llm_usage import estimate_call_cost

CAP_REACHED_DETAIL = {
    "message": "今日 LLM 调用已达上限，缓存命中的分析仍可使用",
    "code": "llm_daily_cap_reached",
}


def llm_daily_status(tenant_id: str) -> dict[str, Any]:
    """Return today's usage, cap, estimated cost, and blocking state."""
    settings = api_module._settings_store.get_settings(tenant_id)
    usage = api_module._llm_usage.get_usage(tenant_id)
    cap = settings.get("daily_llm_cap")
    cap_value = int(cap) if cap is not None else None
    return {
        "date": usage["usage_date"],
        "calls": usage["calls"],
        "cap": cap_value,
        "estimated_cost": round(
            usage["estimated_cost"],
            4,
        ),
        "blocked": cap_value is not None and usage["calls"] >= cap_value,
        "remaining": (
            None
            if cap_value is None
            else max(0, cap_value - usage["calls"])
        ),
    }


def enforce_daily_llm_cap(tenant_id: str) -> None:
    """Reject a new LLM task with 429 when today's cap is exhausted."""
    status = llm_daily_status(tenant_id)
    if status["blocked"]:
        raise HTTPException(
            status_code=429,
            detail=CAP_REACHED_DETAIL,
        )


def record_daily_llm_usage() -> None:
    """Persist one logical LLM call for the current tenant (recorder hook)."""
    from ...llm_usage import current_llm_tenant

    tenant = current_llm_tenant()
    if not tenant:
        # Tests and non-API callers never bind a tenant; do not count them
        # against the real data directory.
        return
    try:
        settings = api_module._settings_store.get_settings(tenant)
    except Exception:  # noqa: BLE001 - usage accounting must never break calls
        settings = {}
    cost = estimate_call_cost(
        settings.get("llm_cost_per_1k_in"),
        settings.get("llm_cost_per_1k_out"),
    )
    api_module._llm_usage.record_call(tenant, estimated_cost=cost)
