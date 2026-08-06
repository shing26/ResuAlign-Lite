"""Combined JD profile and gap analysis in a single LLM round trip."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .gap_analyzer import GAP_ANALYSIS_PROMPT
from .jd_profiler import JD_PROFILER_PROMPT, profile_jd
from .llm import LLMClient
from .models import GapReport, JDProfile

# Cache schema version for the combined JD profile + gap analysis. Bumped to
# v2 because v1 entries were written with legacy alias keys
# (``required_skills``/``nice_to_have``/``business_scene``) that break
# ``JDProfile(**cached)``; reads under the new version never touch v1 rows
# (B3).
JD_ANALYSIS_PROMPT_VERSION = "jd-analysis-v2"

# Fields the current JDProfile model accepts. Cache payloads are filtered
# against this whitelist on read so extra keys are ignored instead of
# crashing the constructor.
_JD_PROFILE_FIELDS = (
    "must_have_skills",
    "nice_to_have_skills",
    "soft_skills",
    "business_scenarios",
    "min_years_experience",
    "education_requirements",
)

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


def jd_profile_to_dict(profile: JDProfile) -> dict:
    """Serialize a JDProfile with the public alias contract."""
    data = asdict(profile)
    data["required_skills"] = profile.required_skills
    data["nice_to_have"] = profile.nice_to_have
    data["business_scene"] = profile.business_scene
    return data


def proactive_jd_profile(
    client: LLMClient,
    jd_text: str,
    cache=None,
    tenant: str = "default",
    model: str | None = None,
) -> JDProfile:
    """Profile a raw JD reusing ``profile_jd`` and the shared content cache."""
    return profile_jd(
        client,
        jd_text,
        cache=cache,
        tenant=tenant,
        model=model,
    )


def _jd_profile_from_cache(raw: dict[str, Any] | None) -> JDProfile | None:
    """Build a JDProfile from a cached payload, ignoring unknown fields."""
    if not isinstance(raw, dict):
        return None
    return JDProfile(
        **{key: raw.get(key) for key in _JD_PROFILE_FIELDS if key in raw}
    )


def _gap_report_from_cache(raw: dict[str, Any] | None) -> GapReport | None:
    """Build a GapReport from a cached payload, ignoring unknown fields."""
    if not isinstance(raw, dict):
        return None
    return GapReport(
        missing_keywords=raw.get("missing_keywords", []),
        misaligned_emphasis=raw.get("misaligned_emphasis", []),
        strength_matches=raw.get("strength_matches", []),
    )


def profile_and_gaps(
    client: LLMClient,
    resume_text: str,
    jd_text: str,
    cache=None,
    tenant: str = "default",
) -> tuple[JDProfile, GapReport]:
    """Extract a JDProfile and GapReport from one chat completion."""
    resolved_model = getattr(client, "model", "default")
    prompt_version = JD_ANALYSIS_PROMPT_VERSION
    content = f"{resume_text}\n\n{jd_text}"
    if cache is not None:
        cached = cache.get(tenant, resolved_model, prompt_version, content)
        if cached is not None:
            profile = _jd_profile_from_cache(cached.get("jd_profile"))
            gap = _gap_report_from_cache(cached.get("gap_report"))
            if profile is not None and gap is not None:
                return profile, gap

    user = f"Resume:\n{resume_text}\n\nJob Description:\n{jd_text}"
    from .llm import _structured_or_json
    from .schema_registry import JDAnalysisSchema

    result = _structured_or_json(
        client,
        JD_ANALYSIS_PROMPT,
        user,
        JDAnalysisSchema,
    )
    profile_raw = result.get("jd_profile") or result
    gap_raw = result.get("gap_report") or {}
    profile = JDProfile(
        must_have_skills=profile_raw.get("must_have_skills", []),
        nice_to_have_skills=profile_raw.get("nice_to_have_skills", []),
        soft_skills=profile_raw.get("soft_skills", []),
        business_scenarios=profile_raw.get("business_scenarios", []),
        min_years_experience=profile_raw.get("min_years_experience"),
        education_requirements=profile_raw.get("education_requirements", []),
    )
    gap = GapReport(
        missing_keywords=gap_raw.get("missing_keywords", []),
        misaligned_emphasis=gap_raw.get("misaligned_emphasis", []),
        strength_matches=gap_raw.get("strength_matches", []),
    )
    if cache is not None:
        cache.put(
            tenant,
            resolved_model,
            prompt_version,
            content,
            {
                "jd_profile": jd_profile_to_dict(profile),
                "gap_report": {
                    "missing_keywords": gap.missing_keywords,
                    "misaligned_emphasis": gap.misaligned_emphasis,
                    "strength_matches": gap.strength_matches,
                },
            },
        )
    return profile, gap