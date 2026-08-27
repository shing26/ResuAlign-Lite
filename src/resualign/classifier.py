"""LLM job classification with controlled vocabulary normalization."""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

from .job_library import JOB_FUNCTIONS, SENIORITIES
from .llm import _structured_or_json
from .schema_registry import ClassifierResultSchema

_CLASSIFIER_SYSTEM_PROMPT = """PROMPT_VERSION: classifier/v2

你是岗位分类器。输入：岗位描述 + 受控词表（Job functions 列表、Seniorities 列表）。输出分类 JSON。

## Output Contract（只能输出一个 JSON 对象，3 个字段）
键名固定为：job_function / seniority / tech_tags

- job_function：必须逐字取自输入中提供的 Job functions 列表（含中文原词），不得自造、不得翻译、不得部分匹配。
- seniority：必须逐字取自输入中提供的 Seniorities 列表，不得自造。
- tech_tags：JD 明确提到的技术/领域标签，3-10 项，每项 ≤ 20 字符；技术名词保留原文英文拼写（如 Python、Docker、Kubernetes）。

## 规则
1. 两个列表都出现在输入文本中；若 job_function 无任何匹配，选 "其他"（列表中存在时）；seniority 无法判断时选 "未知"（列表中存在时）；
2. 自查：job_function / seniority 与列表中某项逐字相同；未列出词不放入；tech_tags 数量与长度在上限内；
3. 只输出 JSON，无 markdown fence，无解释文字。"""

# 运行时版本标记（2026-08-25 新增）。缓存键仍用 sha256(prompt+词表)，
# 词表变化自动失效；本常量服务于指标/日志追溯。
CLASSIFIER_PROMPT_VERSION = "v2"


def normalize_enum(
    value: str | None,
    choices: Sequence[str],
    default: str,
) -> str:
    """Match a raw value to a controlled choice by substring, else default."""
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    for choice in choices:
        if choice.lower() in normalized:
            return choice
    return default


def classify_job(
    client: Any,
    jd_text: str,
    job_functions: Sequence[str] | None = None,
    seniorities: Sequence[str] | None = None,
    *,
    cache=None,
    tenant: str = "default",
    model: str | None = None,
) -> dict[str, Any]:
    """Classify a JD into function, seniority, and tech/domain tags."""
    functions = list(job_functions or JOB_FUNCTIONS)
    levels = list(seniorities or SENIORITIES)
    prompt_version = hashlib.sha256(
        (
            _CLASSIFIER_SYSTEM_PROMPT
            + "|"
            + ",".join(functions)
            + "|"
            + ",".join(levels)
        ).encode("utf-8")
    ).hexdigest()
    resolved_model = model or getattr(client, "model", "default")
    if cache is not None:
        cached = cache.get(tenant, resolved_model, prompt_version, jd_text)
        if cached is not None:
            return cached

    function_default = "其他" if "其他" in functions else (
        functions[0] if functions else "其他"
    )
    seniority_default = "未知" if "未知" in levels else (
        levels[0] if levels else "未知"
    )
    user_prompt = (
        "Job description:\n"
        f"{jd_text}\n\n"
        f"Job functions: {', '.join(functions)}\n"
        f"Seniorities: {', '.join(levels)}\n"
        'Respond as JSON: {"job_function": "...", "seniority": "...", '
        '"tech_tags": ["..."]}'
    )
    raw = _structured_or_json(
        client,
        _CLASSIFIER_SYSTEM_PROMPT,
        user_prompt,
        ClassifierResultSchema,
        model=resolved_model,
    )
    raw_tags = raw.get("tech_tags") or []
    tags = [
        str(tag).strip()
        for tag in raw_tags
        if str(tag).strip()
    ]
    result = {
        "job_function": normalize_enum(
            raw.get("job_function"), functions, function_default
        ),
        "seniority": normalize_enum(
            raw.get("seniority"), levels, seniority_default
        ),
        "tech_tags": tags,
    }
    if cache is not None:
        cache.put(tenant, resolved_model, prompt_version, jd_text, result)
    return result
