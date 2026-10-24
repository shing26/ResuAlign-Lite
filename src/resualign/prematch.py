"""Deterministic pre-match lexical signals (ADR-0064).

Pure-stdlib lexical matching between a resume and a JD: a curated skill
alias dictionary plus word-boundary term detection and hit ratio. The
signals have exactly two sanctioned consumers:

1. ``jd_context_summary(..., prematch=...)`` — one editor-prompt context
   line built ONLY from resume-backed terms (resume ∩ JD). JD-only terms
   and gap-report ``missing_keywords`` must never reach the prompt
   (ADR-0061).
2. Future UI explainability (match badges) — interface reserved, not yet
   implemented.

Signals must never enter allowlist/content validation; ``gate.py`` stays
untouched (vendor lock, ADR-0041 decision 11).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

# variant -> canonical skill name. Curation rule: precision over recall —
# only unambiguous tokens; "go" (stopword-prone) and single letters stay out.
SKILL_ALIASES: Dict[str, str] = {
    "k8s": "kubernetes",
    "js": "javascript",
    "ts": "typescript",
    "postgres": "postgresql",
    "py": "python",
    "springboot": "spring boot",
    "ml": "machine learning",
    "nodejs": "node.js",
}

# Canonical skill vocabulary detected directly (word-boundary, multi-word
# aware via flexible whitespace).
CANONICAL_SKILLS: List[str] = [
    "java",
    "python",
    "spring boot",
    "kubernetes",
    "kafka",
    "spark",
    "airflow",
    "docker",
    "mysql",
    "postgresql",
    "redis",
    "react",
    "typescript",
    "javascript",
    "fastapi",
    "graphql",
    "machine learning",
    "deep learning",
    "etl",
    "microservices",
    "rust",
    "terraform",
    "aws",
    "ci/cd",
    "node.js",
]


def _term_pattern(term: str) -> "re.Pattern[str]":
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return re.compile(r"\b" + escaped + r"\b", re.IGNORECASE)


# canonical -> alias-or-canonical patterns, compiled once
_PATTERNS: Dict[str, List["re.Pattern[str]"]] = {}
for _canonical in CANONICAL_SKILLS:
    _PATTERNS[_canonical] = [_term_pattern(_canonical)]
for _alias, _canonical in SKILL_ALIASES.items():
    _PATTERNS.setdefault(_canonical, []).append(_term_pattern(_alias))


def prematch_enabled() -> bool:
    """Kill switch: RESUALIGN_PREMATCH=0 (or false/no/off) disables signals."""
    return os.environ.get("RESUALIGN_PREMATCH", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def compute_match_signals(resume_text: str, jd_text: str) -> Dict[str, object]:
    """Compute deterministic resume↔JD lexical signals.

    ``matched_skills`` are terms found in BOTH texts — i.e. resume-backed —
    and are the only terms allowed to reach an editor prompt. JD-only terms
    are counted (``jd_skill_total``) but never returned as strings, so the
    ADR-0061 boundary cannot be crossed by accident.
    """
    jd = jd_text or ""
    resume = resume_text or ""
    jd_skills = sorted(
        canonical
        for canonical, patterns in _PATTERNS.items()
        if any(pattern.search(jd) for pattern in patterns)
    )
    matched = sorted(
        canonical
        for canonical in jd_skills
        if any(pattern.search(resume) for pattern in _PATTERNS[canonical])
    )
    # 可观测性（审阅意见 1）：词表盲区（JD 没有任何词表内技能）与真实
    # 零重叠分开计数——前者直接反映词表扩充的紧迫性。只记计数，
    # 不落任何简历/JD 原文（隐私边界与 ADR-0064 一致）。
    if not jd_skills:
        logger.info(
            "prematch vocab blind spot: JD matched 0 vocabulary skills "
            "(resume_tokens=%d, jd_chars=%d)",
            len(resume.split()),
            len(jd),
        )
    elif not matched:
        logger.debug(
            "prematch: no overlap (jd_skills=%d) — genuine gap, not vocab issue",
            len(jd_skills),
        )
    return {
        "matched_skills": matched,
        "jd_skill_total": len(jd_skills),
        "overlap_ratio": (
            round(len(matched) / len(jd_skills), 3) if jd_skills else 0.0
        ),
    }


def signal_line(signals: Dict[str, object] | None, max_skills: int = 3) -> str:
    """Render the one-line prompt context; resume-backed terms only.

    ``max_skills`` caps the displayed list so the signal line can never eat
    the 300-char context budget (review round 2); unshown skills are
    summarised as "等 n 项" while the hit count stays the true value.

    分母口径（审阅第三轮）：``total`` 是**词表内识别出的 JD 技能数**，
    不是 JD 要求总数——「（7/9）」不得被解读为匹配覆盖率。当前该行只进
    LLM prompt 不对用户可见；UI 徽章落地时必须自带用户可见措辞
    （如「词表内技能 7/9」）并注明口径，见 ADR-0064 附录。
    """
    if not signals:
        return ""
    matched = list(signals.get("matched_skills") or [])
    if not matched:
        return ""
    shown = "、".join(str(skill) for skill in matched[:max_skills])
    total = signals.get("jd_skill_total", 0)
    extra = len(matched) - min(len(matched), max_skills)
    suffix = f"，等 {extra} 项" if extra > 0 else ""
    return f"匹配信号：命中核心技能 {shown}（{len(matched)}/{total}{suffix}）"
