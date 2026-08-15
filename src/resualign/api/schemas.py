from typing import Any, Literal

from pydantic import BaseModel, Field, StrictBool

_JD_TEXT_MAX = 100_000
_RESUME_TEXT_MAX = 200_000
_DRAFT_MAX = 200_000
_CSV_TEXT_MAX = 2_000_000
_CUSTOM_PROMPT_MAX = 4_000
_TITLE_MAX = 200
_COMPANY_MAX = 200
_LOCATION_MAX = 100
_URL_MAX = 2_000
_RULE_VALUE_MAX = 2_000
_LABEL_MAX = 200


class AnalyzeRequest(BaseModel):
    resume_text: str = Field(max_length=_RESUME_TEXT_MAX)
    jd_text: str | None = Field(default=None, max_length=_JD_TEXT_MAX)
    jd_url: str | None = Field(default=None, max_length=_URL_MAX)
    run_eval: bool = False
    granularity: Literal['fine', 'medium', 'coarse'] = 'medium'
    prompt_focus: Literal['balanced', 'quantified', 'skills'] = 'balanced'

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class MasterResumeCreateRequest(BaseModel):
    title: str = Field(max_length=_TITLE_MAX)
    content: str = Field(max_length=_RESUME_TEXT_MAX)

class MasterResumeUpdateRequest(BaseModel):
    content: str = Field(max_length=_RESUME_TEXT_MAX)

class MasterResumeRollbackRequest(BaseModel):
    version: int

class ApplicationCreateRequest(BaseModel):
    title: str = Field(max_length=_TITLE_MAX)
    master_resume_id: str
    jd_text: str | None = Field(default=None, max_length=_JD_TEXT_MAX)
    jd_url: str | None = Field(default=None, max_length=_URL_MAX)

class ApplicationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=_TITLE_MAX)
    jd_text: str | None = Field(default=None, max_length=_JD_TEXT_MAX)
    jd_url: str | None = Field(default=None, max_length=_URL_MAX)
    status: str | None = None

class JobCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=_TITLE_MAX)
    jd_text: str | None = Field(default=None, max_length=_JD_TEXT_MAX)
    jd_url: str | None = Field(default=None, max_length=_URL_MAX)
    company: str | None = Field(default=None, max_length=_COMPANY_MAX)
    location: str | None = Field(default=None, max_length=_LOCATION_MAX)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    source_type: str | None = None
    source_url: str | None = Field(default=None, max_length=_URL_MAX)
    job_function: str | None = None
    seniority: str | None = None
    tech_tags: list[str] | None = None
    status: str | None = None
    posting_date: str | None = None

class JDParseRequest(BaseModel):
    jd_url: str = Field(max_length=_URL_MAX)

class JobUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=_TITLE_MAX)
    jd_text: str | None = Field(default=None, max_length=_JD_TEXT_MAX)
    company: str | None = Field(default=None, max_length=_COMPANY_MAX)
    location: str | None = Field(default=None, max_length=_LOCATION_MAX)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    source_type: str | None = None
    source_url: str | None = Field(default=None, max_length=_URL_MAX)
    job_function: str | None = None
    seniority: str | None = None
    tech_tags: list[str] | None = None
    status: str | None = None
    posting_date: str | None = None
    next_step_due_at: str | None = None
    interview_stage: str | None = None
    tailor_granularity: Literal['fine', 'medium', 'coarse'] | None = None
    tailor_focus: Literal['balanced', 'quantified', 'skills'] | None = None
    custom_prompt: str | None = Field(default=None, max_length=_CUSTOM_PROMPT_MAX)

class BulkStatusRequest(BaseModel):
    job_ids: list[str]
    status: str

class JobImportRequest(BaseModel):
    jobs: list[dict[str, Any]] | None = None
    csv_text: str | None = Field(default=None, max_length=_CSV_TEXT_MAX)

_LLM_KEY_MAX = 2_000


class LLMSettingsUpdate(BaseModel):
    """Editable LLM configuration persisted per user.

    ``api_key`` is accepted only on writes; reads return a masked hint.
    Omitted keys keep their stored value; explicit ``null`` clears a field.
    """

    provider: Literal["deepseek", "openrouter", "ollama"] | None = None
    model: str | None = Field(default=None, max_length=_TITLE_MAX)
    api_key: str | None = Field(default=None, max_length=_LLM_KEY_MAX)
    base_url: str | None = Field(default=None, max_length=_URL_MAX)


class SettingsTestConnectionRequest(BaseModel):
    """Optional in-form values used by the connectivity probe.

    Empty fields fall back to the persisted store, then .env / env vars,
    mirroring the real pipeline resolution order.
    """

    provider: Literal["deepseek", "openrouter", "ollama"] | None = None
    model: str | None = Field(default=None, max_length=_TITLE_MAX)
    api_key: str | None = Field(default=None, max_length=_LLM_KEY_MAX)
    base_url: str | None = Field(default=None, max_length=_URL_MAX)


class LLMNodeCreateRequest(BaseModel):
    """Register a new LLM provider node for the tenant.

    The first node of a tenant becomes the active node automatically; later
    nodes stay inactive until explicitly activated.
    """

    name: str = Field(max_length=_TITLE_MAX)
    provider: Literal["deepseek", "openrouter", "ollama"]
    base_url: str | None = Field(default=None, max_length=_URL_MAX)
    api_key: str | None = Field(default=None, max_length=_LLM_KEY_MAX)
    model: str = Field(max_length=_TITLE_MAX)


class LLMNodeUpdateRequest(BaseModel):
    """Partially update a node; omitted fields keep their stored value.

    ``is_active=True`` switches the tenant's active node (all others are
    deactivated); explicit ``null`` clears a string field.
    """

    name: str | None = Field(default=None, max_length=_TITLE_MAX)
    provider: Literal["deepseek", "openrouter", "ollama"] | None = None
    base_url: str | None = Field(default=None, max_length=_URL_MAX)
    api_key: str | None = Field(default=None, max_length=_LLM_KEY_MAX)
    model: str | None = Field(default=None, max_length=_TITLE_MAX)
    is_active: bool | None = None


class SettingsUpdateRequest(BaseModel):
    classification_vocabulary: dict[str, list[str]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    eval_default: StrictBool | None = None
    llm: LLMSettingsUpdate | None = None

class WorkbenchRunRequest(BaseModel):
    master_resume_id: str
    granularity: Literal['fine', 'medium', 'coarse'] = 'medium'
    prompt_focus: Literal['balanced', 'quantified', 'skills'] = 'balanced'
    custom_prompt: str | None = Field(default=None, max_length=_CUSTOM_PROMPT_MAX)
    run_eval: bool | None = None

class WorkbenchAcceptRequest(BaseModel):
    job_id: str
    accepted_indices: list[int] = []

class FinalDraftRequest(BaseModel):
    draft: str = Field(max_length=_DRAFT_MAX)
    accepted_diff_ids: list[str] = Field(default_factory=list)


class WorkbenchSessionInitRequest(BaseModel):
    """Create a workstation session from a pasted JD or a JD URL."""

    raw_jd: str | None = Field(default=None, max_length=_JD_TEXT_MAX)
    jd_url: str | None = Field(default=None, max_length=_URL_MAX)
    master_resume_id: str | None = None
    resume_text: str | None = Field(default=None, max_length=_RESUME_TEXT_MAX)
    granularity: Literal["fine", "medium", "coarse"] = "medium"
    prompt_focus: Literal["balanced", "quantified", "skills"] = "balanced"
    custom_prompt: str | None = Field(default=None, max_length=_CUSTOM_PROMPT_MAX)
    idempotency_key: str | None = None


class WorkstationJDSection(BaseModel):
    profile: dict[str, Any] | None = None
    status: Literal["queued", "ready", "failed"] = "queued"
    error: str | None = None


class WorkstationResumeSection(BaseModel):
    selected_resume_id: str | None = None
    available_resumes: list[dict[str, Any]] = Field(default_factory=list)
    content_ref: str | None = None


class WorkstationGapSection(BaseModel):
    status: Literal["queued", "running", "ready", "failed", "blocked"] = "queued"
    score: float | None = None
    gap_report: dict[str, Any] | None = None
    cache_hit: bool = False
    error: str | None = None


class WorkstationAlignmentSection(BaseModel):
    status: Literal["idle", "queued", "running", "succeeded", "failed"] = "idle"
    stage: str = ""
    diffs: list[dict[str, Any]] = Field(default_factory=list)
    invalid_diffs: list[dict[str, Any]] = Field(default_factory=list)
    draft: str | None = None
    eval_score: dict[str, Any] | None = None


class WorkstationCrawlSection(BaseModel):
    crawl_id: str | None = None
    status: Literal[
        "idle",
        "queued",
        "fetching",
        "parsing",
        "classifying",
        "succeeded",
        "failed",
    ] = "idle"
    stage: str = ""
    error: str | None = None


class WorkstationMeta(BaseModel):
    etag: str = ""
    updated_at: str = ""
    event_url: str = ""


class WorkstationState(BaseModel):
    session_id: str
    status: Literal["initializing", "ready", "failed"] = "initializing"
    job: dict[str, Any] | None = None
    jd: WorkstationJDSection = Field(default_factory=WorkstationJDSection)
    resume: WorkstationResumeSection = Field(default_factory=WorkstationResumeSection)
    gap: WorkstationGapSection = Field(default_factory=WorkstationGapSection)
    alignment: WorkstationAlignmentSection = Field(
        default_factory=WorkstationAlignmentSection
    )
    crawl: WorkstationCrawlSection = Field(default_factory=WorkstationCrawlSection)
    meta: WorkstationMeta = Field(default_factory=WorkstationMeta)


class KanbanBulkStatusRequest(BaseModel):
    job_ids: list[str]
    status: str
    expected_status: str | None = None
    idempotency_key: str | None = None


class KanbanBulkStatusResultItem(BaseModel):
    job_id: str
    updated: bool = False
    status: Literal["updated", "not_found", "conflict", "error"] = "updated"
    job: dict[str, Any] | None = None
    error: str | None = None


class KanbanBulkStatusResponse(BaseModel):
    idempotency_key: str | None = None
    updated: int = 0
    total: int = 0
    results: list[KanbanBulkStatusResultItem] = Field(default_factory=list)


class JobPreanalyzeResponse(BaseModel):
    job_id: str
    status: Literal["ready", "failed"] = "ready"
    jd_profile: dict[str, Any] | None = None
    gap_report: dict[str, Any] | None = None
    match_score: float | None = None
    classification: dict[str, Any] | None = None
    cache_hit: bool = False
    error: str | None = None


class WorkbenchRewriteRequest(BaseModel):
    diff_id: str
    instruction: Literal["quantified", "high_concurrency", "concise"] = (
        "quantified"
    )


class WorkbenchRewriteResponse(BaseModel):
    diff_id: str
    original: str
    proposed: str
    reason: str = ""
    provenance_state: str = "verified"


class DashboardKPI(BaseModel):
    """Aggregated counters for the dashboard header."""

    resumes: int = 0
    jobs: int = 0
    applied: int = 0
    interview: int = 0
    offer: int = 0
    declined: int = 0
    active_followups: int = 0


class SkillGapItem(BaseModel):
    """One must-have skill frequency across the tenant's job library."""

    skill: str
    count: int


class DashboardQuickContinue(BaseModel):
    """The single job suggested for continued alignment work."""

    job_id: str
    title: str
    company: str | None = None
    alignment_status: str = "idle"
    updated_at: float | None = None


class DashboardResponse(BaseModel):
    """Aggregated data for GET /api/dashboard."""

    kpi: DashboardKPI
    skill_gaps: list[SkillGapItem] = Field(default_factory=list)
    quick_continue: DashboardQuickContinue | None = None


class AutomationRuleCreateRequest(BaseModel):
    """Create one automation rule for the fetch pipeline."""

    rule_type: Literal["blacklist", "city_whitelist", "min_salary"]
    value: str = Field(max_length=_RULE_VALUE_MAX)
    label: str | None = Field(default=None, max_length=_LABEL_MAX)
    enabled: bool = True


class AutomationRuleUpdateRequest(BaseModel):
    """Partially update an automation rule (None leaves a field unchanged)."""

    value: str | None = Field(default=None, max_length=_RULE_VALUE_MAX)
    label: str | None = Field(default=None, max_length=_LABEL_MAX)
    enabled: bool | None = None


class FetchUrlRequest(BaseModel):
    """Submit one JD URL to the fetch pipeline."""

    url: str = Field(max_length=_URL_MAX)


class BlockerResolveRequest(BaseModel):
    """Resolve a blocker by building a library job from pasted JD text."""

    manual_text: str = Field(max_length=_JD_TEXT_MAX)

