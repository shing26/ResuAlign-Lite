import bisect
import json as _json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor

from .llm import LLMClient, _structured_or_json
from .models import DiffItem, TailoredResume
from .schema_registry import DiffItemSchema, TailoredResumeSchema

BULLET_REWRITE_PROMPT_VERSION = "v1"
TAILOR_PROMPT_VERSION = "v1"
METRIC_PLACEHOLDER = "[待人工确认：耗时降低 X% / 支撑 QPS 达 Y]"
_METRIC_HINT_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|倍|万|亿|ms\b|s\b|qps\b|tps\b))|"
    r"\b(?:qps|tps|rt|pv|uv|roi)\b|"
    r"(?:成本降低|耗时降低|性能提升)",
    re.IGNORECASE,
)


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
    "13. Every rewritten experience/project bullet MUST open with a strong \n"
    "    action verb and follow ACTION VERB + TECHNICAL METHOD + BUSINESS \n"
    "    SCENARIO + QUANTIFIED OUTCOME. Avoid adverbs and hollow \n"
    "    'responsible for...' filler.\n"
    "14. If the source bullet has no number/metric, do NOT invent one. Append \n"
    "    a clearly marked editable placeholder such as '[待人工确认：耗时降低 \n"
    "    X% / 支撑 QPS 达 Y]' after the factual clause. Never present the \n"
    "    placeholder as an established fact.\n"
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
        "Rewrite in STAR order: strong action verb + technical method + "
        "business scenario + quantified outcome. If the original has no "
        "number, append a clearly marked editable placeholder such as "
        "'[待人工确认：耗时降低 X% / 支撑 QPS 达 Y]'. Never invent a concrete "
        "metric."
    ),
    "high_concurrency": (
        "Tie the existing facts to high-concurrency, low-latency, or "
        "production platform language when the facts support it. Follow "
        "ACTION VERB + TECHNICAL METHOD + BUSINESS SCENARIO + QUANTIFIED "
        "OUTCOME. Use the JD's exact scenario phrase when available; never "
        "add capabilities the original bullet does not contain."
    ),
    "concise": (
        "Shorten the bullet to one crisp line while preserving every fact "
        "and the original meaning. Do not drop numbers or technologies."
    ),
}


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _has_quantified_metric(text: str) -> bool:
    return bool(_METRIC_HINT_RE.search(text or ""))


def _ensure_metric_placeholder(text: str) -> str:
    if not text or _has_quantified_metric(text):
        return text
    return f"{text.rstrip()} {METRIC_PLACEHOLDER}"


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
    if diff.type in {"modify", "add"} and diff.proposed:
        diff.proposed = _ensure_metric_placeholder(diff.proposed)
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
        "5. Start with a strong action verb and keep the sentence business-\n"
        "   outcome focused: ACTION VERB + METHOD + SCENARIO + RESULT.\n"
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
    proposed = _ensure_metric_placeholder(
        str(result.get("proposed") or "").strip()
    ) if instruction in {"quantified", "high_concurrency"} else str(
        result.get("proposed") or ""
    ).strip()
    diff = DiffItem(
        diff_id=uuid.uuid4().hex,
        type="modify",
        original=original,
        proposed=proposed,
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


# ---------------------------------------------------------------------------
# Bullet-level map-reduce editor (Phase 2, ADR-0032)
# ---------------------------------------------------------------------------

_SECTION_HEADING_MR_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:个人(?:信息|简介)|教育(?:背景|经历)|工作经历|"
    r"项目(?:经历|经验)|专业技能|技能清单|证书|荣誉|自我评价|"
    r"summary|education|work\s+experience|projects?|skills|"
    r"certifications?|awards?)\s*[:：]?\s*$",
    re.IGNORECASE,
)
_BULLET_MR_RE = re.compile(
    r"^\s*(?:[-•▪●○◦·∙‣]|\d+(?:[.、)])|[*])\s+"
)


def split_resume_units(resume_text: str) -> list[dict]:
    """Split a resume into ordered atomic lines for per-bullet editing.

    Each entry is ``{"kind": "heading"|"bullet"|"text", "section": str,
    "text": str}``. Section tracks the nearest preceding heading so bullets
    can be grouped back into ``sections`` for reassembly.
    """
    units: list[dict] = []
    section = ""
    for raw in (resume_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _SECTION_HEADING_MR_RE.match(line):
            section = line.lstrip("#").strip()
            units.append({"kind": "heading", "section": section, "text": line})
        elif _BULLET_MR_RE.match(raw):
            bullet_text = _BULLET_MR_RE.sub("", raw).strip()
            units.append({"kind": "bullet", "section": section, "text": bullet_text})
        else:
            units.append({"kind": "text", "section": section, "text": line})
    return units


def _focus_phrases(gap_report: dict) -> list[str]:
    phrases: list[str] = []
    for key in ("missing_keywords", "misaligned_emphasis", "business_scenarios"):
        for item in (gap_report.get(key) or []):
            if isinstance(item, str) and item.strip():
                phrases.append(item.strip())
    return phrases


def _pick_bullet_instruction(granularity: str, prompt_focus: str) -> str:
    if prompt_focus == "quantified":
        return "quantified"
    if prompt_focus == "skills":
        return "high_concurrency"
    return "concise" if granularity == "fine" else "high_concurrency"


def _resolve_bullet_span(original: str, resume_text: str) -> tuple[int, int] | None:
    if not original:
        return None
    start = resume_text.find(original)
    if start < 0:
        return None
    return (start, start + len(original))


def _rewrite_bullet_with_span(
    client: LLMClient,
    original: str,
    resume_text: str,
    section: str,
    instruction: str,
    jd_context: str,
) -> DiffItem:
    diff = rewrite_bullet(
        client,
        original,
        instruction,
        jd_context=jd_context,
    )
    diff.section = section
    span = _resolve_bullet_span(original, resume_text)
    if span is not None:
        diff.source_span = span
    return diff


def _try_rewrite_bullet(
    client: LLMClient,
    original: str,
    resume_text: str,
    section: str,
    instruction: str,
    jd_context: str,
) -> DiffItem:
    """Rewrite one bullet, degrading to a failed DiffItem instead of raising.

    A failed bullet is kept as an ``invalid_diff`` so Phase 4 can offer
    per-item retry without failing the whole map-reduce run.
    """
    try:
        return _rewrite_bullet_with_span(
            client, original, resume_text, section, instruction, jd_context
        )
    except Exception as exc:  # noqa: BLE001 - degrade per bullet
        return DiffItem(
            diff_id=uuid.uuid4().hex,
            section=section,
            type="modify",
            original=original,
            proposed="",
            reason=f"生成失败，可单条重试: {str(exc)[:80]}",
            confidence="low",
            provenance=original,
            provenance_quote="",
            source_span=_resolve_bullet_span(original, resume_text),
            provenance_state="missing",
        )


def tailor_resume_map_reduce(
    client: LLMClient,
    resume_text: str,
    gap_report_text: str,
    granularity: str = "medium",
    prompt_focus: str = "balanced",
    custom_prompt: str = "",
    jd_context: str = "",
    parallel: bool = True,
) -> TailoredResume:
    """Rewrite a resume bullet-by-bullet, concurrent where safe (ADR-0032).

    Only bullets that relate to the gap report are sent to the model (small,
    stable per-bullet calls). Non-targeted bullets pass through verbatim and
    sections are reassembled deterministically. A single bullet failure is
    recorded as an ``invalid_diff`` (for Phase 4 per-item retry) instead of
    failing the whole run; when every targeted bullet fails the map-reduce
    falls back to whole-document editing so the callers' role fallback still
    has a stable output.
    """
    if granularity not in GRANULARITY_GUIDES:
        raise ValueError(
            f"Invalid granularity: {granularity}; expected fine, medium, or coarse"
        )
    instruction = _pick_bullet_instruction(granularity, prompt_focus)
    try:
        gap_report = _json.loads(gap_report_text or "{}")
    except (ValueError, TypeError):
        gap_report = {}
    focus = _focus_phrases(gap_report)
    jd_context = (jd_context or str(gap_report.get("jd_context") or "")).strip()

    units = split_resume_units(resume_text)
    bullets = [u for u in units if u["kind"] == "bullet"]
    if not bullets:
        # No atomic bullets to rewrite; fall back to whole-document editing.
        return tailor_resume(
            client,
            resume_text,
            gap_report_text,
            granularity=granularity,
            prompt_focus=prompt_focus,
            custom_prompt=custom_prompt,
        )

    focus_lower = [f.lower() for f in focus]

    def _is_target(bullet: dict) -> bool:
        text_lower = bullet["text"].lower()
        return any(f and f in text_lower for f in focus_lower)

    targets = [b for b in bullets if _is_target(b)]
    if not targets:
        # Fall back to the first bullet of the first experience/project/skill
        # section so the editor always yields at least one actionable diff.
        prefer = next(
            (
                section
                for name in ("工作经历", "项目经历", "项目经验", "专业技能",
                             "work experience", "projects", "skills")
                for u in units
                if u["kind"] == "bullet"
                for section in [u["section"]]
                if name.lower() == section.lower()
            ),
            None,
        )
        pool = (
            [b for b in bullets if b["section"] == prefer]
            if prefer
            else bullets
        )
        targets = pool[:1]

    if not parallel or len(targets) <= 1:
        rewrites = [
            _try_rewrite_bullet(
                client, b["text"], resume_text, b["section"],
                instruction, jd_context,
            )
            for b in targets
        ]
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(targets))) as pool:
            rewrites = list(
                pool.map(
                    lambda b: _try_rewrite_bullet(
                        client, b["text"], resume_text, b["section"],
                        instruction, jd_context,
                    ),
                    targets,
                )
            )

    diffs: list[DiffItem] = []
    invalid_diffs: list[DiffItem] = []
    accepted: set[str] = set()
    for diff in rewrites:
        if diff.proposed and diff.proposed.strip():
            accepted.add(diff.original)
            diffs.append(diff)
        else:
            diff.confidence = "low"
            diff.provenance_state = "missing"
            diff.reason = (diff.reason or "") + " [生成失败，可单条重试]"
            invalid_diffs.append(diff)

    # Reassemble sections: targeted bullets replaced with proposed text,
    # everything else preserved verbatim; headings/text pass through.
    sections: dict[str, list[str]] = {}
    for unit in units:
        key = unit["section"] or "摘要"
        if unit["kind"] == "bullet" and unit["text"] in accepted:
            proposed = next(
                (d.proposed for d in rewrites if d.original == unit["text"]),
                unit["text"],
            )
            sections.setdefault(key, []).append(proposed)
        else:
            sections.setdefault(key, []).append(unit["text"])

    if not diffs:
        # Every targeted bullet failed: fall back to whole-document editing so
        # role-level fallback / callers still get a coherent result.
        return tailor_resume(
            client,
            resume_text,
            gap_report_text,
            granularity=granularity,
            prompt_focus=prompt_focus,
            custom_prompt=custom_prompt,
        )

    return TailoredResume(
        sections={k: "\n".join(v) for k, v in sections.items()},
        diffs=diffs,
        invalid_diffs=invalid_diffs,
    )
