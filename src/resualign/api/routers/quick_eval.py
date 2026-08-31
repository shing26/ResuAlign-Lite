"""Quick JD evaluation — paste a JD, get a rule-based match read in seconds.

Deterministic, zero-LLM decision aid: combines the rule fallback's skill
extraction / gap report with the deterministic match scorer. This is the
"值不值得投" front door; the deep alignment pipeline stays behind the
"一键入库并对齐" CTA on the client.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import resualign.api as api_module

from ...local_fallback import _extract_skills, local_gap_report
from ...match_scorer import (
    compute_match_score,
    fallback_match_reason,
    keyword_coverage_score,
)
from ..deps import get_current_user

router = APIRouter()

_MISSING_TOP = 3
_JD_TEXT_MAX = 8000  # 与 MAX_JD_INPUT_CHARS 一致


class QuickEvalRequest(BaseModel):
    jd_text: str = Field(min_length=30, max_length=_JD_TEXT_MAX)
    master_resume_id: str | None = None


def _evaluate(
    resume_text: str, jd_text: str, master_resume_id: str | None
) -> dict[str, Any]:
    """Rule-only evaluation shared by the endpoint (pure function, no IO)."""
    must_have = _extract_skills(jd_text)
    profile = {"must_have_skills": must_have}
    gap = local_gap_report(resume_text, jd_text)
    missing = [str(item) for item in (gap.get("missing_keywords") or [])]
    detail = compute_match_score(
        jd_text, profile, gap, None, resume_text, master_resume_id
    )
    coverage = keyword_coverage_score(profile, resume_text)
    return {
        "total": detail.get("total"),
        "dimensions": {
            key: detail.get(key)
            for key in ("hard_skills", "scenario", "expression", "experience")
        },
        "missing_top": missing[:_MISSING_TOP],
        "missing_count": len(missing),
        "keyword_coverage": coverage,
        "recommendation": fallback_match_reason(detail, missing),
        "rule_based": True,
    }


@router.post("/api/quick-eval")
def quick_eval(req: QuickEvalRequest, user: dict[str, Any] = Depends(get_current_user)):
    """Score a pasted JD against a master resume with deterministic rules.

    No LLM is touched: the decision scenario needs a 3-second read, not a
    4-minute pipeline. When the JD already exists in the library the
    response says so and carries the existing job_id so the client can
    deep-link instead of duplicating a row.
    """
    jd_text = req.jd_text.strip()
    if len(jd_text) < 30:
        raise HTTPException(status_code=422, detail="JD 文本太短，至少 30 个字符")

    resume_text = ""
    master_resume_id = req.master_resume_id or None
    if master_resume_id:
        resume = api_module._resumes.get_master_resume(user["user_id"], master_resume_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Master resume not found")
        resume_text = resume.get("content") or ""

    existing = api_module._jobs.find_by_dedupe_key(
        user["user_id"],
        api_module._workbench_service._library_dedupe_key(jd_text),
    )
    evaluation = _evaluate(resume_text, jd_text, master_resume_id)
    return {
        "evaluation": evaluation,
        "existing_job_id": existing["job_id"] if existing else None,
        "resume_selected": bool(master_resume_id),
    }
