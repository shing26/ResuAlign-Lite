import bisect
import re
import uuid

from .llm import LLMClient, _structured_or_json
from .models import DiffItem, TailoredResume
from .schema_registry import DiffItemSchema, TailoredResumeSchema

# PROMPT_VERSION bump: bullet_rewrite/v2 -> v3（2026-08-27，黄金核心 1：Few-Shot 强动词库）
# 本次升级说明：
# - 变更点 1：新增强动词库（构建/设计/落地/优化…）与禁止弱动词（负责/参与/协助…）
# - 变更点 2：proposed 强制「强动词 + 具象机制 + 量化插槽」三件套，杜绝「负责系统优化」空话
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效。
BULLET_REWRITE_PROMPT_VERSION = "v3"
# PROMPT_VERSION bump: tailor/v1 -> v2（2026-08-25，对照 04b-PE §2.5）
# 本次升级说明：
# - 变更点 1：14 条编号规则压缩为 7 条，去掉「用 JD 原话」重复堆砌
# - 变更点 2：diffs 由「at most 15」封顶为 3-10 条；proposed ≤ 250 字、reason ≤ 40 字；
#   sections 只含改动章节（消费方缺席回退原文已确认：engine.py:278-280、
#   api/routers/jobs.py:461 draft 走 diffs 而非全量 sections）
# - 变更点 3：删除假指令 Max tokens: 1500 / Temperature（editor 90s×2 超时风险）
# - 变更点 4：provenance/original 必须逐字匹配原文，add 型 original 为空字符串
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效。
TAILOR_PROMPT_VERSION = "v2"

BULLET_REWRITE_PROMPT = """PROMPT_VERSION: bullet_rewrite/v3

你是简历单条要点改写器。针对一条简历要点（bullet）按给定指令改写，用于投递指定 JD。

## 铁律
1. 保留原条目的每一个事实、技术、指标；禁止新增技能、经验、工具、公司或数字；
2. 只应用给定指令到已有事实上，不得发明或推断。

## 强动词库（Few-Shot：从下面的动词起步，绝不使用弱动词）
优先使用：构建、设计、落地、优化、重构、驱动、支撑、主导、搭建、打通、调优、攻克、沉淀、推广、量化
禁止使用：负责、参与、协助、了解、熟悉（这些是简历空话；出现即视为失败输出）
每条 proposed 必须满足「强动词 + 具象机制（如联合索引/读写分离/本地缓存）+ 量化插槽 [X%]」三件套；
若原文无数字，保留 [待人工确认：…] 占位符并由用户补齐，绝不编造具体数值。

## Output Contract（只能输出一个 JSON 对象，2 个字段）
键名固定为：proposed / reason

- proposed：改写后的新文本，≤ 250 字；保持与原文同语言；JD 技术短语（如 "production Kubernetes deployment"、"FastAPI async endpoints"）保留英文原文；必须含强动词与具象机制。
- reason：一句话理由，≤ 40 字。

## 提交前自查
- proposed 中每个技术名词与数字都能在原文找到依据；无新增事实；长度在上限内；
- proposed 不含「负责/参与/协助/了解/熟悉」等弱动词；
- 只输出 JSON，无 markdown fence，无解释文字。"""
METRIC_PLACEHOLDER = "[待人工确认：耗时降低 X% / 支撑 QPS 达 Y]"
_METRIC_HINT_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|倍|万|亿|ms\b|s\b|qps\b|tps\b))|"
    r"\b(?:qps|tps|rt|pv|uv|roi)\b|"
    r"(?:成本降低|耗时降低|性能提升)",
    re.IGNORECASE,
)


TAILOR_PROMPT = """PROMPT_VERSION: tailor/v2

你是精确的简历编辑器。给定主简历与差距报告，重写简历以弥合差距。铁律：不得编造。禁止新增简历中不存在的技能、经验、指标、工具、公司或项目；只允许改述、重排、重强调已有事实。

## Output Contract（只能输出一个 JSON 对象，2 个字段）
{"sections": {章节名: 重写后的纯文本}, "diffs": [...]}

### sections
- 只包含【发生了改动】的章节；未改动章节不要放入本对象（调用方会用原文合并）。
- 每章为纯文本，保持原文 Markdown 列表风格；技术名词保留原文英文拼写。
- 部署注意：当前实施已确认「sections 消费方在缺席时回退原文」（`engine.py:278-280`，draft 由 `_apply_diffs` 生成走 diffs 而非 sections，`api/routers/jobs.py:461`）——**「只含改动章节」模式可直接启用**；若未来消费方变化，本约束可降级为「sections 含所有章节，未改动章节与原文逐字一致」。

### diffs：3-10 条，按影响从大到小；每条对象字段（键名固定）
{
  "type": "modify" | "add" | "remove",
  "section": 简历中的确切章节名（逐字节写自简历标题，如"项目经历"、"工作经历"），
  "original": "modify/remove 时 = 简历原文的逐字子串；add 时 = 空字符串 ""\",
  "proposed": "改写后的新文本，≤ 250 字",
  "reason": "一句话理由，≤ 40 字，说清改了什么、为什么更贴近 JD",
  "confidence": "high" | "medium" | "low",
  "provenance": "逐字节写自简历原文的出处句；modify/remove 时与 original 一致；add 时 = 相邻的支持句（必须逐字存在于原文）"
}

## 改写规则
1. 只允许：改述、重排、重强调简历中已存在的事实；禁止发明或推断任何事实。
2. 简历已支持 JD 关键词时，用 JD 的确切短语改写该条（如 "Redis caching for high concurrency"），但只能依托简历已有事实，不新增能力。
3. 原文无数字/指标时禁止补数；在事实句后附加明确标注的占位符 "[待人工确认：耗时降低 X% / 支撑 QPS 达 Y]"，不得把占位符当事实呈现。
4. 每条 proposed 的技术名词、业务场景短语必须能在 original 或简历原文中找到依据；provenance 必须逐字匹配简历原文（允许空白差异，不允许大意或改写）。
5. 覆盖检查：完成后确认差距报告中每个 missing_keyword / misaligned_emphasis 至少被一条 diff 或一个改动的章节覆盖；无法用已有事实覆盖的，不要硬凑。
6. 语言：与简历原文同语言；JD 技术短语保留英文原文（如 "production Kubernetes deployment"、"FastAPI async endpoints"）。
7. section 字段逐字节写简历中的章节标题。

## 提交前自查
- 每个 provenance / original 都能在简历原文逐字找到；
- proposed 中不得出现原文没有的技术名、数字、公司、项目名；
- diffs 数量 ≤ 10；type / confidence 只用枚举值；add 型 original 必须为空字符串；
- 只输出一个 JSON 对象，无 markdown fence，无解释文字。"""

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

    system = BULLET_REWRITE_PROMPT
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
