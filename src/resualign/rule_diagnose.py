"""Deterministic, local rule-based resume diagnosis.

This replaces the LLM "diagnose" stage in the alignment pipeline (取舍一
方案 A): pure Python checks for contact info (phone/email), experience-section
length, garbled text / abnormal line breaks, quantification hints, plus a
lightweight tech-stack keyword scan.

It runs in ~1ms instead of a 15-45s LLM call and can never fail on provider
timeouts (there is no provider). The output shape matches the LLM
``AnalysisSchema``: ``score`` / ``skills`` / ``issues``, plus
``fallback_used`` so callers can tell the result was not LLM-generated.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Contact info
# ---------------------------------------------------------------------------
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d[- ]?\d{4}[- ]?\d{4}(?!\d)"
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# ---------------------------------------------------------------------------
# Garbled text / abnormal line breaks
# ---------------------------------------------------------------------------
# U+FFFD replacement char, the classic "锟斤拷" mojibake, UTF-8 read as
# Latin-1/Windows-1252, and stray control characters.
_GARBLED_RE = re.compile(
    r"[\ufffd]"
    r"|锟斤拷"
    r"|Ã[©¨±´¸â]"
    r"|â€[œ¾‚™\"']"
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f]"
)


def _abnormal_line_breaks(text: str) -> bool:
    """True for excessive blank runs or a majority of very short lines."""
    if re.search(r"\n{4,}", text):
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 5:
        short = sum(1 for ln in lines if len(ln) < 8)
        if short / len(lines) > 0.4:
            return True
    return False

# ---------------------------------------------------------------------------
# Experience sections + quantification
# ---------------------------------------------------------------------------
_SECTION_HEADERS_RE = re.compile(
    r"(?m)^\s*(项目经历|项目经验|工作经历|实习经历|工作经验)\s*[:：]?\s*$"
)
_QUANT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|万|亿|倍|人|单|次|个|QPS|TPS|RPS|并发|ms|MB|GB|TB)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Lightweight tech-stack extraction
# ---------------------------------------------------------------------------
_SKILL_KEYWORDS: tuple[str, ...] = (
    "Elasticsearch", "TensorFlow", "TypeScript", "JavaScript", "Spring Boot",
    "PostgreSQL", "RabbitMQ", "Kubernetes", "MongoDB", "Spark", "Flink",
    "Python", "React", "Angular", "Django", "Flask", "FastAPI", "MySQL",
    "Redis", "Docker", "Kafka", "Hadoop", "PyTorch", "GraphQL", "Golang",
    "Node.js", "Windows", "Linux", "NoSQL", "微服务", "分布式", "消息队列",
    "数据分析", "机器学习", "深度学习", "高并发", "低延迟", "Java", "Vue",
    "Go", "C++", "C#", "SQL", "Git", "AWS", "GCP", "Azure", "CI/CD", "REST",
)
_MAX_SKILLS = 12


def _keyword_pattern(keyword: str) -> re.Pattern:
    """Build a boundary-aware pattern for a skill keyword.

    Alphanumeric edges get word boundaries so "Java" does not match inside
    "JavaScript"; Chinese keywords match as plain substrings.
    """
    esc = re.escape(keyword)
    if keyword[0].isalnum():
        esc = rf"(?<![A-Za-z0-9]){esc}"
    if keyword[-1].isalnum():
        esc = rf"{esc}(?![A-Za-z0-9])"
    flags = re.IGNORECASE if keyword.isascii() else 0
    return re.compile(esc, flags)


_KEYWORD_PATTERNS: dict[str, re.Pattern] = {
    kw: _keyword_pattern(kw) for kw in _SKILL_KEYWORDS
}


def _extract_skills(text: str, max_skills: int = _MAX_SKILLS) -> list[str]:
    """Return matched tech keywords, longest-first so shorter aliases that are
    substrings of an already matched keyword are skipped."""
    found: list[str] = []
    for kw in sorted(_SKILL_KEYWORDS, key=len, reverse=True):
        if len(found) >= max_skills:
            break
        if any(kw.lower() in matched.lower() for matched in found):
            continue
        if _KEYWORD_PATTERNS[kw].search(text):
            found.append(kw)
    return found

# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _score_from_issues(issues: list[str]) -> int:
    score = 75
    for issue in issues:
        if "乱码" in issue or "编码" in issue:
            score -= 20
        elif "手机号" in issue or "邮箱" in issue:
            score -= 10
        elif "简短" in issue or "篇幅过短" in issue:
            score -= 10
        elif "量化" in issue:
            score -= 5
        elif "技能关键词" in issue:
            score -= 5
    return max(0, min(100, score))


def diagnose_resume_local(resume_text: str, *, max_skills: int = _MAX_SKILLS) -> dict:
    """Run local rule-based diagnosis; returns an ``Analysis``-shaped dict."""
    text = (resume_text or "").strip()
    if not text:
        return {
            "score": 0,
            "skills": [],
            "issues": ["简历内容为空，请先粘贴简历正文"],
            "fallback_used": True,
        }

    issues: list[str] = []

    # --- contact info ---
    if not _PHONE_RE.search(text):
        issues.append("未检测到手机号，建议在简历顶部补充手机号联系方式")
    if not _EMAIL_RE.search(text):
        issues.append("未检测到邮箱，建议在简历顶部补充邮箱联系方式")

    # --- garbled text / abnormal line breaks ---
    if _GARBLED_RE.search(text):
        issues.append("检测到乱码或异常编码，请检查文件编码（推荐 UTF-8）与导出方式")
    elif _abnormal_line_breaks(text):
        issues.append("检测到异常换行或排版格式问题，请重新排版为规范段落")

    # --- overall / per-section length ---
    if len(text) < 150:
        issues.append("简历内容过于简短，建议补充教育背景、项目经历与技能项")
    else:
        matches = list(_SECTION_HEADERS_RE.finditer(text))
        for idx, m in enumerate(matches):
            next_start = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            content = text[m.end():next_start].strip()
            if content and len(content) < 30:
                issues.append(f"“{m.group(1)}”篇幅过短，建议补充职责、技术栈与量化结果")

    # --- quantification ---
    if (_SECTION_HEADERS_RE.search(text) or len(text) >= 300) and not _QUANT_RE.search(text):
        issues.append("经历缺少量化数据，建议补充吞吐量、耗时、覆盖率或营收等具体成果指标")

    # --- skills ---
    skills = _extract_skills(text, max_skills=max_skills)
    if len(text) >= 300 and len(skills) < 2:
        issues.append("技能关键词较少，建议明确列出技术栈（如 Python、Redis、Kubernetes）")

    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique_issues: list[str] = []
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            unique_issues.append(issue)
    issues = unique_issues

    return {
        "score": _score_from_issues(issues),
        "skills": skills,
        "issues": issues,
        "fallback_used": True,
    }