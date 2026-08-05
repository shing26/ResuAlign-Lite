"""Workstation session orchestration: init, read, poll, and SSE events."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from ..deps import get_current_user
from ..schemas import WorkbenchSessionInitRequest, WorkstationState

import resualign.api as api_module


router = APIRouter()


def _session_or_404(session_id: str, user: dict[str, Any]) -> dict[str, Any]:
    session = api_module._session_store.get(session_id, tenant_id=user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail="Workstation session not found")
    return session


@router.post(
    "/api/workbench/session/init",
    status_code=202,
    response_model=WorkstationState,
)
def init_workbench_session(
    req: WorkbenchSessionInitRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Create a workstation session from a pasted JD or JD URL.

    Returns immediately with a WorkstationState; crawling, classification,
    and JD profiling run on a background worker and stream through SSE.
    """
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    raw_jd = (req.raw_jd or "").strip()
    jd_url = (req.jd_url or "").strip()
    if not raw_jd and not jd_url:
        raise HTTPException(
            status_code=422, detail="Either raw_jd or jd_url is required"
        )
    existing = api_module._session_store.find_by_idempotency(
        user["user_id"], req.idempotency_key
    )
    if existing is not None:
        return api_module._workbench_service.public_state(existing)

    resume = None
    if req.master_resume_id:
        resume = api_module._resumes.get_master_resume(
            user["user_id"], req.master_resume_id
        )
        if resume is None:
            raise HTTPException(status_code=404, detail="Master resume not found")
    elif (req.resume_text or "").strip():
        resume = {"resume_id": None, "content": req.resume_text}

    job = None
    if raw_jd:
        try:
            job = api_module._workbench_service._create_library_job_without_llm(
                user,
                {"jd_text": raw_jd, "source_type": "paste"},
            )
        except api_module.UserStoreError as exc:
            if "Duplicate job" in str(exc):
                existing = api_module._jobs.find_by_dedupe_key(
                    user["user_id"],
                    api_module._workbench_service._library_dedupe_key(raw_jd),
                )
                if existing is not None:
                    session = api_module._session_store.find_by_job(
                        existing["job_id"], user["user_id"]
                    )
                    if session is not None:
                        return api_module._workbench_service.public_state(
                            session
                        )
                    return api_module._workbench_service.public_state(
                        api_module._session_store.create(
                            user["user_id"],
                            session_id=f"job:{existing['job_id']}",
                            status="ready",
                            job=existing,
                            jd={
                                "profile": existing.get("jd_profile"),
                                "status": "ready",
                                "error": None,
                            },
                            resume={
                                "selected_resume_id": existing.get(
                                    "workbench_resume_id"
                                ),
                                "available_resumes": api_module._workbench_service._available_resumes(
                                    user["user_id"]
                                ),
                                "content_ref": None,
                            },
                            gap={
                                "status": (
                                    "ready"
                                    if existing.get("gap_report")
                                    else "blocked"
                                ),
                                "score": existing.get("match_score"),
                                "gap_report": existing.get("gap_report"),
                                "cache_hit": False,
                                "error": None,
                            },
                            crawl={
                                "crawl_id": None,
                                "status": "idle",
                                "stage": "",
                                "error": None,
                            },
                        )
                    )
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    resume_section = {
        "selected_resume_id": req.master_resume_id,
        "available_resumes": api_module._workbench_service._available_resumes(
            user["user_id"]
        ),
        "content_ref": (
            None
            if req.master_resume_id
            else f"paste:{len((req.resume_text or '').strip())}"
        ),
    }
    crawl_section = {
        "crawl_id": uuid.uuid4().hex if jd_url else None,
        "status": "queued" if jd_url else "idle",
        "stage": "queued" if jd_url else "",
        "error": None,
    }
    session = api_module._session_store.create(
        user["user_id"],
        status="ready" if job else "initializing",
        job=job,
        jd={
            "profile": None,
            "status": "ready" if job else "queued",
            "error": None,
        },
        resume=resume_section,
        gap={
            "status": "blocked" if resume is None else "queued",
            "score": None,
            "gap_report": None,
            "cache_hit": False,
            "error": None,
        },
        crawl=crawl_section,
        raw_jd=raw_jd,
        jd_url=jd_url,
        master_resume_id=req.master_resume_id,
        resume_text=req.resume_text,
        granularity=req.granularity,
        prompt_focus=req.prompt_focus,
        custom_prompt=req.custom_prompt,
        idempotency_key=req.idempotency_key,
    )
    if job is not None:
        api_module._session_store.emit(
            session["session_id"],
            "job.stage",
            {"stage": "created", "message": "Job created", "job_id": job["job_id"]},
        )

    start_pipeline = bool(jd_url)
    if not start_pipeline:
        try:
            start_pipeline = bool(api_module.build_config().api_key)
        except Exception:
            start_pipeline = False
    if start_pipeline:
        threading.Thread(
            target=api_module._workbench_service._run_session_pipeline,
            args=(session["session_id"],),
            daemon=True,
        ).start()
    return api_module._workbench_service.public_state(session)


@router.get(
    "/api/workbench/session/{session_id}",
    response_model=WorkstationState,
)
def get_workbench_session(
    session_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the current workstation state, with polling via If-None-Match."""
    session = _session_or_404(session_id, user)
    state = api_module._workbench_service.public_state(session)
    if request.headers.get("If-None-Match") == state["meta"]["etag"]:
        return Response(status_code=304)
    return state


@router.get(
    "/api/workspace/session/{job_id}",
    response_model=WorkstationState,
)
def get_workspace_session(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Open an existing library job as a read-only workstation session."""
    job = api_module._jobs.get_job(user["user_id"], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    session = api_module._session_store.find_by_job(job_id, user["user_id"])
    if session is None:
        session = api_module._session_store.create(
            user["user_id"],
            session_id=f"job:{job_id}",
            status="ready",
            job=job,
            jd={"profile": None, "status": "ready", "error": None},
            resume={
                "selected_resume_id": job.get("workbench_resume_id"),
                "available_resumes": api_module._workbench_service._available_resumes(
                    user["user_id"]
                ),
                "content_ref": None,
            },
            gap={
                "status": "blocked"
                if not job.get("workbench_resume_id")
                else "queued",
                "score": None,
                "gap_report": None,
                "cache_hit": False,
                "error": None,
            },
            crawl={
                "crawl_id": None,
                "status": "idle",
                "stage": "",
                "error": None,
            },
        )
    state = api_module._workbench_service.public_state(session)
    if request.headers.get("If-None-Match") == state["meta"]["etag"]:
        return Response(status_code=304)
    return state


@router.post(
    "/api/workbench/session/{session_id}/analyze",
    response_model=WorkstationState,
)
def analyze_workbench_session(
    session_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Run JD profiling/gap analysis for a library-job workstation session.

    The first call queues the pipeline; subsequent calls return the current
    state without spawning another worker.
    """
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    session = _session_or_404(session_id, user)
    jd = session.get("jd") or {}
    if jd.get("profile") is not None:
        return api_module._workbench_service.public_state(session)
    if jd.get("status") in ("queued", "running"):
        return api_module._workbench_service.public_state(session)
    job = session.get("job") or {}
    if not (job.get("jd_text") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="This job has no JD text to analyze",
        )
    api_module._session_store.update(
        session_id,
        {
            "jd": {"profile": None, "status": "queued", "error": None},
            "gap": {
                "status": "queued",
                "score": None,
                "gap_report": None,
                "cache_hit": False,
                "error": None,
            },
        },
    )
    threading.Thread(
        target=api_module._workbench_service._run_session_pipeline,
        args=(session_id,),
        daemon=True,
    ).start()
    return api_module._workbench_service.public_state(
        api_module._session_store.get(session_id)
    )


@router.get("/api/workbench/session/{session_id}/events")
async def stream_workbench_events(
    session_id: str,
    replay: bool = False,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Stream workstation events as Server-Sent Events with history replay."""
    session = _session_or_404(session_id, user)
    if replay:
        history = list(session["events"])

        async def replay_events():
            for item in history:
                payload = json.dumps(item.get("data", {}), ensure_ascii=False)
                yield (
                    f"id: {item.get('seq', 0)}\n"
                    f"event: {item.get('event', 'message')}\n"
                    f"data: {payload}\n\n"
                )

        return StreamingResponse(
            replay_events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    cursor = api_module._session_store.events_cursor(
        session_id, tenant_id=user["user_id"]
    )
    if cursor is None:
        raise HTTPException(status_code=404, detail="Workstation session not found")

    async def generate():
        try:
            while True:
                item = await asyncio.to_thread(cursor.next_item, 15.0)
                if item is None:
                    break
                payload = json.dumps(item.get("data", {}), ensure_ascii=False)
                yield (
                    f"id: {item.get('seq', 0)}\n"
                    f"event: {item.get('event', 'message')}\n"
                    f"data: {payload}\n\n"
                )
        finally:
            cursor.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
