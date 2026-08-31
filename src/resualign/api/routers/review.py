"""Weekly delivery review endpoint.

Pure SQL-backed aggregation over the job library — no LLM calls. The review
page consumes: this week's application pace, the pipeline stage distribution,
three rule-based action lists, and the attribution comparison (alignment vs
unaligned screen-pass rate) introduced with the application_result field.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends

import resualign.api as api_module

from ...job_library.status_lifecycle import canonical_status
from ..deps import get_current_user
from ..schemas import (
    ReviewActions,
    ReviewAttribution,
    ReviewJobCard,
    ReviewResponse,
)

router = APIRouter()

# 复盘关注"投递后仍在推进"的岗位：已投递/面试中才算停滞或待跟进；
# offer/withdrawn 是终局，不进行动清单。
_ACTIONABLE_STATUSES = frozenset({"applied", "interview"})
_STALE_DAYS = 7
_DUE_SOON_DAYS = 7
# 归因对比的最小组样本：低于它只报计数不报比率（1/1=100% 的误导）。
_MIN_ATTRIBUTION_SAMPLE = 3


def _job_card(job: dict[str, Any]) -> ReviewJobCard:
    return ReviewJobCard(
        job_id=job["job_id"],
        title=job.get("title"),
        company=job.get("company"),
        status=canonical_status(job.get("status") or "draft"),
        alignment_status=job.get("alignment_status") or "idle",
        application_result=job.get("application_result") or None,
        next_step=job.get("next_step") or None,
        next_step_due_at=job.get("next_step_due_at") or None,
        deadline=job.get("deadline") or None,
    )


def _date_str(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _parse_date(value: str | None) -> str | None:
    """Normalize a stored DATE / datetime string to its YYYY-MM-DD prefix."""
    if not value:
        return None
    return str(value)[:10]


def _attribution_summary(
    jobs: list[dict[str, Any]],
) -> ReviewAttribution:
    aligned_pass = 0
    aligned_total = 0
    unaligned_pass = 0
    unaligned_total = 0
    for job in jobs:
        result = (job.get("application_result") or "").strip()
        if not result:
            continue
        aligned = (job.get("alignment_status") or "idle") == "succeeded"
        passed = result == "screen_pass"
        if aligned:
            aligned_total += 1
            aligned_pass += 1 if passed else 0
        else:
            unaligned_total += 1
            unaligned_pass += 1 if passed else 0
    return ReviewAttribution(
        min_sample=_MIN_ATTRIBUTION_SAMPLE,
        aligned_total=aligned_total,
        aligned_pass=aligned_pass,
        aligned_pass_rate=(
            round(aligned_pass / aligned_total, 3)
            if aligned_total >= _MIN_ATTRIBUTION_SAMPLE
            else None
        ),
        unaligned_total=unaligned_total,
        unaligned_pass=unaligned_pass,
        unaligned_pass_rate=(
            round(unaligned_pass / unaligned_total, 3)
            if unaligned_total >= _MIN_ATTRIBUTION_SAMPLE
            else None
        ),
    )


@router.get("/api/review", response_model=ReviewResponse)
def get_review(user: dict[str, Any] = Depends(get_current_user)):
    """Return the weekly delivery review payload (deterministic, zero LLM)."""
    tenant_id = user["user_id"]
    jobs = api_module._jobs.list_jobs(tenant_id, limit=None)
    now = time.time()
    today = _date_str(now)

    # 本周投递节奏：applied_at（DATE/datetime 前 10 位）按日计数，近 7 天
    # 逐日补零，让"哪天空投、哪天忘跟进"一眼可见。
    pace_counts: dict[str, int] = {}
    for offset in range(6, -1, -1):
        pace_counts[_date_str(now - offset * 86400)] = 0
    for job in jobs:
        applied = _parse_date(job.get("applied_at"))
        if applied and applied in pace_counts:
            pace_counts[applied] += 1
    week_pace = [{"date": day, "count": count} for day, count in pace_counts.items()]

    stage_distribution: dict[str, int] = {}
    for job in jobs:
        stage = canonical_status(job.get("status") or "draft")
        stage_distribution[stage] = stage_distribution.get(stage, 0) + 1

    overdue: list[ReviewJobCard] = []
    stale: list[ReviewJobCard] = []
    due_soon: list[ReviewJobCard] = []
    stale_cutoff = _date_str(now - _STALE_DAYS * 86400)
    due_soon_end = _date_str(now + _DUE_SOON_DAYS * 86400)
    for job in jobs:
        status = canonical_status(job.get("status") or "draft")
        if status not in _ACTIONABLE_STATUSES:
            continue
        next_due = _parse_date(job.get("next_step_due_at"))
        if next_due and next_due < today:
            overdue.append(_job_card(job))
            continue
        updated_day = _parse_date(
            time.strftime("%Y-%m-%d", time.localtime(job.get("updated_at") or 0))
        )
        if updated_day and updated_day <= stale_cutoff:
            stale.append(_job_card(job))
        deadline = _parse_date(job.get("deadline"))
        # 已过期 deadline 不进"临近截止"（它属于岗位卡上的过期警示）。
        if deadline and today <= deadline <= due_soon_end:
            due_soon.append(_job_card(job))

    return ReviewResponse(
        generated_at=today,
        week_pace=week_pace,
        stage_distribution=stage_distribution,
        actions=ReviewActions(
            overdue_next_steps=overdue,
            stale_jobs=stale,
            due_soon=due_soon,
        ),
        attribution=_attribution_summary(jobs),
    )
