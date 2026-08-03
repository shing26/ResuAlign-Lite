from .llm import LLMClient
from .models import JDProfile


JD_PROFILER_PROMPT = (
    "You are a job description analyst. Given a job description, "
    "extract structured information. Return JSON with: "
    "must_have_skills (list of strings), nice_to_have_skills (list of strings), "
    "soft_skills (list of strings), business_scenarios (list of strings), "
    "min_years_experience (int or null), education_requirements (list of strings). "
    "must_have_skills must include delivery/platform skills (Docker, "
    "Kubernetes, CI/CD) and performance/observability expectations (metrics, "
    "latency, tracing) when the JD mentions them. "
    "business_scenarios must include platform-level phrases such as "
    "'high concurrency', 'low latency', 'millions of requests per day', "
    "'production deployment', and 'observability' even when they appear in "
    "the opening paragraph rather than a bullet. Every platform-level phrase "
    "that appears in the JD must appear verbatim in business_scenarios; never "
    "omit one that is present. Include hyphenated compound scenarios from the "
    "opening paragraph verbatim as well (e.g., 'high-concurrency platform', "
    "'millions of requests per day'); do not paraphrase them. "
    "Output ONLY JSON."
)


def profile_jd(client: LLMClient, jd_text: str) -> JDProfile:
    """Extract structured profile from a raw job description."""
    result = client.chat_json(JD_PROFILER_PROMPT, jd_text)
    return JDProfile(
        must_have_skills=result.get("must_have_skills", []),
        nice_to_have_skills=result.get("nice_to_have_skills", []),
        soft_skills=result.get("soft_skills", []),
        business_scenarios=result.get("business_scenarios", []),
        min_years_experience=result.get("min_years_experience"),
        education_requirements=result.get("education_requirements", []),
    )
