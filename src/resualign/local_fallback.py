"""Deterministic, network-free resume heuristics (Phase 5 fallback).

Pure-Python rule/regex analysis that mirrors the LLM-backed diagnosis surface
without any external dependency, network access, or side effects on import.
"""

import re

SKILL_KEYWORDS = [
    "python",
    "java",
    "golang",
    "go",
    "fastapi",
    "docker",
    "redis",
    "sql",
    "mysql",
    "postgres",
    "mongodb",
    "kubernetes",
    "k8s",
    "aws",
    "gcp",
    "git",
    "react",
    "javascript",
    "typescript",
    "tensorflow",
    "pytorch",
    "kafka",
]

HEADINGS_RE = re.compile(
    r"(?i)(education|work experience|work history|experience|projects?|"
    r"skills|summary|objective|contact|technologies)\b|"
    r"(教育背景|教育|工作经历|工作履历|项目经历|项目经验|专业技能|技能|"
    r"个人简介|联系方式|自我评价)"
)

QUANTIFIED_RE = re.compile(
    r"(?i)(\d+(\.\d+)?\s*(%|percent|years?|yrs|users?|clients?|"
    r"requests?|qps|tps|gb|mb|tb|ms|seconds?|downtime|improvement))"
)

MIN_RESUME_LENGTH = 120


def _as_text(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        return str(value)
    return value


def _skill_pattern(skill: str) -> re.Pattern:
    esc = re.escape(skill.lower())
    return re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])")


def _extract_skills(text: str) -> list[str]:
    lowered = text.lower()
    found: list[str] = []
    for skill in SKILL_KEYWORDS:
        if _skill_pattern(skill).search(lowered):
            found.append(skill)
    return found


def _has_quantified_metrics(text: str) -> bool:
    return bool(QUANTIFIED_RE.search(text))


def _matches_skill(text: str, skill: str) -> bool:
    """Word-boundary, case-insensitive match shared by all rule paths."""
    return bool(_skill_pattern(skill).search(_as_text(text).lower()))


def local_diagnose(resume_text) -> dict:
    """Score a resume with simple heuristics and list actionable issues."""
    text = _as_text(resume_text)
    skills = _extract_skills(text)
    has_headings = bool(HEADINGS_RE.search(text))
    has_metrics = _has_quantified_metrics(text)

    score = 60
    if has_headings:
        score += 10
    if skills:
        score += 15
    if has_metrics:
        score += 15
    score = max(0, min(100, score))

    issues: list[str] = []
    if not text.strip():
        issues.append("Resume is empty.")
    if not has_metrics:
        issues.append("No quantified metrics detected.")
    if not skills:
        issues.append("No recognizable skills section found.")
    if len(text.strip()) < MIN_RESUME_LENGTH:
        issues.append("Resume is too short.")

    return {"score": score, "skills": skills, "issues": issues}


def local_gap_report(resume_text, jd_text) -> dict:
    """Compare JD keywords against the resume and report gaps."""
    resume = _as_text(resume_text)
    jd = _as_text(jd_text)
    jd_keywords = _extract_skills(jd)

    strength_matches: list[str] = []
    missing_keywords: list[str] = []
    for keyword in jd_keywords:
        if _skill_pattern(keyword).search(resume.lower()):
            strength_matches.append(keyword)
        else:
            missing_keywords.append(keyword)

    return {
        "missing_keywords": missing_keywords,
        "misaligned_emphasis": [],
        "strength_matches": strength_matches,
    }


def local_ats_score(resume_text, jd_profile) -> dict:
    """Rank resume keyword coverage against a structured JD profile."""
    resume = _as_text(resume_text)
    profile = jd_profile if isinstance(jd_profile, dict) else {}

    required: list[str] = []
    for key in ("required_skills", "must_have_skills", "skills", "required"):
        value = profile.get(key)
        if isinstance(value, list):
            required.extend(str(item).strip() for item in value if str(item).strip())

    total = len(required)
    if total == 0:
        return {"score": 1.0, "details": ["No required skills specified."]}

    matched = [skill for skill in required if _matches_skill(resume, skill)]
    score = len(matched) / total
    details = [
        f"Matched: {skill}" if skill in matched else f"Missing: {skill}"
        for skill in required
    ]
    return {"score": round(score, 3), "details": details}


_PHONE_RE = re.compile(r"(?:\+?86[-\s]?)?1[3-9]\d[-\s]?\d{4}[-\s]?\d{4}")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LOCATION_RE = re.compile(r"(?:坐标|城市|所在地|base[:：\s]*)\s*([\u4e00-\u9fa5]{2,8})")


def enrich_profile_from_text(content: str, profile: dict) -> dict:
    """Rule-based backstop for the structured profile extraction.

    LLM 抽取漏掉联系方式等高置信字段时（缺陷 #2：basic 全空），从简历
    原文用正则兜底填充 basic 的空位。规则只填 LLM 未抽到的字段
    （LLM 值优先，规则不覆盖），且绝不触碰非空字符串以外的判断。
    """
    text = content or ""
    basic = profile.setdefault("basic", {})
    if not basic.get("phone"):
        m = _PHONE_RE.search(text)
        if m:
            basic["phone"] = m.group(0)
    if not basic.get("email"):
        m = _EMAIL_RE.search(text)
        if m:
            basic["email"] = m.group(0)
    if not basic.get("location"):
        m = _LOCATION_RE.search(text)
        if m:
            basic["location"] = m.group(1)
    return profile
