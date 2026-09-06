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
    """Return today's usage, cap, estimated cost, and blocking state.

    P1-1（2026-09-06 安全审查）：blocked/remaining 按实际调用 + 未消费预留
    计算（``calls + reserves``），入队即占坑，任务真正调用时消费。
    """
    settings = api_module._settings_store.get_settings(tenant_id)
    usage = api_module._llm_usage.get_usage(tenant_id)
    cap = settings.get("daily_llm_cap")
    cap_value = int(cap) if cap is not None else None
    effective_calls = usage["calls"] + usage.get("reserves", 0)
    return {
        "date": usage["usage_date"],
        "calls": usage["calls"],
        "cap": cap_value,
        "estimated_cost": round(
            usage["estimated_cost"],
            4,
        ),
        "blocked": cap_value is not None and effective_calls >= cap_value,
        "remaining": (
            None
            if cap_value is None
            else max(0, cap_value - effective_calls)
        ),
    }


def enforce_daily_llm_cap(tenant_id: str) -> None:
    """Reject a new LLM task with 429 when today's cap is exhausted.

    P1-1：检查与预留合并为一次原子条件递增（``WHERE calls + reserves <
    cap``），并发入队不再能整体击穿每日 cap。预留由任务的真实 LLM 调用
    （record_call）消费；任务结束未消费的由 _run_job 释放，未释放的随
    「当日」边界过期（保守方向：只会少用不会多用）。
    """
    settings = api_module._settings_store.get_settings(tenant_id)
    cap = settings.get("daily_llm_cap")
    if cap is None:
        return
    cap_value = int(cap)
    if cap_value <= 0:
        raise HTTPException(
            status_code=429,
            detail=CAP_REACHED_DETAIL,
        )
    if not api_module._llm_usage.reserve_call(tenant_id, cap_value):
        raise HTTPException(
            status_code=429,
            detail=CAP_REACHED_DETAIL,
        )


# R4 P0-6（03-AIE §③）：同一 job（library_job_id）连续失败熔断阈值。
# 失败后用户可无脑连点重试烧额度（体验报告 P0-1④），熔断前先引导换节点/缩短 JD。
_FAIL_STREAK_LIMIT = 3
_REPEATED_FAILURES_DETAIL = {
    "message": "该任务已连续失败 3 次，建议先更换模型/节点或缩短 JD 后重试",
    "code": "repeated_failures",
}


def enforce_llm_task_entry(
    tenant_id: str,
    job_ref_key: str | None = None,
) -> bool:
    """Entry interception: daily cap + consecutive-failure circuit breaker.

    Wired into ``_queue_job`` (api/services/jobs.py) so every queued LLM task
    is gated; ``job_ref_key`` is the library_job_id for workbench retries.
    Returns whether a daily-cap slot was reserved (P1-1) so the queue can
    carry the flag for release-at-completion.
    """
    settings = api_module._settings_store.get_settings(tenant_id)
    reserved = settings.get("daily_llm_cap") is not None
    enforce_daily_llm_cap(tenant_id)
    if job_ref_key:
        streak = api_module._registry.recent_fail_streak(tenant_id, job_ref_key)
        if streak >= _FAIL_STREAK_LIMIT:
            # 熔断拒绝时保留已成功的预留（保守占用，随当日边界过期），
            # 不再走反向释放路径。
            raise HTTPException(
                status_code=429,
                detail=_REPEATED_FAILURES_DETAIL,
            )
    return reserved


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
