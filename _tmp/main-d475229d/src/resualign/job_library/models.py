"""Controlled vocabularies and shared constants for the job library."""

from __future__ import annotations

from typing import Sequence

JOB_FUNCTIONS = (
    "后端",
    "前端",
    "算法",
    "数据",
    "测试",
    "运维",
    "产品",
    "设计",
    "运营",
    "销售",
    "其他",
)

SENIORITIES = (
    "初级",
    "中级",
    "高级",
    "资深",
    "未知",
)

JOB_STATUSES = (
    "未投递",
    "已投递",
    "面试中",
    "已拿Offer",
    "放弃",
)

JOB_STATUSES_CANONICAL = ("draft", "applied", "interview", "offer", "withdrawn")

_JOB_STATUS_ALIASES = {
    "未投递": "draft",
    "已投递": "applied",
    "面试中": "interview",
    "已拿Offer": "offer",
    "放弃": "withdrawn",
}

_STATUS_LABELS = {
    canonical: legacy for legacy, canonical in _JOB_STATUS_ALIASES.items()
}

RULE_TYPES = ("blacklist", "city_whitelist", "min_salary")

BLOCKER_CATEGORIES = (
    "captcha",
    "login_required",
    "no_content",
    "parse_error",
    "fetch_error",
    "rule_rejected",
    "timeout",
    "network_error",
    "site_error",
    "invalid_url",
)

BLOCKER_STATUSES = ("pending", "resolved", "ignored")

TAILOR_GRANULARITIES = ("fine", "medium", "coarse")
TAILOR_FOCUSES = ("balanced", "quantified", "skills")


def _effective_choices(
    base: Sequence[str],
    extra: Sequence[str] | None,
) -> list[str]:
    """Merge tenant vocabulary into the built-in controlled choices."""
    choices = list(base)
    for choice in extra or []:
        choice = str(choice).strip()
        if choice and choice not in choices:
            choices.append(choice)
    return choices
