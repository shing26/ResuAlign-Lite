import bisect
import re
import uuid

from .llm import LLMClient, _structured_or_json
from .models import DiffItem, TailoredResume
from .schema_registry import DiffItemSchema, TailoredResumeSchema

BULLET_REWRITE_PROMPT_VERSION = "v1"
TAILOR_PROMPT_VERSION = "v1"


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
    "diffs (list of objects with type in ['modify','add','remove'], section, \n"
    "original, proposed, reason, confidence in ['high','medium','low'], \n"
    "provenance).\n"
    "Return at most 15 diffs, prioritizing the highest-impact gaps, and \n"
    "keep each reason under 80 characters.\n"
    "For each diff, section is the name of the resume section the diff \n"
    "belongs to (e.g. '项目经历', '工作经历', '教育经历'); use the exact \n"
    "section name as it appears in the resume.\n"
    "Output ONLY JSON."
    "## Output Constraints\\n"
    "- Max tokens: 1500\\n"
    "- Temperature: 0.0\\n"
    "- Never invent facts: every entity must be traceable to the original resume\\n"
    "- If uncertain: leave section unchanged\\n"
    "- Output ONLY valid JSON, no markdown fences\\n"
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

BULLET_INSTRUCTIONS = {
    "quantified": (
        "Re-emphasize measurable outcomes that already exist in the bullet "
        "(numbers, percentages, counts, or reductions). Never invent or "
        "inflate metrics that are absent from the original bullet."
    ),
    "high_concurrency": (
        "Tie the existing facts to high-concurrency, low-latency, or "
        "production platform language when the facts support it. Use the "
        "JD's exact scenario phrase when available; never add capabilities "
        "the original bullet does not contain."
    ),
    "concise": (
        "Shorten the bullet to one crisp line while preserving every fact "
        "and the original meaning. Do not drop numbers or technologies."
    ),
}


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _normalized_char_map(text: str) -> tuple[str, list[int]]:
    """Return whitespace-collapsed text plus a char->original index map."""
    norm_chars: list[str] = []
    map_to_original: list[int] = []
    index = 0
    length = len(text)
    while index < length:
        if text[index].isspace():
            start = index
            while index < length and text[index].isspace():
                index += 1
            norm_chars.append(" ")
            map_to_original.append(start)
        else:
            norm_chars.append(text[index])
            map_to_original.append(index)
            index += 1
    return "".join(norm_chars), map_to_original


def _resolve_span(
    quote: str, resume_text: str, start_index: int = 0
) -> tuple[int, int] | None:
    """Locate a provenance quote with exact or whitespace-normalized matching."""
    if not quote:
        return None
    exact = resume_text.find(quote, start_index)
    if exact >= 0:
        return (exact, exact + len(quote))
    normalized_text, char_map = _normalized_char_map(resume_text)
    normalized_quote = _normalize_whitespace(quote)
    normalized_start = bisect.bisect_left(char_map, start_index) if start_index else 0
    position = normalized_text.find(normalized_quote, normalized_start)
    if position < 0 or position >= len(char_map):
        return None
    start = char_map[position]
    end_index = position + len(normalized_quote)
    end = char_map[end_index] if end_index < len(char_map) else len(resume_text)
    return (start, end)


def parse_diff_with_provenance(
    item: dict,
    resume_text: str,
) -> tuple[DiffItem, bool]:
    """Build a DiffItem and verify its provenance against the source resume."""
    diff_type = item.get("type", "modify")
    if diff_type not in {"modify", "add", "remove"}:
        diff_type = "modify"
    confidence = item.get("confidence", "medium")
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    original = item.get("original", "")
    quote = str(item.get("provenance_quote") or item.get("provenance") or "").strip()
    source_span = None
    valid = False
    provenance_state = "pending_review"
    source_span = _resolve_span(quote, resume_text)
    if source_span is None and quote and (":" in quote or "：" in quote):
        # Section-prefixed quote ("工作经历: 使用 Python ...") fails exact
        # match when the resume uses "工作经历\n- 使用 Python ...". Strip the
        # prefix (ASCII or full-width colon) and retry against the bullet text.
        prefix, stripped = (part.strip() for part in re.split(r"[:：]", quote, maxsplit=1))
        if stripped:
            heading = str(item.get("section") or "").strip() or prefix
            heading_index = resume_text.find(heading) if heading else -1
            candidates = [(stripped, 0)]
            if heading_index >= 0:
                candidates.insert(0, (stripped, heading_index))
            for candidate, start_index in candidates:
                source_span = _resolve_span(candidate, resume_text, start_index)
                if source_span is not None:
                    break
    if quote and source_span is not None:
        valid = True
        provenance_state = "verified"
    elif quote:
        provenance_state = "missing"
    elif diff_type == "add" and not str(original).strip():
        provenance_state = "missing"
    diff = DiffItem(
        diff_id=str(item.get("diff_id") or uuid.uuid4().hex),
        section=str(item.get("section") or ""),
        type=diff_type,
        original=original,
        proposed=item.get("proposed", ""),
        reason=item.get("reason", ""),
        confidence=confidence,
        provenance=quote if valid else item.get("provenance", ""),
        provenance_quote=quote if valid else "",
        source_span=source_span,
        provenance_state=provenance_state,
    )
    return diff, valid


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
    result = _structured_or_json(client, system, user, TailoredResumeSchema)
    diffs = []
    invalid_diffs = []
    strict_provenance = bool(getattr(client, "strict_provenance", False))
    for item in result.get("diffs", []):
        diff, valid = parse_diff_with_provenance(item, resume_text)
        if diff.type == "add" and not diff.original.strip():
            invalid_diffs.append(diff)
            continue
        if not valid and strict_provenance:
            invalid_diffs.append(diff)
        else:
            diffs.append(diff)
            if not valid:
                invalid_diffs.append(diff)
    return TailoredResume(
        sections=result.get("sections", {}),
        diffs=diffs,
        invalid_diffs=invalid_diffs,
    )


def rewrite_bullet(
    client: LLMClient,
    original: str,
    instruction: str,
    jd_context: str | None = None,
    cache=None,
    tenant: str = "default",
    model: str | None = None,
) -> DiffItem:
    """Rewrite one resume bullet with a whitelisted instruction."""
    if instruction not in BULLET_INSTRUCTIONS:
        raise ValueError(
            f"Invalid instruction: {instruction}; expected "
            "quantified, high_concurrency, or concise"
        )
    original = (original or "").strip()
    if not original:
        raise ValueError("Original bullet is required")
    resolved_model = model or getattr(client, "model", "default")
    content = f"{instruction}\n{original}\n{jd_context or ''}"
    if cache is not None:
        cached = cache.get(
            tenant,
            resolved_model,
            BULLET_REWRITE_PROMPT_VERSION,
            content,
        )
        if cached is not None:
            return DiffItem(
                diff_id=uuid.uuid4().hex,
                type="modify",
                original=original,
                proposed=cached.get("proposed", ""),
                reason=cached.get("reason", ""),
                confidence="high",
                provenance=original,
                provenance_quote=original,
                source_span=(0, len(original)),
                provenance_state="verified",
            )

    system = (
        "You rewrite exactly one resume bullet for a job application.\n"
        "RULES:\n"
        "1. Preserve every fact, technology, and metric already present.\n"
        "2. NEVER invent skills, experience, tools, or numbers.\n"
        "3. Apply the requested instruction to the existing facts.\n"
        "4. Keep the same language as the original bullet.\n"
        "Return ONLY JSON: {\"proposed\": \"...\", \"reason\": \"...\"}."
    )
    user = (
        f"Original bullet:\n{original}\n\n"
        f"Instruction: {BULLET_INSTRUCTIONS[instruction]}\n\n"
        f"JD context:\n{jd_context or '(none)'}"
    )
    result = _structured_or_json(
        client,
        system,
        user,
        DiffItemSchema,
        model=resolved_model,
    )
    diff = DiffItem(
        diff_id=uuid.uuid4().hex,
        type="modify",
        original=original,
        proposed=str(result.get("proposed") or "").strip(),
        reason=str(result.get("reason") or "").strip(),
        confidence="high",
        provenance=original,
        provenance_quote=original,
        source_span=(0, len(original)),
        provenance_state="verified",
    )
    if cache is not None:
        cache.put(
            tenant,
            resolved_model,
            BULLET_REWRITE_PROMPT_VERSION,
            content,
            {"proposed": diff.proposed, "reason": diff.reason},
        )
    return diff
