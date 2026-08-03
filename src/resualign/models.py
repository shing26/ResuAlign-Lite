from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiffItem:
    type: str = "modify"
    original: str = ""
    proposed: str = ""
    reason: str = ""
    confidence: str = "medium"
    provenance: str = ""


@dataclass
class Analysis:
    score: int = 0
    issues: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class JDProfile:
    must_have_skills: list[str] = field(default_factory=list)
    nice_to_have_skills: list[str] = field(default_factory=list)
    soft_skills: list[str] = field(default_factory=list)
    business_scenarios: list[str] = field(default_factory=list)
    min_years_experience: Optional[int] = None
    education_requirements: list[str] = field(default_factory=list)


@dataclass
class GapReport:
    missing_keywords: list[str] = field(default_factory=list)
    misaligned_emphasis: list[str] = field(default_factory=list)
    strength_matches: list[str] = field(default_factory=list)


@dataclass
class EvalScore:
    jd_match_score: int = 0
    improvement: int = 0
    hallucination_detected: bool = False
    hallucination_details: list[str] = field(default_factory=list)
    gap_coverage: float = 0.0


@dataclass
class TailoredResume:
    sections: dict[str, str] = field(default_factory=dict)
    diffs: list[DiffItem] = field(default_factory=list)


@dataclass
class Report:
    score: int = 0
    skills: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    diffs: list[DiffItem] = field(default_factory=list)
    model: str = ""
    jd_profile: Optional[JDProfile] = None
    gap_report: Optional[GapReport] = None
    tailored_resume: Optional[TailoredResume] = None
    eval_score: Optional[EvalScore] = None
    elapsed_seconds: float = 0.0


@dataclass
class ResuAlignConfig:
    provider: str = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = ""
