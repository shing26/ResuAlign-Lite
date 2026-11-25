"""Dashboard data aggregation API.

GET /api/dashboard aggregates the tenant's master resumes and job library
into KPI counters, must-have skill frequencies, and a quick-continue
suggestion (the most recently updated job whose alignment has not
succeeded).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ...app.context import context
from ...job_library import ADVANCE_BUCKETS
from ..deps import get_current_user
from ..schemas import (
    AdvanceCounts,
    AlignmentQuality,
    DashboardKPI,
    DashboardQuickContinue,
    DashboardResponse,
    SkillGapItem,
)

router = APIRouter()

# Upper bound for the returned skill-gap ranking.
_SKILL_GAP_LIMIT = 8

# 「继续」卡只抬升一档：待定稿。
#
# 待定稿是唯一「再走一步就完成」的状态（建议已生成、只差采纳），而它的
# ``alignment_status`` 恰好是 ``succeeded``，被旧规则直接跳过 —— 17 条
# 已产出建议的岗位因此永远排不到队首。这是本轮唯一要修的产品缺陷。
#
# 其余未完成岗位继续沿用「最近更新优先」。**不要**再细分
# unanalyzed → unaligned → failed：既有用例
# ``test_dashboard_quick_continue_failed_includes_failure_detail`` 断言
# 「失败且更新更晚」的岗位优先于未预分析岗位，任何固定档位排序都会与它
# 冲突（两条既有用例对该子序的要求互相矛盾，见
# ``plans/advance-lanes-2026-11-25.md`` 的契约修订记录）。
_PRIORITY_BUCKET = "pending_draft"

# 四档「还没做完」的桶；``finalized`` 已完成，不再建议继续。
ADVANCE_ACTIONABLE = tuple(
    bucket for bucket in ADVANCE_BUCKETS if bucket != "finalized"
)


def _quick_continue_sort_key(job: dict[str, Any]) -> tuple[int, float, float]:
    """Order candidates: 待定稿 first, then match score, then recency."""
    on_top = 0 if job.get("advance_bucket") == _PRIORITY_BUCKET else 1
    score = float(job.get("match_score") or 0.0)
    updated = float(job.get("updated_at") or 0.0)
    return (on_top, -score, -updated)


def _quick_continue_card(
    job: dict[str, Any], next_action: str | None
) -> DashboardQuickContinue:
    failed = job["alignment_status"] == "failed"
    return DashboardQuickContinue(
        job_id=job["job_id"],
        title=job["title"],
        company=job["company"],
        alignment_status=job["alignment_status"],
        alignment_reason=job.get("alignment_reason"),
        alignment_error=job.get("alignment_error") if failed else None,
        updated_at=job["updated_at"],
        failure_detail=job.get("alignment_error") if failed else None,
        next_action=next_action,
    )


def _pick_quick_continue(
    jobs: list[dict[str, Any]],
) -> DashboardQuickContinue | None:
    """Pick the job whose next step is closest to done.

    ``finalized`` jobs are finished, so they are never suggested; jobs in no
    lane at all (no JD body, no-gap results) are also skipped. When no
    actionable job is left the card falls back to the most recently updated
    job, matching the pre-existing behaviour.
    """
    # In-flight rows sit in no lane but were part of the old candidate set
    # (``alignment_status != 'succeeded'``); keep them so the card does not
    # jump away from a job that is currently running.
    candidates = [
        job
        for job in jobs
        if job.get("advance_bucket") in ADVANCE_ACTIONABLE
        or job.get("alignment_status") in ("queued", "running")
    ]
    if candidates:
        best = min(candidates, key=_quick_continue_sort_key)
        return _quick_continue_card(best, best.get("advance_bucket"))
    if jobs:
        # Fallback row may be finalized or lane-less; ``next_action`` would
        # then claim a step that does not exist, so leave it unset.
        return _quick_continue_card(jobs[0], None)
    return None


def _job_funnel_stage(job: dict[str, Any]) -> str:
    """Return the highest historical pipeline stage for a library job.

    ADR-0027: the funnel stage is the peak of the current canonical status,
    ``applied_at`` evidence, and ``offer_at`` evidence. Withdrawn jobs keep
    their pre-abandon stage when a historical timestamp exists.

    Module 3 invariant: timestamps are append-only (terminal timestamps are
    preserved on revive). So ``offer_at`` > ``applied_at`` > current status
    is always true when all three exist.
    """
    stages = ("draft", "applied", "interview", "offer")
    current = job.get("status_canonical", "draft")
    peak = stages.index(current) if current in stages else 0
    if job.get("applied_at"):
        peak = max(peak, 1)
    if job.get("offer_at"):
        peak = max(peak, 3)
    return stages[peak]


@router.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(user: dict[str, Any] = Depends(get_current_user)):
    """Return aggregated KPI, skill-gap, and quick-continue data.

    - ``kpi.resumes`` counts the tenant's master resumes.
    - ``kpi.jobs`` counts the tenant's library jobs; applied/interview/offer
      use the historical peak stage (offer_at > applied_at > current status),
      while declined stays the current withdrawn count.
    - ``skill_gaps`` ranks the frequencies of ``must_have_skills`` across
      all job JD profiles, descending (top 8).
    - ``quick_continue`` is the most recently updated job whose
      ``alignment_status`` is not ``succeeded``; when every job is
      finished, it falls back to the most recently updated job.
    """
    tenant_id = user["user_id"]
    jobs = context._jobs.list_dashboard_jobs(tenant_id)
    resume_count = len(context._resumes.list_master_resumes(tenant_id))

    applied = 0
    interview = 0
    offer = 0
    declined = 0
    for job in jobs:
        canonical = job["status_canonical"]
        stage = _job_funnel_stage(job)
        if stage in {"applied", "interview", "offer"}:
            applied += 1
        if stage in {"interview", "offer"}:
            interview += 1
        if stage == "offer":
            offer += 1
        if canonical == "withdrawn":
            declined += 1

    skill_counts: dict[str, int] = {}
    for job in jobs:
        profile = job["jd_profile"]
        if not isinstance(profile, dict):
            continue
        for skill in profile.get("must_have_skills") or []:
            key = str(skill).strip()
            if key:
                skill_counts[key] = skill_counts.get(key, 0) + 1
    skill_gaps = [
        SkillGapItem(skill=skill, count=count)
        for skill, count in sorted(
            skill_counts.items(), key=lambda item: (-item[1], item[0])
        )[:_SKILL_GAP_LIMIT]
    ]

    quick_continue = _pick_quick_continue(jobs)

    return DashboardResponse(
        kpi=DashboardKPI(
            resumes=resume_count,
            jobs=len(jobs),
            applied=applied,
            interview=interview,
            offer=offer,
            declined=declined,
        ),
        skill_gaps=skill_gaps,
        quick_continue=quick_continue,
        quality=AlignmentQuality(**context._jobs.alignment_quality_summary(
            user["user_id"]
        )),
        advance=AdvanceCounts(**context._jobs.advance_counts(user["user_id"])),
    )
