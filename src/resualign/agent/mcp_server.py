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
    if not config.api_key:
        return {"status": "error", "error": "API key not configured"}

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
