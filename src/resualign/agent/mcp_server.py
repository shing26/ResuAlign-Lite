"""MCP server exposing the ResuAlign pipeline to agent runtimes.

The server exposes four tools that mirror the personal workbench API but
are callable directly by an MCP client (Claude Desktop, coding agents,
``mcp.run()`` hosts):

- ``fetch_and_evaluate_job``  run the Sprint 3 URL pipeline state machine
- ``auto_align_resume``       queue a workbench alignment against a master resume
- ``get_pending_blockers``    list the tenant's pending blocker queue
- ``resolve_blocker``         resolve a blocker by pasting JD text

Every tool defaults to the personal-mode tenant ``"local"`` and accepts an
explicit ``tenant_id`` for multi-tenant callers.

The ``@mcp.tool()`` decorator registers each function with FastMCP and
returns the *plain* function, so tools can be imported and called directly
in tests without starting any transport::

    from resualign.agent.mcp_server import fetch_and_evaluate_job
    result = fetch_and_evaluate_job(url="https://example.com/jobs/1")
"""

from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

import resualign.api as api_module

from ..reminders import AUTO_FOLLOWUP_MESSAGE, auto_followup_due_at

logger = logging.getLogger(__name__)

DEFAULT_TENANT = "local"

mcp = FastMCP(
    "resualign",
    instructions=(
        "ResuAlign agent tools: fetch a JD URL and evaluate it into the job "
        "library, queue resume alignment runs against the master resume, and "
        "inspect/resolve pipeline blockers. All tools default to the personal "
        "'local' tenant and accept an explicit tenant_id for multi-tenant "
        "callers."
    ),
)


def _user(tenant_id: str) -> dict[str, Any]:
    """Build the user dict consumed by ``_queue_job`` / ``_create_job_from_source``."""
    return {"user_id": tenant_id or DEFAULT_TENANT}


def _resolve_master_resume(
    tenant_id: str, master_resume_id: str | None
) -> dict[str, Any] | None:
    """Resolve the requested resume, or the tenant's first master resume."""
    if master_resume_id:
        return api_module._resumes.get_master_resume(
            tenant_id, master_resume_id
        )
    resumes = api_module._resumes.list_master_resumes(tenant_id)
    return resumes[0] if resumes else None


def _maybe_emit_low_confidence(job: dict[str, Any]) -> None:
    """Emit ``alignment.low_confidence`` when the job already carries low
    confidence diffs (e.g. from a previous alignment run).

    Optional nicety: the freshly queued analysis has not produced diffs yet,
    so this surfaces *known* review-worthy diffs without blocking the queue.
    """
    diffs = job.get("diffs") or []
    for index, diff in enumerate(diffs):
        if str(diff.get("confidence", "")).lower() == "low":
            from .hitl import emit_hitl_event

            emit_hitl_event(
                "alignment.low_confidence",
                {
                    "job_id": job["job_id"],
                    "diff_index": index,
                    "confidence": "low",
                },
            )
            return


@mcp.tool()
def fetch_and_evaluate_job(
    url: str, tenant_id: str = DEFAULT_TENANT
) -> dict[str, Any]:
    """Fetch a JD URL and run the Sprint 3 pipeline state machine.

    Returns ``{status, job_id?, blocker_id?, category?, reason?}`` where
    status is one of ``created`` / ``duplicate`` / ``blocked`` /
    ``rule_rejected``. A blocked/rejected result leaves a durable entry in
    the tenant's blocker queue (and fires a ``blocker.created`` HITL event).
    """
    return api_module._fetcher.submit_url(tenant_id, url)


@mcp.tool()
def auto_align_resume(
    job_id: str,
    master_resume_id: str | None = None,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Queue a workbench alignment run for a library job.

    Uses the master resume pinned to the job (``master_resume_id``) or the
    tenant's first master resume. The run is queued through the same
    ``_queue_job(user, payload, workbench=True)`` path as the web API, with
    ``granularity`` defaulting to ``medium``.

    Returns ``{analysis_job_id, status: 'queued'}`` on success or
    ``{status: 'error', error}`` when the job/resume is missing, the JD is
    empty, or no LLM API key is configured.
    """
    job = api_module._jobs.get_job(tenant_id, job_id)
    if job is None:
        return {"status": "error", "error": "job not found", "job_id": job_id}
    if not (job.get("jd_text") or "").strip():
        return {
            "status": "error",
            "error": "job has no JD text",
            "job_id": job_id,
        }
    resume = _resolve_master_resume(tenant_id, master_resume_id)
    if resume is None:
        return {
            "status": "error",
            "error": "master resume not found",
            "job_id": job_id,
        }
    config = api_module.build_config()
    if not config.is_llm_configured:
        return {"status": "error", "error": "LLM 未配置"}

    user = _user(tenant_id)
    payload: dict[str, Any] = {
        "resume_text": resume["content"],
        "jd_text": job["jd_text"],
        "jd_url": job.get("source_url"),
        "run_eval": False,
        "granularity": "medium",
        "prompt_focus": "balanced",
        "custom_prompt": "",
        "master_resume_id": resume["resume_id"],
        "library_job_id": job_id,
    }
    analysis_job_id = api_module._queue_job(user, payload, workbench=True)
    api_module._jobs.update_job(
        tenant_id,
        job_id,
        workbench_job_id=analysis_job_id,
        workbench_resume_id=resume["resume_id"],
        tailor_granularity="medium",
        tailor_focus="balanced",
        custom_prompt="",
    )
    _maybe_emit_low_confidence(job)
    return {"analysis_job_id": analysis_job_id, "status": "queued"}


@mcp.tool()
def get_pending_blockers(tenant_id: str = DEFAULT_TENANT) -> list[dict[str, Any]]:
    """Return the tenant's pending pipeline blockers, newest first.

    Each item carries ``{blocker_id, url, title, reason, category,
    created_at}``. Blockers are created by fetch failures and rule
    rejections; agents use this to decide what needs human attention.
    """
    blockers = api_module._jobs.list_blockers(tenant_id, status="pending")
    return [
        {
            "blocker_id": blocker["blocker_id"],
            "url": blocker.get("url"),
            "title": blocker.get("title"),
            "reason": blocker.get("reason"),
            "category": blocker.get("category"),
            "created_at": blocker.get("created_at"),
        }
        for blocker in blockers
    ]


@mcp.tool()
def resolve_blocker(
    blocker_id: str, text: str, tenant_id: str = DEFAULT_TENANT
) -> dict[str, Any]:
    """Resolve a pending blocker by pasting the JD text into the library.

    Creates a library job from the pasted text and marks the blocker
    resolved. Returns ``{status: 'resolved', blocker_id, job_id}`` on
    success, or ``{status: 'error', error, blocker_id}`` when the blocker is
    missing or not in a pending state.
    """
    try:
        result = api_module._fetcher.resolve_blocker_with_text(
            tenant_id, blocker_id, text
        )
    except api_module.UserStoreError as exc:
        return {
            "status": "error",
            "error": str(exc),
            "blocker_id": blocker_id,
        }
    if result is None:
        return {
            "status": "error",
            "error": "blocker not found",
            "blocker_id": blocker_id,
        }
    return {
        "status": "resolved",
        "blocker_id": blocker_id,
        "job_id": result["job"]["job_id"],
    }


def _job_profile_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """Return the structured JD profile, hard gates, and classification."""
    profile = job.get("jd_profile") or {}
    if not isinstance(profile, dict):
        profile = {}
    return {
        "jd_profile": profile,
        "hard_gates": {
            "min_years_experience": profile.get("min_years_experience"),
            "education_requirements": profile.get(
                "education_requirements"
            )
            or [],
        },
        "classification": {
            "job_function": job.get("job_function"),
            "seniority": job.get("seniority"),
            "tech_tags": job.get("tech_tags") or [],
        },
    }


@mcp.tool()
def job_ingest_and_profile(
    source: str,
    source_type: str = "url",
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Ingest a JD URL or raw text and return its structured profile.

    ``source_type`` accepts ``url`` or ``text``. URL ingestion runs the
    existing fetch pipeline (including automation rules and blocker
    creation); text ingestion creates a paste-sourced library job directly.
    """
    kind = (source_type or "url").strip().lower()
    if kind not in {"url", "text"}:
        return {"status": "error", "error": "source_type must be url or text"}
    if not (source or "").strip():
        return {"status": "error", "error": "source is required"}
    if kind == "url":
        result = api_module._fetcher.submit_url(tenant_id, source)
    else:
        try:
            job = api_module._create_job_from_source(
                {"user_id": tenant_id},
                {"jd_text": source, "source_type": "text"},
            )
        except api_module.UserStoreError as exc:
            return {"status": "error", "error": str(exc)}
        result = {"status": "created", "job_id": job["job_id"]}
    if result.get("status") != "created":
        return {
            **result,
            "jd_profile": None,
            "hard_gates": None,
            "classification": None,
        }
    job = api_module._jobs.get_job(tenant_id, result["job_id"]) or {}
    return {**result, **_job_profile_snapshot(job)}


@mcp.tool()
def resume_align_and_tailor(
    job_id: str,
    resume_id: str | None = None,
    style: str | None = None,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Queue a full alignment-and-tailoring run for one library job.

    The run goes through the same workbench queue as the web UI and executes
    the Graph pipeline (JD profiling, gap analysis, style routing, STAR
    tailoring, provenance/anti-hallucination gates, ATS scoring). Poll the
    returned ``analysis_job_id`` through ``/api/jobs/{analysis_job_id}`` or
    the aligned library job for the diff report.
    """
    result = auto_align_resume(
        job_id=job_id,
        master_resume_id=resume_id,
        tenant_id=tenant_id,
    )
    if result.get("status") == "queued":
        result["style"] = style
    return result


@mcp.tool()
def job_tracker_manage(
    job_id: str,
    action: str,
    stage: str | None = None,
    note: str | None = None,
    due_at: str | None = None,
    tenant_id: str = DEFAULT_TENANT,
) -> dict[str, Any]:
    """Manage the job-board lifecycle for one library job.

    Actions: ``apply`` marks the job applied and creates the automatic
    3-day follow-up reminder; ``update_stage`` advances the interview stage;
    ``log_note`` appends a communication note; ``set_reminder`` sets the next
    follow-up step and due time.
    """
    job = api_module._jobs.get_job(tenant_id, job_id)
    if job is None:
        return {"status": "error", "error": "job not found", "job_id": job_id}
    action = (action or "").strip().lower()
    updates: dict[str, Any] = {}
    if action == "apply":
        updates["status"] = "applied"
        updates["applied_at"] = job.get("applied_at")
        updates["next_step"] = AUTO_FOLLOWUP_MESSAGE
        updates["next_step_due_at"] = auto_followup_due_at(
            job.get("applied_at")
        )
    elif action == "update_stage":
        if not (stage or "").strip():
            return {
                "status": "error",
                "error": "stage is required for update_stage",
                "job_id": job_id,
            }
        updates["interview_stage"] = stage
    elif action == "log_note":
        if not (note or "").strip():
            return {
                "status": "error",
                "error": "note is required for log_note",
                "job_id": job_id,
            }
        current_note = (job.get("notes") or "").strip()
        updates["notes"] = (
            f"{current_note}\n{note}" if current_note else note
        )
    elif action == "set_reminder":
        if not (due_at or "").strip():
            return {
                "status": "error",
                "error": "due_at is required for set_reminder",
                "job_id": job_id,
            }
        updates["next_step"] = (note or "").strip() or "跟进"
        updates["next_step_due_at"] = due_at
    else:
        return {
            "status": "error",
            "error": "action must be apply, update_stage, log_note, or set_reminder",
            "job_id": job_id,
        }
    updated = api_module._jobs.update_job(tenant_id, job_id, **updates)
    if updated is None:
        return {"status": "error", "error": "job update failed", "job_id": job_id}
    return {
        "status": "updated",
        "job_id": job_id,
        "action": action,
        "job": updated,
    }


@mcp.tool()
def master_resume_query(
    resume_id: str,
    query: str,
    top_k: int = 5,
    tenant_id: str = DEFAULT_TENANT,
) -> list[dict[str, Any]]:
    """Keyword-search a master resume for atomic STAR experience fragments.

    Returns up to ``top_k`` matching lines/chunks with their provenance
    (resume id + line number) so callers can anchor generated claims to the
    source resume.
    """
    resume = api_module._resumes.get_master_resume(tenant_id, resume_id)
    if resume is None:
        return []
    content = (resume.get("content") or "").splitlines()
    keys = [k.strip().lower() for k in (query or "").split() if k.strip()]
    if not keys:
        keys = []
    scored: list[tuple[float, int, str]] = []
    for index, line in enumerate(content):
        text = line.strip()
        if not text:
            continue
        lowered = text.lower()
        score = sum(1 for key in keys if key in lowered)
        if score:
            scored.append((score, index, text))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "fragment": text,
            "line_number": index + 1,
            "score": score,
            "provenance": {
                "resume_id": resume_id,
                "title": resume.get("title"),
                "line": index + 1,
            },
            "situation": None,
            "task": None,
            "action": None,
            "result": None,
        }
        for score, index, text in scored[: max(0, int(top_k))]
    ]


def run(transport: str = "stdio") -> None:
    """Run the MCP server over stdio (default) or SSE.

    ``mcp.run(transport="sse")`` serves the Streamable HTTP/SSE endpoint so
    a remote MCP client can connect over HTTP.
    """
    mcp.run(transport=transport)


def get_mcp_app() -> FastMCP:
    """Return the FastMCP instance for embedding and tests."""
    return mcp


if __name__ == "__main__":
    run()
