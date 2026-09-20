"""Persist one finished alignment run to the library job (R3-B).

Split out of ``jobs._run_job_holding_gate`` so the runner owns claim/run/
notify while this module owns the durable alignment product. It must run
*before* the registry job is marked succeeded: if persistence crashes, the
registry job stays non-terminal and startup recovery can requeue or flag it
instead of leaving a succeeded job with no durable product.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from ...app.context import context
from ...evaluator import EVALUATOR_PROMPT_VERSION
from ...gap_analyzer import GAP_ANALYZER_PROMPT_VERSION
from ...jd_profiler import JD_PROFILER_PROMPT_VERSION
from ...llm import DIAG_PROMPT_VERSION
from ...tailor import TAILOR_PROMPT_VERSION
from .alignment_rules import resolve_alignment_outcome, split_verified_diffs

logger = logging.getLogger(__name__)


@dataclass
class AlignmentOutcome:
    """Durable result of one alignment run, consumed by the notify phase."""

    library_job_id: str
    alignment_status: str
    alignment_error: str | None
    kept_diffs: list[dict[str, Any]]
    invalid_diffs: list[dict[str, Any]]
    draft: str | None
    eval_score: dict[str, Any] | None


def _draft_from_result(result: dict[str, Any]) -> str | None:
    sections = ((result.get("tailored_resume") or {}).get("sections") or {})
    if not sections:
        return None
    return "\n\n".join(str(value) for value in sections.values())


def _resolve_match_scoring(
    tenant_id: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    eval_score: dict[str, Any] | None,
) -> tuple[float | None, dict[str, Any] | None, str | None, float | None]:
    """Return ``(score, detail, reason, updated_at)`` for the saved job."""
    match_score = (
        eval_score.get("jd_match_score") if eval_score else None
    )
    if match_score is None:
        match_score = context._gap_match_score(result)
    match_detail = None
    match_reason = None
    match_updated_at = None
    library_job = context._jobs.get_job(tenant_id, payload["library_job_id"])
    if library_job and library_job.get("workbench_resume_id"):
        resume = context._resumes.get_master_resume(
            tenant_id,
            library_job["workbench_resume_id"],
        )
        resume_text = payload.get("resume_text") or (
            resume["content"] if resume else ""
        )
        if (
            resume_text
            and result.get("jd_profile")
            and result.get("gap_report")
        ):
            match_detail = context.compute_match_score(
                library_job.get("jd_text"),
                result.get("jd_profile"),
                result.get("gap_report"),
                eval_score,
                resume_text,
                library_job["workbench_resume_id"],
            )
            match_reason = context.fallback_match_reason(
                match_detail,
                (result.get("gap_report") or {}).get("missing_keywords") or [],
            )
            match_updated_at = time.time()
            match_score = match_detail["total"]
    return match_score, match_detail, match_reason, match_updated_at


def persist_alignment(
    tenant_id: str,
    job_id: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> AlignmentOutcome:
    """Write the alignment product and return what the notify phase needs.

    Raises on persistence failure so the caller keeps the registry job
    non-terminal for startup recovery.
    """
    library_job_id = payload["library_job_id"]
    tailored = result.get("tailored_resume") or {}
    draft = _draft_from_result(result)
    eval_score = result.get("eval_score")
    match_score, match_detail, match_reason, match_updated_at = (
        _resolve_match_scoring(tenant_id, payload, result, eval_score)
    )
    eval_hallucinated = bool(
        isinstance(eval_score, dict)
        and eval_score.get("hallucination_detected")
    )
    kept_diffs, invalid_diffs = split_verified_diffs(
        list(result.get("diffs") or []),
        list(tailored.get("invalid_diffs") or []),
        eval_hallucinated=eval_hallucinated,
        job_label=library_job_id,
    )
    result["diffs"] = kept_diffs
    alignment_status, alignment_error = resolve_alignment_outcome(
        kept_diffs=kept_diffs,
        gap_report=result.get("gap_report"),
        tailor_degraded=bool(result.get("tailor_degraded")),
        eval_hallucinated=eval_hallucinated,
    )
    try:
        context._jobs.save_alignment(
            tenant_id,
            library_job_id,
            jd_profile=result.get("jd_profile"),
            gap_report=result.get("gap_report"),
            match_score=match_score,
            match_score_detail=match_detail,
            match_reason=match_reason,
            match_updated_at=match_updated_at,
            diffs=kept_diffs,
            invalid_diffs=invalid_diffs,
            draft=draft,
            eval_score=eval_score,
            model=result.get("model") or "",
            prompt_version=(
                f"engine:diag:{DIAG_PROMPT_VERSION};"
                f"profiler:{JD_PROFILER_PROMPT_VERSION};"
                f"gap:{GAP_ANALYZER_PROMPT_VERSION};"
                f"tailor:{TAILOR_PROMPT_VERSION};"
                f"eval:{EVALUATOR_PROMPT_VERSION}"
            ),
            alignment_status=alignment_status,
            usable_diffs=len(kept_diffs),
            last_alignment_error=alignment_error,
        )
    except Exception:
        logger.exception(
            "Failed to persist alignment for library job %s; "
            "keeping analysis job %s non-terminal for recovery",
            library_job_id,
            job_id,
        )
        raise
    # 度量 A：一次产出结果的运行（含 tailor 降级）计一次 run。
    context._jobs.record_alignment_run(tenant_id)
    return AlignmentOutcome(
        library_job_id=library_job_id,
        alignment_status=alignment_status,
        alignment_error=alignment_error,
        kept_diffs=kept_diffs,
        invalid_diffs=invalid_diffs,
        draft=draft,
        eval_score=eval_score,
    )
