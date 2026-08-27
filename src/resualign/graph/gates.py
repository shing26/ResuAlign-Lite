"""Deterministic gates for the alignment Graph.

Provenance, hallucination, minimum requirements, and ATS scoring gates.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel


class GateResult(BaseModel):
    passed: bool = False
    score: float = 0.0
    details: list[str] = []
    entities: list[str] = []
    flags: list[str] = []


class ProvenanceGate:
    """Check that rewritten entities belong to the Master Resume (>=80%)."""
    THRESHOLD = 0.8

    @staticmethod
    def _extract_entities(text: str) -> set[str]:
        tokens = re.findall(r"[A-Za-z0-9#+./_-]+", text)
        return {t.lower() for t in tokens if len(t) > 2}

    @staticmethod
    def _extract_cjk_tokens(text: str) -> set[str]:
        """Extract CJK bigrams as entity proxies (Chinese resumes)."""
        cjk = re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]{2,}", text)
        result: set[str] = set()
        for chunk in cjk:
            for i in range(len(chunk) - 1):
                result.add(chunk[i:i+2].lower())
            result.add(chunk.lower())
        return result

    @classmethod
    def check(cls, original: str, proposed: str = "", diffs: Optional[list[dict]] = None) -> GateResult:
        orig_entities = cls._extract_entities(original) | cls._extract_cjk_tokens(original)
        if diffs:
            proposed_text = " ".join(d.get("proposed", "") or "" for d in diffs)
        else:
            proposed_text = proposed
        prop_entities = cls._extract_entities(proposed_text) | cls._extract_cjk_tokens(proposed_text)
        if not prop_entities:
            return GateResult(passed=True, score=1.0, details=["No entities to check"])
        if not orig_entities:
            return GateResult(passed=False, score=0.0, details=["Original resume has no entities"])
        matched = prop_entities & orig_entities
        ratio = len(matched) / len(prop_entities) if prop_entities else 1.0
        missing = sorted(prop_entities - orig_entities)
        return GateResult(
            passed=ratio >= cls.THRESHOLD,
            score=ratio,
            details=[f"matched {len(matched)}/{len(prop_entities)} entities (threshold={cls.THRESHOLD})"],
            entities=list(matched),
            flags=missing[:20],
        )


class AntiHallucinationGate:
    """Cross-check that numbers and metrics match the original resume."""

    @staticmethod
    def _extract_numbers(text: str) -> list[tuple[str, str]]:
        return re.findall(r"(\w+(?:\s+\w+){0,3})\s*[:\s]\s*(\d{2,}(?:\.\d+)?%?)", text)

    @classmethod
    def check(cls, original: str, proposed: str = "", diffs: Optional[list[dict]] = None) -> GateResult:
        if diffs:
            proposed_text = " ".join(d.get("proposed", "") or "" for d in diffs)
        else:
            proposed_text = proposed
        orig_numbers = cls._extract_numbers(original)
        prop_numbers = cls._extract_numbers(proposed_text)
        flags = []
        orig_num_set = {n for _, n in orig_numbers}
        for ctx, num in prop_numbers:
            if num not in orig_num_set:
                flags.append(f"{ctx}: {num} (not in original)")
        return GateResult(
            passed=len(flags) == 0,
            score=1.0 - (len(flags) / max(len(prop_numbers), 1)),
            details=[f"checked {len(prop_numbers)} metrics, {len(flags)} mismatches"],
            flags=flags[:20],
        )


class MinimumRequirementsGate:
    """Check hard minimum requirements: education, years, sensitivity keywords."""

    @staticmethod
    def _parse_education(text: str) -> list[str]:
        levels = []
        patterns = [
            (r"本科|学士|bachelor|undergraduate", "bachelor"),
            (r"硕士|研究生|master|graduate", "master"),
            (r"博士|ph\.?d|doctor", "phd"),
            (r"大专|专科|associate|college", "associate"),
        ]
        text_lower = text.lower()
        for pattern, level in patterns:
            if re.search(pattern, text_lower):
                levels.append(level)
        return levels

    @staticmethod
    def _has_sensitivity_keywords(text: str) -> list[str]:
        sensitive = ["机密", "classified", "保密协议", "nda", "安全保密"]
        return [kw for kw in sensitive if kw.lower() in text.lower()]

    @classmethod
    def check(
        cls,
        jd_profile: Optional[dict] = None,
        resume_text: str = "",
        jd_text: str = "",
    ) -> GateResult:
        details: list[str] = []
        passed = True

        if not jd_profile:
            return GateResult(passed=True, score=1.0, details=["No JD profile to check"])

        edu_reqs = jd_profile.get("education_requirements", [])
        edu_text = " ".join(edu_reqs) if edu_reqs else ""
        if edu_text:
            required_edu = cls._parse_education(edu_text)
            if required_edu:
                resume_edu = cls._parse_education(resume_text)
                edu_order = ["associate", "bachelor", "master", "phd"]
                min_idx = min((edu_order.index(e) for e in required_edu if e in edu_order), default=-1)
                resume_idx = max((edu_order.index(e) for e in resume_edu if e in edu_order), default=-1)
                if resume_idx >= 0 and min_idx >= 0 and resume_idx < min_idx:
                    details.append(f"Education: requires {required_edu}, resume has {resume_edu}")
                    passed = False
                else:
                    details.append(f"Education: meets requirement ({required_edu})")

        sensitive = cls._has_sensitivity_keywords(resume_text + " " + jd_text)
        if sensitive:
            details.append(f"Sensitivity keywords found: {sensitive}")

        return GateResult(
            passed=passed,
            score=1.0 if passed else 0.0,
            details=details if details else ["Minimum requirements pass (no hard constraints)"],
        )


def keyword_density_ats_score(state: Any) -> GateResult:
    """Simple ATS keyword density scorer.

    Compares required skills from JD profile against resume text.
    Returns a score between 0.0 and 1.0 based on keyword match ratio.
    """
    jd_profile = getattr(state, "jd_profile", None) or {}
    resume_text = getattr(state, "resume_text", "") or ""
    required = jd_profile.get("required_skills", []) or []
    if not required:
        return GateResult(passed=True, score=0.85, details=["No required skills to match"])
    matched = 0
    resume_lower = resume_text.lower()
    for skill in required:
        skill_lower = skill.lower().strip()
        if skill_lower and skill_lower in resume_lower:
            matched += 1
    ratio = matched / len(required)
    return GateResult(
        passed=ratio >= 0.3,
        score=ratio,
        details=[f"ATS score: {matched}/{len(required)} keywords matched ({ratio:.0%})"],
    )