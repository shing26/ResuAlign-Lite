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

# Canonical statuses counted as "已投递" (applied pipeline states).
_APPLIED_STATUSES = {"applied", "interview", "offer"}
# Upper bound for the returned skill-gap ranking.
_SKILL_GAP_LIMIT = 8


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
    - ``kpi.jobs`` counts the tenant's library jobs; the applied/interview/
      offer/declined counters derive from the canonical five-state status.
    - ``kpi.active_followups`` counts jobs whose ``next_step_due_at`` is
      non-empty and not in the past.
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
        if canonical in _APPLIED_STATUSES:
            applied += 1
        if canonical == "interview":
            interview += 1
        elif canonical == "offer":
            offer += 1
        elif canonical == "withdrawn":
            declined += 1
        due = _due_date_key(job["next_step_due_at"])
        if due is not None and due >= today:
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
