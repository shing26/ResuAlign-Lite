from .llm import LLMClient, _structured_or_json
from .models import JDProfile
from .schema_registry import JDProfileSchema

# PROMPT_VERSION bump: jd_profiler/v1 -> v2（2026-08-25，对照 04b-PE §2.2）
# 本次升级说明：
# - 变更点 1：business_scenarios 由「逐字全量、一个都不能少」改为 0-6 项封顶
#   （每项 ≤ 30 字符），直接砍输出 token（166s 链路核心一刀）
# - 变更点 2：各列表数量与单项长度封顶（must 5-12 / nice 0-8 / soft 0-5 / edu 0-3）
# - 变更点 3：删除假指令 Max tokens/Temperature 与 error 分支（空输入由调用层拦截）
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效（cache.py 以 prompt_version 为键）；
#   若只改文本不 bump，新旧提示词结果互串缓存（B3 类事故）。
JD_PROFILER_PROMPT_VERSION = "v2"

# Fields the current JDProfile model accepts. Cached payloads are filtered
# against this whitelist on read so legacy/extra keys never reach the
# dataclass constructor (B3 hardening).
_JD_PROFILE_FIELDS = (
    "must_have_skills",
    "nice_to_have_skills",
    "soft_skills",
    "business_scenarios",
    "min_years_experience",
    "education_requirements",
)


JD_PROFILER_PROMPT = """PROMPT_VERSION: jd_profiler/v2

你是岗位画像分析师。从岗位描述（JD）中抽取结构化画像。

## Output Contract（只能输出一个 JSON 对象，6 个字段，不得增减字段）
键名固定为：must_have_skills / nice_to_have_skills / soft_skills / business_scenarios / min_years_experience / education_requirements

- must_have_skills：硬性技术/平台技能，5-12 项，每项 ≤ 24 字符。JD 提到交付平台技能（Docker、Kubernetes、CI/CD）或性能/可观测性要求（metrics、latency、tracing）时必须包含。
- nice_to_have_skills：加分技能，0-8 项，每项 ≤ 24 字符。
- soft_skills：软技能，0-5 项，每项 ≤ 12 字符。
- business_scenarios：业务/平台场景短语，0-6 项，每项 ≤ 30 字符。逐字摘录原文（如 high concurrency、millions of requests per day、low latency、observability），不改写、不翻译；先按出现顺序摘录，超过 6 个时保留对简历改写最有区分度（与具体技能配对）的 6 个。
- min_years_experience：要求的整数年数；JD 未提及给 null。
- education_requirements：学历/专业要求，0-3 项，每项 ≤ 20 字符。

## 规则
1. 每项技能/场景必须能在 JD 原文中找到依据，不得脑补；
2. 技术名词保留原文英文拼写（Docker、Kubernetes、CI/CD）；
3. 输入为空时该任务应在调用层直接拦截；若文本为空，输出 {"must_have_skills": [], "nice_to_have_skills": [], "soft_skills": [], "business_scenarios": [], "min_years_experience": null, "education_requirements": []}，不要输出 error 对象。

## 提交前自查
- 6 个字段齐全、类型正确；每项数量与单项长度在上限内；业务场景均为原文逐字节写；
- 只输出一个 JSON 对象，无 markdown fence，无解释文字。"""


def profile_jd(
    client: LLMClient,
    jd_text: str,
    cache=None,
    tenant: str = "default",
    model=None,
) -> JDProfile:
    """Extract a structured profile from a raw job description."""
    # AIE M4 确认必须落地：空输入在调用层直接拦截，返回空画像而非抛错
    # （下游 gap/tailor 对空列表有默认容错，不会炸链路）。
    if not (jd_text or "").strip():
        return JDProfile(
            must_have_skills=[],
            nice_to_have_skills=[],
            soft_skills=[],
            business_scenarios=[],
            min_years_experience=None,
            education_requirements=[],
        )
    resolved_model = model or getattr(client, "model", "default")
    if cache is not None:
        cached = cache.get(
            tenant,
            resolved_model,
            JD_PROFILER_PROMPT_VERSION,
            jd_text,
        )
        if cached is not None:
            return JDProfile(
                **{
                    key: cached[key]
                    for key in _JD_PROFILE_FIELDS
                    if key in cached
                }
            )

    result = _structured_or_json(
        client,
        JD_PROFILER_PROMPT,
        jd_text,
        JDProfileSchema,
        model=resolved_model,
    )
    profile = JDProfile(
        must_have_skills=result.get("must_have_skills", []),
        nice_to_have_skills=result.get("nice_to_have_skills", []),
        soft_skills=result.get("soft_skills", []),
        business_scenarios=result.get("business_scenarios", []),
        min_years_experience=result.get("min_years_experience"),
        education_requirements=result.get("education_requirements", []),
    )
    if cache is not None:
        cache.put(
            tenant,
            resolved_model,
            JD_PROFILER_PROMPT_VERSION,
            jd_text,
            profile.__dict__,
        )
    return profile
