"""State models for the alignment Graph executor."""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class AlignmentStatus(str, Enum):
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"

class StageResult(BaseModel):
    stage: str = ""
    status: str = "pending"
    result: Any = None
    error: Optional[str] = None
    fallback_used: bool = False
    actual_model: str = ""
    duration_ms: float = 0.0

class AlignmentState(BaseModel):
    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    job_id: str = ""
    resume_text: str = ""
    jd_text: str = ""
    jd_profile: Optional[dict] = None
    gap_report: Optional[dict] = None
    tailored_draft: Optional[dict] = None
    eval_score: Optional[dict] = None
    retry_count: int = 0
    max_retries: int = 1
    current_node: str = "start"
    completed_nodes: list[str] = Field(default_factory=list)
    stage_results: list[StageResult] = Field(default_factory=list)
    status: AlignmentStatus = AlignmentStatus.RUNNING
    errors: list[dict] = Field(default_factory=list)
    fallback_used: bool = False
    provenance_ratio: float = 0.0
    provenance_entities: list[str] = Field(default_factory=list)
    hallucination_flags: list[str] = Field(default_factory=list)
    granularity: str = "medium"
    prompt_focus: str = "balanced"
    custom_prompt: str = ""
    rewrite_style: str = ""
    run_eval: bool = False
    model_config = {"arbitrary_types_allowed": True, "frozen": False, "use_enum_values": True}
