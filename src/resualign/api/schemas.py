from typing import Any, Literal

from pydantic import BaseModel, Field

_JD_TEXT_MAX = 100_000
_RESUME_TEXT_MAX = 200_000
_DRAFT_MAX = 200_000
_CSV_TEXT_MAX = 2_000_000
_CUSTOM_PROMPT_MAX = 4_000
_TITLE_MAX = 200
_COMPANY_MAX = 200
_LOCATION_MAX = 100
_URL_MAX = 2_000


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


class SettingsUpdateRequest(BaseModel):
    salary_reference: list[dict[str, Any]] | None = None
    appraisal_weights: dict[str, float] | None = None
    classification_vocabulary: dict[str, list[str]] | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm: LLMSettingsUpdate | None = None

class WorkbenchRunRequest(BaseModel):
    master_resume_id: str
    granularity: Literal['fine', 'medium', 'coarse'] = 'medium'
    prompt_focus: Literal['balanced', 'quantified', 'skills'] = 'balanced'
    custom_prompt: str | None = Field(default=None, max_length=_CUSTOM_PROMPT_MAX)

class WorkbenchAcceptRequest(BaseModel):
    job_id: str
    accepted_indices: list[int] = []

class FinalDraftRequest(BaseModel):
    draft: str = Field(max_length=_DRAFT_MAX)


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
    appraisal: dict[str, Any] = Field(default_factory=dict)
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

