"""Dashboard data aggregation API.

GET /api/dashboard aggregates the tenant's master resumes and job library
into KPI counters, must-have skill frequencies, and a quick-continue
suggestion (the most recently updated job whose alignment has not
succeeded).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import (
    DashboardKPI,
    DashboardQuickContinue,
    DashboardResponse,
    SkillGapItem,
)

router = APIRouter()

# Canonical statuses that still produce an active follow-up reminder.
_ACTIVE_REMINDER_STATUSES = {"applied", "interview"}
# Upper bound for the returned skill-gap ranking.
_SKILL_GAP_LIMIT = 8


def _job_funnel_stage(job: dict[str, Any]) -> str:
    """Return the highest historical pipeline stage for a library job.

    ADR-0027: the funnel stage is the peak of the current canonical status,
    ``applied_at`` evidence, and ``offer_at`` evidence. Withdrawn jobs keep
    their pre-abandon stage when a historical timestamp exists.
    """
    stages = ("draft", "applied", "interview", "offer")
    current = job.get("status_canonical", "draft")
    peak = stages.index(current) if current in stages else 0
    if job.get("applied_at"):
        peak = max(peak, 1)
    if job.get("offer_at"):
        peak = max(peak, 3)
    return stages[peak]


def _due_date_key(value: str | None) -> str | None:
    """Normalize a stored follow-up due value to a YYYY-MM-DD key.

    ``next_step_due_at`` is stored as a full ISO timestamp (e.g.
    ``2026-08-15T09:00:00Z``); only the date prefix participates in the
    "not expired" comparison against today.
    """
    if not value:
        return None
    key = value.strip()[:10]
    return key or None


@router.get("/api/dashboard", response_model=DashboardResponse)
def get_dashboard(user: dict[str, Any] = Depends(get_current_user)):
    """Return aggregated KPI, skill-gap, and quick-continue data.

    - ``kpi.resumes`` counts the tenant's master resumes.
    - ``kpi.jobs`` counts the tenant's library jobs; applied/interview/offer
      use the historical peak stage (offer_at > applied_at > current status),
      while declined stays the current withdrawn count.
    - ``kpi.active_followups`` counts jobs whose ``next_step_due_at`` is
      non-empty and not in the past, restricted to applied/interview jobs.
    - ``skill_gaps`` ranks the frequencies of ``must_have_skills`` across
      all job JD profiles, descending (top 8).
    - ``quick_continue`` is the most recently updated job whose
      ``alignment_status`` is not ``succeeded``; when every job is
      finished, it falls back to the most recently updated job.
    """
    tenant_id = user["user_id"]
    jobs = api_module._jobs.list_dashboard_jobs(tenant_id)
    resume_count = len(api_module._resumes.list_master_resumes(tenant_id))

    applied = 0
    interview = 0
    offer = 0
    declined = 0
    active_followups = 0
    today = date.today().isoformat()
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
        due = _due_date_key(job["next_step_due_at"])
        if (
            canonical in _ACTIVE_REMINDER_STATUSES
            and due is not None
            and due >= today
        ):
            active_followups += 1

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

    quick_continue = None
    for job in jobs:  # already ordered by updated_at DESC
        if job["alignment_status"] != "succeeded":
            quick_continue = DashboardQuickContinue(
                job_id=job["job_id"],
                title=job["title"],
                company=job["company"],
                alignment_status=job["alignment_status"],
                updated_at=job["updated_at"],
            )
            break
    if quick_continue is None and jobs:
        first = jobs[0]
        quick_continue = DashboardQuickContinue(
            job_id=first["job_id"],
            title=first["title"],
            company=first["company"],
            alignment_status=first["alignment_status"],
            updated_at=first["updated_at"],
        )

    return DashboardResponse(
        kpi=DashboardKPI(
            resumes=resume_count,
            jobs=len(jobs),
            applied=applied,
            interview=interview,
            offer=offer,
            declined=declined,
            active_followups=active_followups,
        ),
        skill_gaps=skill_gaps,
        quick_continue=quick_continue,
    )
