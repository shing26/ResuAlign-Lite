from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiffItem:
    diff_id: str = ""
    type: str = "modify"
    original: str = ""
    proposed: str = ""
    reason: str = ""
    confidence: str = "medium"
    provenance: str = ""
    provenance_quote: str = ""
    source_span: Optional[tuple[int, int]] = None
    provenance_state: str = "pending_review"


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

    @property
    def required_skills(self) -> list[str]:
        """Public alias for the required-skill contract."""
        return self.must_have_skills

    @property
    def nice_to_have(self) -> list[str]:
        """Public alias for the optional-skill contract."""
        return self.nice_to_have_skills

    @property
    def business_scene(self) -> list[str]:
        """Public alias for the business-scenario contract."""
        return self.business_scenarios


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
    invalid_diffs: list[DiffItem] = field(default_factory=list)


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
