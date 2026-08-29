"""Deterministic four-dimension match scoring for the job library."""

from __future__ import annotations

import hashlib
import re
from typing import Any

MATCH_WEIGHTS = {
    "hard_skills": 0.35,
    "scenario": 0.25,
    "expression": 0.20,
    "experience": 0.20,
}
MATCH_VERSION = 1

_EXPERIENCE_RE = re.compile(
    r"(?:\d+\s*年|y(?:ea)?rs?\b|经验|experience)",
    flags=re.IGNORECASE,
)


def clamp100(value: float | int) -> float:
    """Clamp a numeric score to the 0..100 range, rounded to one decimal."""
    return round(max(0.0, min(100.0, float(value))), 1)


def _content_sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()


def keyword_coverage_score(
    jd_profile: dict[str, Any] | None,
    resume_text: str | None,
) -> dict[str, Any] | None:
    """Deterministic ATS keyword-coverage proxy.

    Ratio of the JD profile's hard skill keywords literally present in the
    resume text (case-insensitive). Reads ``must_have_skills`` (the live
    profiler's canonical key) with the ``required_skills``/``skills``
    aliases accepted by the rule fallback. Returns ``None`` when the
    profile lists no skills so callers can skip the metric instead of
    mistaking "no requirements" for "zero coverage".
    """
    profile_skills = (jd_profile or {}).get("must_have_skills")
    if not profile_skills:
        for alias in ("required_skills", "skills", "required"):
            profile_skills = (jd_profile or {}).get(alias)
            if profile_skills:
                break
    required = [str(skill).strip() for skill in (profile_skills or []) if str(skill).strip()]
    if not required:
        return None
    resume_lower = (resume_text or "").lower()
    matched = [skill for skill in required if skill.lower() in resume_lower]
    return {
        "required": len(required),
        "matched": len(matched),
        "ratio": round(len(matched) / len(required), 3),
        "missing": [skill for skill in required if skill.lower() not in resume_lower],
    }


def compute_match_score(
    jd_text: str | None,
    jd_profile: dict[str, Any] | None,
    gap_report: dict[str, Any] | None,
    eval_score: dict[str, Any] | None,
    resume_text: str | None,
    master_resume_id: str | None,
) -> dict[str, Any]:
    """Return the four-dimension score detail with its input snapshot."""
    profile = jd_profile or {}
    gap = gap_report or {}
    evaluation = eval_score or {}
    missing_keywords = [
        str(item).strip()
        for item in (gap.get("missing_keywords") or [])
        if str(item).strip()
    ]
    business_scenarios = [
        str(item).strip()
        for item in (profile.get("business_scenarios") or [])
        if str(item).strip()
    ]
    scenario_missing_count = sum(
        1
        for keyword in missing_keywords
        if any(scenario and scenario in keyword for scenario in business_scenarios)
    )
    experience_missing_count = sum(
        1
        for keyword in missing_keywords
        if _EXPERIENCE_RE.search(keyword)
    )
    misaligned_emphasis = gap.get("misaligned_emphasis") or []
    hallucination = 1 if evaluation.get("hallucination_detected") else 0

    hard_skills = clamp100(100 - 15 * len(missing_keywords))
    scenario = clamp100(100 - 25 * scenario_missing_count)
    expression = clamp100(
        100 - 20 * len(misaligned_emphasis) - 5 * hallucination
    )
    experience = clamp100(100 - 15 * experience_missing_count)
    total = round(
        MATCH_WEIGHTS["hard_skills"] * hard_skills
        + MATCH_WEIGHTS["scenario"] * scenario
        + MATCH_WEIGHTS["expression"] * expression
        + MATCH_WEIGHTS["experience"] * experience,
        1,
    )
    return {
        "hard_skills": hard_skills,
        "scenario": scenario,
        "expression": expression,
        "experience": experience,
        "total": total,
        "version": MATCH_VERSION,
        "keyword_coverage": keyword_coverage_score(profile, resume_text),
        "inputs_snapshot": {
            "jd_sha256": _content_sha256(jd_text),
            "resume_sha256": _content_sha256(resume_text),
            "master_resume_id": master_resume_id or "",
        },
    }


def fallback_match_reason(
    detail: dict[str, Any],
    missing_keywords: list[str],
) -> str:
    """Return a deterministic Chinese recommendation based on rule scores."""
    total = float(detail.get("total") or 0)
    missing = len(missing_keywords or [])
    if total >= 80:
        return (
            f"基于规则评分：四维匹配 {total:.1f} 分，仅 {missing} 项硬技能缺口，"
            "整体匹配度较高，建议优先投递。"
        )
    if total >= 60:
        return (
            f"基于规则评分：四维匹配 {total:.1f} 分，存在 {missing} 项技能缺口，"
            "可先补齐关键词再投递。"
        )
    return (
        f"基于规则评分：四维匹配 {total:.1f} 分，{missing} 项关键能力缺口明显，"
        "当前匹配度偏低，建议先优化简历或筛选更合适的岗位。"
    )


def snapshot_matches(
    detail: dict[str, Any] | None,
    jd_text: str | None,
    resume_text: str | None,
    master_resume_id: str | None,
) -> bool:
    """Return whether a stored detail still reflects the current inputs."""
    if not isinstance(detail, dict):
        return False
    snapshot = detail.get("inputs_snapshot")
    if not isinstance(snapshot, dict):
        return False
    return bool(
        snapshot.get("jd_sha256") == _content_sha256(jd_text)
        and snapshot.get("resume_sha256") == _content_sha256(resume_text)
        and snapshot.get("master_resume_id") == (master_resume_id or "")
    )
