from .llm import LLMClient
from .models import TailoredResume, DiffItem


TAILOR_PROMPT = (
    "You are a precise resume editor. Given a resume and a gap report, \n"
    "rewrite the resume to address gaps while preserving every existing fact.\n"
    "RULES:\n"
    "1. NEVER invent skills, experience, or metrics.\n"
    "2. May rephrase, reorder, or re-emphasize existing facts only.\n"
    "3. Keep every section that already aligns; include it unchanged.\n"
    "4. When the resume already supports a JD keyword (e.g., Redis caching), \n"
    "   rewrite that bullet to tie it to the JD business scenario (e.g., high \n"
    "   concurrency) using only facts already present in the resume. When the \n"
    "   JD pairs a skill with a scenario, keep the exact paired phrase in the \n"
    "   rewritten bullet (e.g., 'Redis caching for high concurrency'), not a \n"
    "   paraphrase.\n"
    "5. The Gap Report may include business_scenarios and jd_context; use \n"
    "   those as rewriting context. Example: \n"
    "   resume says 'Used Redis for cache storage and session management' and \n"
    "   the JD says high concurrency; rewrite as 'Used Redis caching for hot \n"
    "   data and session management on the high-concurrency platform'. Never \n"
    "   add metrics, tools, or skills that are absent from the resume.\n"
    "6. Each change must include the exact source sentence as provenance.\n"
    "7. When the JD names a capability and the resume supports it, use the \n"
    "   JD's exact phrase in the rewritten bullet (e.g., 'Airflow scheduling \n"
    "   and orchestration', 'FastAPI async endpoints') instead of a paraphrase.\n"
    "8. After rewriting, verify that every missing_keyword and misaligned_ \n"
    "   emphasis item from the Gap Report is covered by at least one section \n"
    "   or diff; do not drop an earlier addressed gap when applying later rules.\n"
    "9. When the JD asks for production deployment, performance metrics, \n"
    "   latency, observability, or containerization, and the resume contains \n"
    "   any supporting fact (deployed, monitored, optimized, profiled, \n"
    "   measured, containerized), re-emphasize that fact using the JD phrase, \n"
    "   e.g. 'production Kubernetes deployment evidence', 'low latency \n"
    "   performance metrics', 'observability and tracing', 'Docker and \n"
    "   Kubernetes deployment workflows'.\n"
    "10. When the resume is written in a non-English language, keep the \n"
    "    JD capability phrases in English verbatim inside the rewritten \n"
    "    bullet (e.g., 'production Kubernetes deployment', 'FastAPI async \n"
    "    endpoints', 'Docker and Kubernetes deployment workflows'); do not \n"
    "    translate technical keywords. Preserve the resume's original \n"
    "    language everywhere else.\n"
    "11. When the JD pairs a skill with a scenario (e.g., Redis caching for \n"
    "    high concurrency), keep the exact scenario word (e.g., 'high \n"
    "    concurrency') in the same bullet; do not replace it with a \n"
    "    different scenario phrase such as 'production platform' or \n"
    "    'production deployment'. When the JD names a platform-level \n"
    "    scenario (e.g., 'high concurrency', 'high-concurrency platform', \n"
    "    'millions of requests per day') and the resume supports a related \n"
    "    skill bullet (e.g., Redis caching), include the platform-level \n"
    "    phrase in the same bullet as the skill, even when the JD also \n"
    "    gives the skill a narrower scenario (e.g., 'Redis caching for hot \n"
    "    data and rate limiting' becomes 'Used Redis caching for hot data \n"
    "    and rate limiting on the high-concurrency platform').\n"
    "12. Scan jd_context (the original JD text) for exact skill-plus-scenario \n"
    "    phrases such as 'Redis caching for hot data and rate limiting', \n"
    "    'high-concurrency platform', 'async FastAPI services', 'low \n"
    "    latency', 'millions of requests per day'. If the resume supports \n"
    "    the skill, echo the JD phrase in the rewritten bullet with its \n"
    "    scenario words exactly as written. For non-English resumes, include \n"
    "    the English phrase verbatim alongside the translated text (e.g., \n"
    "    write 'FastAPI async endpoints' as well as the Chinese rendering).\n"
    "Return ONLY a JSON object with exactly two keys:\n"
    "sections (object mapping section_name to rewritten plain text),\n"
    "diffs (list of objects with type in ['modify','add','remove'], original, \n"
    "proposed, reason, confidence in ['high','medium','low'], provenance).\n"
    "Output ONLY JSON."
)

GRANULARITY_GUIDES = {
    "fine": (
        "GRANULARITY: fine. Rewrite only the exact bullets that fail to "
        "match the JD. Preserve the original section order, bullet count, "
        "wording, and length as much as possible."
    ),
    "medium": (
        "GRANULARITY: medium. Rewrite within the existing resume structure. "
        "Keep section headings and the overall order, but freely rephrase "
        "bullets and re-emphasize supported facts to close gaps."
    ),
    "coarse": (
        "GRANULARITY: coarse. Restructure aggressively: reorder sections and "
        "bullets, merge or split entries, and rewrite wording as needed, "
        "while still preserving every existing fact with provenance."
    ),
}

PROMPT_FOCUS_GUIDES = {
    "balanced": (
        "FOCUS: balanced. Follow the general rules without extra emphasis."
    ),
    "quantified": (
        "FOCUS: quantified. When the resume already contains measurable "
        "outcomes (numbers, percentages, counts, or reductions), keep and "
        "re-emphasize them in the rewritten bullets; never invent or inflate "
        "numbers that are absent from the resume."
    ),
    "skills": (
        "FOCUS: skills. Prioritize exact JD skill and scenario phrases over "
        "general wording; make sure every missing_keyword is addressed by "
        "bullets that use facts already present in the resume."
    ),
}


def tailor_resume(
    client: LLMClient,
    resume_text: str,
    gap_report_text: str,
    granularity: str = "medium",
    prompt_focus: str = "balanced",
    custom_prompt: str = "",
) -> TailoredResume:
    """Rewrite resume to close gaps. Every diff carries provenance."""
    guide = GRANULARITY_GUIDES.get(granularity)
    if guide is None:
        raise ValueError(
            f"Invalid granularity: {granularity}; expected "
            "fine, medium, or coarse"
        )
    focus_guide = PROMPT_FOCUS_GUIDES.get(prompt_focus)
    if focus_guide is None:
        raise ValueError(
            f"Invalid prompt_focus: {prompt_focus}; expected "
            "balanced, quantified, or skills"
        )
    user = f"Resume:\n{resume_text}\n\nGap Report:\n{gap_report_text}"
    system = f"{TAILOR_PROMPT}\n\n{guide}\n\n{focus_guide}"
    custom = (custom_prompt or "").strip()
    if custom:
        system += (
            f"\n\nUSER REQUIREMENTS:\n{custom}\n\n"
            "The user requirements above may only prioritize, reorder, "
            "rephrase, or re-emphasize facts already present in the original "
            "resume. They may never instruct you to invent, infer, or "
            "fabricate skills, experience, metrics, tools, or any other fact "
            "not present in the original resume."
        )
    result = client.chat_json(system, user)
    diffs = []
    for item in result.get("diffs", []):
        diff_type = item.get("type", "modify")
        if diff_type not in {"modify", "add", "remove"}:
            diff_type = "modify"
        confidence = item.get("confidence", "medium")
        if confidence not in {"high", "medium", "low"}:
            confidence = "medium"
        diffs.append(DiffItem(
            type=diff_type,
            original=item.get("original", ""),
            proposed=item.get("proposed", ""),
            reason=item.get("reason", ""),
            confidence=confidence,
            provenance=item.get("provenance", ""),
        ))
    return TailoredResume(
        sections=result.get("sections", {}),
        diffs=diffs,
    )
