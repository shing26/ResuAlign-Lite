"""LLM job classification with controlled vocabulary normalization."""

from __future__ import annotations

from typing import Any, Sequence

from .job_library import JOB_FUNCTIONS, SENIORITIES

_CLASSIFIER_SYSTEM_PROMPT = (
    "You are a job classifier. Given a job description, return JSON with "
    "job_function (one of the supplied vocabulary), seniority (one of the "
    "supplied vocabulary), and tech_tags (a list of free-form technology or "
    "domain tags). Output ONLY JSON."
)


def normalize_enum(
    value: str | None,
    choices: Sequence[str],
    default: str,
) -> str:
    """Match a raw value to a controlled choice by substring, else default."""
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    for choice in choices:
        if choice.lower() in normalized:
            return choice
    return default


def classify_job(
    client: Any,
    jd_text: str,
    job_functions: Sequence[str] | None = None,
    seniorities: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Classify a JD into function, seniority, and tech/domain tags."""
    functions = list(job_functions or JOB_FUNCTIONS)
    levels = list(seniorities or SENIORITIES)
    function_default = "其他" if "其他" in functions else (
        functions[0] if functions else "其他"
    )
    seniority_default = "未知" if "未知" in levels else (
        levels[0] if levels else "未知"
    )
    user_prompt = (
        "Job description:\n"
        f"{jd_text}\n\n"
        f"Job functions: {', '.join(functions)}\n"
        f"Seniorities: {', '.join(levels)}\n"
        'Respond as JSON: {"job_function": "...", "seniority": "...", '
        '"tech_tags": ["..."]}'
    )
    raw = client.chat_json(_CLASSIFIER_SYSTEM_PROMPT, user_prompt)
    raw_tags = raw.get("tech_tags") or []
    tags = [
        str(tag).strip()
        for tag in raw_tags
        if str(tag).strip()
    ]
    return {
        "job_function": normalize_enum(
            raw.get("job_function"), functions, function_default
        ),
        "seniority": normalize_enum(
            raw.get("seniority"), levels, seniority_default
        ),
        "tech_tags": tags,
    }
