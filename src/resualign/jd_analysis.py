"""Combined JD profile and gap analysis in a single LLM round trip."""

from __future__ import annotations

from .gap_analyzer import GAP_ANALYSIS_PROMPT
from .jd_profiler import JD_PROFILER_PROMPT
from .llm import LLMClient
from .models import GapReport, JDProfile


JD_ANALYSIS_PROMPT = (
    "You are a job description analyst and resume gap analyst. "
    "Given a resume and a job description, return ONE JSON object with "
    'exactly two keys:\n'
    '1. "jd_profile": the structured JD profile described below.\n'
    '2. "gap_report": the gap analysis described below.\n\n'
    "JD PROFILE INSTRUCTIONS:\n"
    f"{JD_PROFILER_PROMPT}\n\n"
    "GAP ANALYSIS INSTRUCTIONS:\n"
    f"{GAP_ANALYSIS_PROMPT}\n\n"
    "Return ONLY JSON."
)


def profile_and_gaps(
    client: LLMClient,
    resume_text: str,
    jd_text: str,
) -> tuple[JDProfile, GapReport]:
    """Extract a JDProfile and GapReport from one chat completion."""
    user = f"Resume:\n{resume_text}\n\nJob Description:\n{jd_text}"
    result = client.chat_json(JD_ANALYSIS_PROMPT, user)
    profile_raw = result.get("jd_profile") or result
    gap_raw = result.get("gap_report") or {}
    return (
        JDProfile(
            must_have_skills=profile_raw.get("must_have_skills", []),
            nice_to_have_skills=profile_raw.get("nice_to_have_skills", []),
            soft_skills=profile_raw.get("soft_skills", []),
            business_scenarios=profile_raw.get("business_scenarios", []),
            min_years_experience=profile_raw.get("min_years_experience"),
            education_requirements=profile_raw.get(
                "education_requirements", []
            ),
        ),
        GapReport(
            missing_keywords=gap_raw.get("missing_keywords", []),
            misaligned_emphasis=gap_raw.get("misaligned_emphasis", []),
            strength_matches=gap_raw.get("strength_matches", []),
        ),
    )
