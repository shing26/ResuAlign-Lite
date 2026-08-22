"""Pydantic response models for structured LLM outputs."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Analysis(BaseModel):
    score: int = 0
    issues: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)


class JDProfile(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    business_scene: list[str] = Field(default_factory=list)
    must_have_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    business_scenarios: list[str] = Field(default_factory=list)
    min_years_experience: Optional[int] = None
    education_requirements: list[str] = Field(default_factory=list)


class GapReport(BaseModel):
    missing_keywords: list[str] = Field(default_factory=list)
    misaligned_emphasis: list[str] = Field(default_factory=list)
    strength_matches: list[str] = Field(default_factory=list)


class JDAnalysis(BaseModel):
    jd_profile: JDProfile = Field(default_factory=JDProfile)
    gap_report: GapReport = Field(default_factory=GapReport)


class ClassifierResult(BaseModel):
    job_function: str = ""
    seniority: str = ""
    tech_tags: list[str] = Field(default_factory=list)


class JdIntakeDecision(BaseModel):
    action: Literal["keep_pending", "resolve"] = "keep_pending"
    reason: str = ""


class DiffItem(BaseModel):
    diff_id: str = ""
    # Resume section this diff belongs to (e.g. "项目经历"); the LLM fills it
    # when it can, otherwise it stays "" (additive, backward-compatible).
    section: str = ""
    type: Literal["modify", "add", "remove"] = "modify"
    original: str = ""
    proposed: str = ""
    reason: str = ""
    confidence: Literal["high", "medium", "low"] = "medium"
    provenance: str = ""
    provenance_quote: str = ""
    source_span: Optional[tuple[int, int]] = None
    provenance_state: Literal[
        "verified",
        "ambiguous",
        "missing",
        "pending_review",
    ] = "pending_review"


class TailoredResume(BaseModel):
    sections: dict[str, str] = Field(default_factory=dict)
    diffs: list[DiffItem] = Field(default_factory=list)
    invalid_diffs: list[DiffItem] = Field(default_factory=list)

    @field_validator("sections", mode="before")
    @classmethod
    def _normalize_section_values(cls, value: object) -> object:
        """Accept nested section values by flattening them into Markdown text.

        LLM JSON responses occasionally nest section content as objects or
        arrays (e.g. ``{"工作经历": {"公司": "…", "职位": "…"}}``); the strict
        ``dict[str, str]`` declaration used to reject those with a confusing
        ``Input should be a valid string`` error. Flattening keeps the content
        and gives callers a single string per section.
        """
        if not isinstance(value, dict):
            return value

        def _flatten(item: object) -> str:
            if isinstance(item, dict):
                return "\n".join(f"{k}: {_flatten(v)}" for k, v in item.items())
            if isinstance(item, list):
                return "\n".join(f"- {_flatten(v)}" for v in item)
            if item is None:
                return ""
            return str(item)

        return {str(key): _flatten(item) for key, item in value.items()}


class EvalScore(BaseModel):
    jd_match_score: int = 0
    improvement: int = 0
    hallucination_detected: bool = False
    hallucination_details: list[str] = Field(default_factory=list)
    gap_coverage: float = 0.0


# Aliases make the registry easy to consume both by domain name and by suffix.
AnalysisModel = Analysis
JDProfileModel = JDProfile
GapReportModel = GapReport
JDAnalysisModel = JDAnalysis
ClassifierResultModel = ClassifierResult
JdIntakeDecisionModel = JdIntakeDecision
DiffItemModel = DiffItem
TailoredResumeModel = TailoredResume
EvalScoreModel = EvalScore

AnalysisSchema = Analysis
JDProfileSchema = JDProfile
GapReportSchema = GapReport
JDAnalysisSchema = JDAnalysis
ClassifierResultSchema = ClassifierResult
JdIntakeDecisionSchema = JdIntakeDecision
DiffItemSchema = DiffItem
TailoredResumeSchema = TailoredResume
EvalScoreSchema = EvalScore
