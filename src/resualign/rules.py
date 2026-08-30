"""Zero-LLM rule-based job filtering for the fetch pipeline (Sprint 3).

The engine is intentionally pure rule matching: it never calls an LLM. It
reads enabled ``automation_rules`` from the tenant's job library store and
evaluates a small job metadata dict (``title``/``jd_text``/``location``/
``salary_min``/``salary_max``/``url``) against three rule types:

- ``blacklist``      reject when any keyword appears in title/JD text/URL
- ``city_whitelist`` reject when the job location is outside the list
- ``min_salary``     reject when either salary bound sits below the floor

Rule values are plain comma/space separated tokens (keywords or cities); a
``min_salary`` value is a monthly-yuan number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .job_library import JobLibraryStore, _split_rule_value


@dataclass(frozen=True)
class RuleVerdict:
    """Outcome of a rule check for one job candidate."""

    accepted: bool
    reason: str | None = None
    rule_type: str | None = None


def _normalize_city(value: str) -> str:
    """Normalize a city token: strip whitespace and a trailing 市 suffix."""
    return re.sub(r"\s+", "", value).rstrip("市")


class RuleFilterEngine:
    """Evaluate tenant automation rules against a job candidate's metadata."""

    def __init__(self, store: JobLibraryStore):
        self._store = store

    def check(
        self,
        tenant_id: str,
        job_meta: dict[str, Any],
        preflight: bool = False,
    ) -> RuleVerdict:
        """Return the first rejecting verdict, or an accepting verdict.

        ``job_meta`` may carry ``title``, ``jd_text``, ``location``,
        ``salary_min``, ``salary_max`` and ``url``. Missing fields are
        treated as unknown, which only matters for the city whitelist
        (unknown location rejects when a whitelist exists) and min_salary
        (unknown salary skips the check).

        ``preflight=True`` is used before JD intake when only a link is
        known (legacy): city-whitelist and min-salary constraints are
        skipped because their inputs (location/salary) are not available
        until the page is parsed, so evaluating them would reject every
        candidate regardless of content. Backend crawling is retired; JD
        intake goes through the collector userscript or pasted text.
        """
        rules = self._store.list_rules(tenant_id, enabled_only=True)
        if not rules:
            return RuleVerdict(accepted=True)
        # Deterministic evaluation order: blacklist -> city -> salary, matching
        # the pipeline documentation regardless of rule insertion order.
        precedence = {"blacklist": 0, "city_whitelist": 1, "min_salary": 2}
        ordered = sorted(
            rules, key=lambda rule: precedence.get(rule["rule_type"], 99)
        )
        haystack = self._haystack(job_meta)
        location = job_meta.get("location")
        salary_min = job_meta.get("salary_min")
        salary_max = job_meta.get("salary_max")
        for rule in ordered:
            rule_type = rule["rule_type"]
            if rule_type == "blacklist":
                verdict = self._check_blacklist(rule, haystack)
            elif rule_type == "city_whitelist":
                if preflight and not location:
                    continue
                verdict = self._check_city(rule, location)
            elif rule_type == "min_salary":
                if preflight and salary_min is None and salary_max is None:
                    continue
                verdict = self._check_salary(
                    rule, salary_min, salary_max
                )
            else:
                continue
            if not verdict.accepted:
                return verdict
        return RuleVerdict(accepted=True)

    @staticmethod
    def _haystack(job_meta: dict[str, Any]) -> str:
        """Build the lowercased text searched by blacklist keywords."""
        parts = [
            str(job_meta.get("title") or ""),
            str(job_meta.get("jd_text") or ""),
            str(job_meta.get("url") or ""),
        ]
        return "\n".join(parts).lower()

    def _check_blacklist(
        self,
        rule: dict[str, Any],
        haystack: str,
    ) -> RuleVerdict:
        for keyword in _split_rule_value(rule["value"]):
            lowered = keyword.lower()
            if not lowered:
                continue
            if lowered in haystack:
                return RuleVerdict(
                    accepted=False,
                    reason=f"命中黑名单关键词：{keyword}",
                    rule_type="blacklist",
                )
        return RuleVerdict(accepted=True)

    def _check_city(
        self,
        rule: dict[str, Any],
        location: Any,
    ) -> RuleVerdict:
        cities = [_normalize_city(city) for city in _split_rule_value(rule["value"])]
        if not cities:
            # An empty whitelist disables the constraint.
            return RuleVerdict(accepted=True)
        location_value = str(location or "").strip()
        if not location_value:
            return RuleVerdict(
                accepted=False,
                reason="岗位城市未知，不在城市白名单内",
                rule_type="city_whitelist",
            )
        normalized = _normalize_city(location_value)
        for city in cities:
            if normalized == city or city in normalized or normalized in city:
                return RuleVerdict(accepted=True)
        return RuleVerdict(
            accepted=False,
            reason=f"岗位城市「{location_value}」不在白名单内",
            rule_type="city_whitelist",
        )

    def _check_salary(
        self,
        rule: dict[str, Any],
        salary_min: Any,
        salary_max: Any,
    ) -> RuleVerdict:
        try:
            threshold = float(rule["value"])
        except (TypeError, ValueError):
            # A malformed stored threshold is ignored, never a hard failure.
            return RuleVerdict(accepted=True)
        if salary_min is None and salary_max is None:
            # Unknown salary: cannot judge, so skip the constraint.
            return RuleVerdict(accepted=True)
        low = float(salary_min) if salary_min is not None else None
        high = float(salary_max) if salary_max is not None else None
        if (high is not None and high < threshold) or (
            low is not None and low < threshold
        ):
            return RuleVerdict(
                accepted=False,
                reason=f"薪资低于最低要求（{threshold:g}）",
                rule_type="min_salary",
            )
        return RuleVerdict(accepted=True)
