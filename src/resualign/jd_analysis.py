"""Combined JD profile and gap analysis in a single LLM round trip."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .jd_profiler import profile_jd
from .llm import LLMClient
from .models import GapReport, JDProfile

# Cache schema version for the combined JD profile + gap analysis. Bumped to
# v2 because v1 entries were written with legacy alias keys
# (``required_skills``/``nice_to_have``/``business_scene``) that break
# ``JDProfile(**cached)``; reads under the new version never touch v1 rows
# (B3).
# PROMPT_VERSION bump: jd-analysis-v2 -> jd-analysis-v3（2026-08-25，对照 04b-PE §2.4）
# 本次升级说明：
# - 变更点 1：组合契约重写为纯静态文本（不再 f-string 拼插两份子提示词），
#   jd_profile 各字段与 gap_report 各字段均带数量/长度上限
# - 变更点 2：删除假指令 Max tokens；补充「只输出两个顶层字段」约束
# - 说明：profile_and_gaps 为死代码路径（M3，无生产调用方），仍保留最小维护
# - 缓存影响：版本常量随文本变更 bump（api/routers/jobs.py:475-482 预分析缓存键
#   直接引用本常量，漏 bump 会新旧结果串扰）。
JD_ANALYSIS_PROMPT_VERSION = "jd-analysis-v3"

# Fields the current JDProfile model accepts. Cache payloads are filtered
# against this whitelist on read so extra keys are ignored instead of
# crashing the constructor.
_JD_PROFILE_FIELDS = (
    "must_have_skills",
    "nice_to_have_skills",
    "soft_skills",
    "business_scenarios",
    "min_years_experience",
    "education_requirements",
)

JD_ANALYSIS_PROMPT = """PROMPT_VERSION: jd_analysis/v3

你是岗位画像与差距分析师。输入：主简历 + 岗位描述。输出一个 JSON 对象，包含且仅包含两个顶层字段：jd_profile 与 gap_report。两个子对象都必须完整给出。

## Output Contract
{"jd_profile": {...}, "gap_report": {...}}

### jd_profile（6 个字段，键名固定）
- must_have_skills：硬性技术/平台技能，5-12 项，每项 ≤ 24 字符；JD 提到交付平台技能（Docker、Kubernetes、CI/CD）或性能/可观测性要求（metrics、latency、tracing）时必须包含。
- nice_to_have_skills：加分技能，0-8 项，每项 ≤ 24 字符。
- soft_skills：软技能，0-5 项，每项 ≤ 12 字符。
- business_scenarios：业务/平台场景短语，0-6 项，每项 ≤ 30 字符；逐字摘录原文（如 high concurrency、millions of requests per day、low latency、observability），去重；超过 6 个时保留与具体技能配对、最有改写价值的 6 个。
- min_years_experience：整数年数；未提及给 null。
- education_requirements：学历/专业要求，0-3 项，每项 ≤ 20 字符。

### gap_report（3 个字段，键名固定）
- missing_keywords：JD 要求但简历未体现的关键词或紧凑配对短语（如 "Redis caching for high concurrency"），5-12 项，每项 ≤ 30 字符；语义重复合并，不堆砌。
- misaligned_emphasis：简历有但强调方向与 JD 不符的点，0-4 项，每项 ≤ 30 字符；没有给 []。
- strength_matches：简历已满足的 JD 要求，2-8 项，每项 ≤ 30 字符。

## 通用规则
1. 所有内容必须能在输入原文中找到依据；技术名词保留原文英文拼写；
2. 值用简历同语言（中文简历 → 中文输出）；
3. 自查：两个子对象字段齐全、类型正确；各列表数量与单项长度不超上限；无多余字段；
4. 只输出一个 JSON 对象，无 markdown fence，无解释文字。"""


def jd_profile_to_dict(profile: JDProfile) -> dict:
    """Serialize a JDProfile with the public alias contract."""
    data = asdict(profile)
    data["required_skills"] = profile.required_skills
    data["nice_to_have"] = profile.nice_to_have
    data["business_scene"] = profile.business_scene
    return data


def proactive_jd_profile(
    client: LLMClient,
    jd_text: str,
    cache=None,
    tenant: str = "default",
    model: str | None = None,
) -> JDProfile:
    """Profile a raw JD reusing ``profile_jd`` and the shared content cache."""
    return profile_jd(
        client,
        jd_text,
        cache=cache,
        tenant=tenant,
        model=model,
    )


def _jd_profile_from_cache(raw: dict[str, Any] | None) -> JDProfile | None:
    """Build a JDProfile from a cached payload, ignoring unknown fields."""
    if not isinstance(raw, dict):
        return None
    return JDProfile(
        **{key: raw.get(key) for key in _JD_PROFILE_FIELDS if key in raw}
    )


def _gap_report_from_cache(raw: dict[str, Any] | None) -> GapReport | None:
    """Build a GapReport from a cached payload, ignoring unknown fields."""
    if not isinstance(raw, dict):
        return None
    return GapReport(
        missing_keywords=raw.get("missing_keywords", []),
        misaligned_emphasis=raw.get("misaligned_emphasis", []),
        strength_matches=raw.get("strength_matches", []),
    )


def profile_and_gaps(
    client: LLMClient,
    resume_text: str,
    jd_text: str,
    cache=None,
    tenant: str = "default",
) -> tuple[JDProfile, GapReport]:
    """Extract a JDProfile and GapReport from one chat completion."""
    resolved_model = getattr(client, "model", "default")
    prompt_version = JD_ANALYSIS_PROMPT_VERSION
    content = f"{resume_text}\n\n{jd_text}"
    if cache is not None:
        cached = cache.get(tenant, resolved_model, prompt_version, content)
        if cached is not None:
            profile = _jd_profile_from_cache(cached.get("jd_profile"))
            gap = _gap_report_from_cache(cached.get("gap_report"))
            if profile is not None and gap is not None:
                return profile, gap

    user = f"Resume:\n{resume_text}\n\nJob Description:\n{jd_text}"
    from .llm import _structured_or_json
    from .schema_registry import JDAnalysisSchema

    result = _structured_or_json(
        client,
        JD_ANALYSIS_PROMPT,
        user,
        JDAnalysisSchema,
    )
    profile_raw = result.get("jd_profile") or result
    gap_raw = result.get("gap_report") or {}
    profile = JDProfile(
        must_have_skills=profile_raw.get("must_have_skills", []),
        nice_to_have_skills=profile_raw.get("nice_to_have_skills", []),
        soft_skills=profile_raw.get("soft_skills", []),
        business_scenarios=profile_raw.get("business_scenarios", []),
        min_years_experience=profile_raw.get("min_years_experience"),
        education_requirements=profile_raw.get("education_requirements", []),
    )
    gap = GapReport(
        missing_keywords=gap_raw.get("missing_keywords", []),
        misaligned_emphasis=gap_raw.get("misaligned_emphasis", []),
        strength_matches=gap_raw.get("strength_matches", []),
    )
    if cache is not None:
        cache.put(
            tenant,
            resolved_model,
            prompt_version,
            content,
            {
                "jd_profile": jd_profile_to_dict(profile),
                "gap_report": {
                    "missing_keywords": gap.missing_keywords,
                    "misaligned_emphasis": gap.misaligned_emphasis,
                    "strength_matches": gap.strength_matches,
                },
            },
        )
    return profile, gap