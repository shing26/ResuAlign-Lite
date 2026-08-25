"""Resume optimizer: overall analysis + modular project-experience polish.

Mirrors the xzjobs "--section=resume 简历优化" flow:

1. **整体分析 (overview)** — fully local and deterministic (rule-based
   diagnosis + quantified highlights + optional JD keyword overlap). It never
   calls the LLM, so it can never time out; it is the always-available first
   step, like the reference site's instant overall assessment.
2. **模块化优化/润色 (polish)** — each project-experience entry ("项目经历",
   falling back to work/internship entries) is rewritten in ONE independent
   LLM call (STAR-style, facts preserved, no invented metrics). Modules are
   isolated on purpose: a timeout / 402 / rate-limit on one entry is recorded
   as an item-level ``failed`` and never blocks the other entries.

This replaces the previous "rewrite the whole resume in one LLM pass"
(pipeline 取舍咨询的第三项) with a bounded, per-module design: smaller
per-call latency, no whole-document blast radius, and user-controlled
accept/reject per item (xzjobs-like).
"""

from __future__ import annotations

import re

from .engine import MAX_RESUME_INPUT_CHARS, truncate_text
from .llm import LLMClient, LLMResponseError
from .role_router import _role_timeout
from .rule_diagnose import _SKILL_KEYWORDS, diagnose_resume_local

# ---------------------------------------------------------------------------
# Section / entry parsing
# ---------------------------------------------------------------------------

# Section headings that own optimizable "experience" content, in the order a
# Chinese resume would use. Everything else (education/skills/awards) is only
# used as a boundary to stop a section.
_SECTION_HEADING_LINE_RE = re.compile(
    r"^(?:#\s*)?(?:项目经历|项目经验|项目实践|科研经历|工作经历|工作经验|"
    r"实习经历|projects?|work\s+experience|employment\s+history|"
    r"internship|experience)[\s:：]*$",
    re.IGNORECASE,
)
_BOUNDARY_HEADING_LINE_RE = re.compile(
    r"^(?:#\s*)?(?:个人(?:信息|简介)|教育(?:背景|经历)|技能(?:清单|栈)?|"
    r"专业技能|证书|荣誉|自我评价|summary|education|skills?|"
    r"certifications?|awards?)[\s:：]*$",
    re.IGNORECASE,
)
_DATE_RANGE_RE = re.compile(
    r"\d{2,4}\s*[-—~–至/.]\s*(\d{2,4}|至今|现在|present|now)\b"
    r"|\d{4}\s*年\s*[-—~–至/.]?\s*\d{0,4}\s*月?"
    r"|(?:至今|现在|present|now)\s*$",
    re.IGNORECASE,
)
# A line whose *whole* content is a date range, e.g. "2023.01 - 2023.06",
# "2020 年 3 月 - 2020 年 9 月", "至今". Used to merge "## 项目名" + date.
_DATE_ONLY_LINE_RE = re.compile(
    r"^[\d\s\-—~～–至/.年月日－presentnow ]+$",
    re.IGNORECASE,
)
_ENTRY_HEADER_SPLIT_RE = re.compile(r"[|｜·•]")
_BULLET_PREFIX_RE = re.compile(r"^[\s]*[-*•▪●○◦·∙‣◦◆◇■□★☆※]\s*")
_QUANT_LINE_RE = re.compile(
    r"\d+(?:\.\d+)?\s*"
    r"(?:%|％|万|亿|倍|人|单|次|个|项|条|天|年|月|"
    r"QPS|TPS|RPS|并发|ms|s|秒|毫秒|MB|GB|TB|千万|百万)",
    re.IGNORECASE,
)


def _is_entry_header_line(line: str, current_entry_lines: list[str]) -> bool:
    """True when ``line`` looks like the start of a new entry (title row)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _BULLET_PREFIX_RE.match(stripped):
        return False
    # "2023.01 - 至今 项目名" or title rows with separators ("XX项目 | 负责人")
    if _DATE_RANGE_RE.search(stripped):
        return True
    if len(stripped) <= 60 and _ENTRY_HEADER_SPLIT_RE.search(stripped):
        return True
    # A very short bare line after an existing entry is a title row too.
    if current_entry_lines and len(stripped) <= 30 and not re.search(r"[。！？!?；;]", stripped):
        return True
    return False


def extract_project_modules(resume_text: str) -> list[dict]:
    """Split experience sections into per-entry modules.

    Returns a list of ``{module, index, title, original}`` where ``module`` is
    the section heading as written (e.g. "项目经历"), ``index`` is 0-based
    within that section, ``title`` is the first meaningful line, and
    ``original`` is the whole entry text (title + bullets) used for both the
    polish prompt and the apply-time exact replacement.
    """
    text = (resume_text or "").strip()
    if not text:
        return []
    lines = text.splitlines()
    # Collect ranges for every recognized boundary heading (experience ones
    # keep the body; other sections just cut the previous body).
    starts: list[int] = []
    for i, raw in enumerate(lines):
        heading = raw.strip().lstrip("#").strip()
        if _SECTION_HEADING_LINE_RE.match(heading) or _BOUNDARY_HEADING_LINE_RE.match(heading):
            starts.append(i)
    if not starts:
        return []
    starts.append(len(lines) + 1)

    modules: list[dict] = []
    for pos, start in enumerate(starts[:-1]):
        heading_raw = lines[start].strip().lstrip("#").strip()
        if not _SECTION_HEADING_LINE_RE.match(heading_raw):
            continue
        section_name = heading_raw
        end = starts[pos + 1] - 1
        body = lines[start + 1 : end]
        entries = _split_section_into_entries(body)
        for index, entry_lines in enumerate(entries):
            entry_text = "\n".join(entry_lines).strip()
            if not entry_text:
                continue
            title = _entry_title(entry_lines) or f"{section_name} 第{index + 1}条"
            modules.append(
                {
                    "module": section_name,
                    "index": index,
                    "title": title[:60],
                    "original": entry_text,
                }
            )
    return modules


def _looks_like_title_line(line: str) -> bool:
    """True for a short bare line that could be an entry title row."""
    stripped = line.strip().lstrip("#").strip()
    if not stripped or _BULLET_PREFIX_RE.match(stripped):
        return False
    if re.search(r"[。！？!?；;]", stripped):
        return False
    return len(stripped) <= 60


def _split_section_into_entries(body: list[str]) -> list[list[str]]:
    """Group a section body into entries separated by blank lines/title rows."""
    entries: list[list[str]] = []
    current: list[str] = []
    previous_blank = False
    for raw in body:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            previous_blank = True
            continue
        if (previous_blank or _is_entry_header_line(stripped, current)) and current:
            # "## 智能客服系统\n2023.01 - 2023.06\n- 要点": a date-only line
            # right after a bare title line belongs to the same entry, not a
            # new one.
            if (
                not previous_blank
                and len(current) == 1
                and _looks_like_title_line(current[0])
                and _DATE_ONLY_LINE_RE.match(stripped)
                and _DATE_RANGE_RE.search(stripped)
            ):
                current.append(line)
                previous_blank = False
                continue
            entries.append(current)
            current = []
        current.append(line)
        previous_blank = False
    if current:
        entries.append(current)
    return [entry for entry in entries if entry]


def _entry_title(entry_lines: list[str]) -> str:
    for line in entry_lines:
        stripped = _BULLET_PREFIX_RE.sub("", line).strip()
        if stripped:
            return stripped[:60]
    return ""


# ---------------------------------------------------------------------------
# Overall analysis (local, deterministic)
# ---------------------------------------------------------------------------

def build_overview(resume_text: str, jd_text: str | None = None) -> dict:
    """Build the xzjobs-style overall analysis without any LLM call.

    Combines the rule-based diagnosis (score/issues/skills) with quantified
    highlights and, when a JD is provided, a cheap keyword-overlap view.
    """
    text = truncate_text(resume_text or "", MAX_RESUME_INPUT_CHARS)
    diagnosis = diagnose_resume_local(text)
    score = int(diagnosis.get("score", 0))
    verdict = "优秀" if score >= 80 else "建议优化" if score >= 60 else "需重点优化"

    highlights: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = _BULLET_PREFIX_RE.sub("", raw).strip()
        if not line or len(line) < 8:
            continue
        if _QUANT_LINE_RE.search(line) and line not in seen:
            seen.add(line)
            highlights.append(line)
        if len(highlights) >= 6:
            break

    sections_found: list[str] = []
    for raw in (text or "").splitlines():
        heading = raw.strip().lstrip("#").strip()
        if heading and _SECTION_HEADING_LINE_RE.match(heading) and heading not in sections_found:
            sections_found.append(heading)

    jd = None
    jd_raw = (jd_text or "").strip()
    if jd_raw:
        resume_lower = text.lower()
        jd_lower = jd_raw.lower()
        matched: list[str] = []
        unmatched: list[str] = []
        for kw in _SKILL_KEYWORDS:
            in_jd = kw.lower() in jd_lower
            if not in_jd:
                continue
            if kw.lower() in resume_lower:
                matched.append(kw)
            else:
                unmatched.append(kw)
        jd = {
            "provided": True,
            "matched_keywords": matched[:12],
            "unmatched_keywords": unmatched[:12],
            "keyword_hits": len(matched),
        }

    return {
        "score": score,
        "verdict": verdict,
        "skills": diagnosis.get("skills", []),
        "issues": diagnosis.get("issues", []),
        "highlights": highlights,
        "project_count": len(extract_project_modules(text)),
        "sections_found": sections_found,
        "generated_by": "local-rules",
        "jd": jd,
    }


# ---------------------------------------------------------------------------
# Per-module LLM polish
# ---------------------------------------------------------------------------

POLISH_PROMPT = """PROMPT_VERSION: polish/v2

你是资深简历润色专家。针对下面给出的单条「项目/工作经历」条目，用 STAR 法则（情境-任务-行动-结果）润色为更专业、更有说服力的表述。

## Output Contract（只能输出一个 JSON 对象，2 个字段）
键名固定为：optimized / rationale

- optimized：润色后的整段内容（含标题行），≤ 600 字，且不超过输入条目的 1.5 倍长度。
- rationale：一句话中文说明，≤ 40 字，说清改了什么、为什么更契合 HR/ATS。

## 硬性规则
1. 必须保留条目的事实行（项目名称、时间、公司/团队/角色），不得改动或删除；
2. 严禁编造数据、指标、结果、公司、项目名、链接；只能保留原文已有的量化数字并优化表述；缺量化处不得补数字，用更具体的行为描述替代；
3. 每条要点以行为动词开头，突出职责、技术难点、行动与结果；
4. 提供「目标 JD」时，只把 JD 中与原文已有事实吻合的关键词/业务场景自然融入；不得引入原文不存在的能力；
5. 保持原文 Markdown 列表风格（- 开头）与原文语言；技术名词保留原文英文拼写；
6. 自查：optimized 中所有技术名词与数字都能在原文中找到；未新增任何事实；长度在上限内。

只输出 JSON，无 markdown fence，无解释文字。"""

# 运行时版本标记（2026-08-25 新增）。调用点为 chat_json（无 schema），
# 版本常量服务于日志/指标追溯（polish 仍走 chat_json，调用点不动）。
POLISH_PROMPT_VERSION = "v2"


def _module_basics(module: dict) -> dict:
    return {
        "module": module.get("module", ""),
        "index": int(module.get("index", 0)),
        "title": module.get("title", ""),
        "original": module.get("original", ""),
    }


def module_failure_detail(exc: BaseException, module_label: str) -> str:
    """Return a readable, user-facing reason when ONE module fails to polish."""
    message = str(exc) or exc.__class__.__name__
    if isinstance(exc, LLMResponseError):
        # R4 P0-1：结构化 code 优先分支（与 _job_failure_detail 同口径）；
        # code == "other" 回退文本分类（兼容无 code 构造的老调用方）。
        code = getattr(exc, "code", "other")
        if code != "other":
            if code == "quota":
                reason = "模型账户欠费或余额不足，请充值后重试"
            elif code == "auth":
                reason = "API Key 无效或缺失，请检查模型设置"
            elif code == "rate_limit":
                reason = "模型服务限流，请稍后重试"
            elif code == "timeout":
                reason = "模型响应超时，可尝试更换更快的模型或稍后重试"
            elif code == "empty":
                reason = "模型返回为空，请重试"
            elif code in ("parse", "schema"):
                reason = "模型返回内容格式异常，请重试或更换模型"
            else:
                reason = "模型服务暂时不可用，请稍后重试"
        else:
            lowered = message.lower()
            if "402" in message or "payment" in lowered or "insufficient" in lowered or "余额" in message:
                reason = "模型账户欠费或余额不足，请充值后重试"
            elif (
                "401" in message
                or "403" in message
                or "invalid api key" in lowered
                or "api key" in lowered
                or "unauthorized" in lowered
                or "authentication" in lowered
            ):
                # P0-1: 仅 auth 类失败提示查 API Key；"invalid" 若继续保留会误吞
                # "invalid json" 之类的结构解析失败。
                reason = "API Key 无效或缺失，请检查模型设置"
            elif "429" in message or "rate limit" in lowered:
                reason = "模型服务限流，请稍后重试"
            elif "timeout" in lowered or "timed out" in lowered or "time-out" in lowered:
                reason = "模型响应超时，可尝试更换更快的模型或稍后重试"
            elif (
                "empty" in lowered
                or "returned nothing" in lowered
            ):
                reason = "模型返回为空，请重试"
            elif (
                "schema" in lowered
                or "failed validation" in lowered
                or "expecting value" in lowered
                or "no json" in lowered
                or "not a json object" in lowered
            ):
                reason = "模型返回内容格式异常，请重试或更换模型"
            else:
                reason = "模型服务暂时不可用，请稍后重试"
    else:
        reason = (message or "内部错误")[:200]
    return f"「{module_label or '该条目'}」润色失败：{reason}"


def polish_project_module(
    client: LLMClient,
    module: dict,
    jd_context: str = "",
    *,
    timeout: float | None = None,
) -> dict:
    """Run one LLM polish pass over a single experience module.

    Raises on failure (callers isolate per module); on success returns the
    module dict plus ``optimized`` / ``rationale`` / ``status: "ok"``.
    """
    original = (module.get("original") or "").strip()
    if len(original) < 10:
        raise LLMResponseError("content too short to polish")
    user = (
        "目标 JD（可为空）：\n"
        f"{truncate_text(jd_context or '', 4000)}\n\n"
        "原始项目经历条目：\n"
        f"{original}"
    )
    data = client.chat_json(POLISH_PROMPT, user)
    optimized = (data.get("optimized") or "").strip()
    if not optimized:
        raise LLMResponseError("empty response")
    return {
        **_module_basics(module),
        "status": "ok",
        "optimized": optimized,
        "rationale": (data.get("rationale") or "").strip(),
        "error": None,
    }


# Keep the timeout helper importable where the job runner builds the client.
def polish_timeout() -> float:
    return _role_timeout("editor")


__all__ = [
    "POLISH_PROMPT",
    "build_overview",
    "extract_project_modules",
    "module_failure_detail",
    "polish_project_module",
    "polish_timeout",
]