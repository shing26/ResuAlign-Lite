from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DiffItem:
    diff_id: str = ""
    # Resume section the diff belongs to (e.g. "项目经历", "工作经历").
    # Empty means "unknown/not grouped"; the frontend falls back to its own
    # grouping when section is blank (additive contract field, default "").
    section: str = ""
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
    fallback: str = ""
    jd_profile: Optional[JDProfile] = None
    gap_report: Optional[GapReport] = None
    tailored_resume: Optional[TailoredResume] = None
    eval_score: Optional[EvalScore] = None
    elapsed_seconds: float = 0.0
    provenance_ratio: float = 0.0
    graph_status: str = ""
    trace_id: str = ""
    # R4 P0-5（03-AIE §③）：gap 结构失败时降级为空 GapReport 并置位本标记，
    # 任务继续而非整体 fail；随 asdict(report) 流入 API 结果（落库标记）。
    gap_degraded: bool = False
    # editor 阶段反复失败时降级为空改写并置位本标记：诊断/画像/缺口照常
    # 保存（重试改写有 precomputed_diagnosis + profiler 缓存兜底），任务
    # succeeded 而非 failed；随 asdict(report) 流入 API 结果（落库标记）。
    tailor_degraded: bool = False


@dataclass
class ResuAlignConfig:
    provider: str = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = ""

    @property
    def is_llm_configured(self) -> bool:
        """Return True when the config can power LLM calls.

        Ollama is a local server that needs no API key; all other providers
        require a non-empty api_key.
        """
        return bool(self.api_key) or self.provider == "ollama"
