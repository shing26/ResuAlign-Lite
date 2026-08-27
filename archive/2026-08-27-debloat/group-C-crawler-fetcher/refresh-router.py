"""Job refresh endpoints: re-crawl an existing URL job in place."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import JobRefreshAllResponse, JobRefreshResponse

router = APIRouter()


@router.post(
    "/api/jobs/{job_id}/refresh",
    response_model=JobRefreshResponse,
)
def refresh_library_job(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> JobRefreshResponse:
    """Queue and run one in-place refresh for an existing URL job."""
    queued = api_module._refresh_service.queue_refresh(
        user["user_id"],
        job_id,
    )
    if queued is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result = api_module._refresh_service.run_refresh(
        user["user_id"],
        job_id,
        queued["crawl_id"],
    )
    return JobRefreshResponse(
        queued=queued["queued"],
        job_id=job_id,
        crawl_id=result.get("crawl_id"),
        status=result.get("status"),
        changed=result.get("changed"),
        changed_fields=result.get("changed_fields") or [],
        error=result.get("error"),
        job=result.get("job"),
    )


@router.post(
    "/api/jobs/refresh-all",
    response_model=JobRefreshAllResponse,
)
def refresh_all_library_jobs(
    user: dict[str, Any] = Depends(get_current_user),
) -> JobRefreshAllResponse:
    """Queue and run refresh for every eligible URL-sourced job."""
    tenant_id = user["user_id"]
    queued_items = api_module._refresh_service.queue_refresh_all(tenant_id)
    items: list[JobRefreshResponse] = []
    for queued in queued_items:
        if queued.get("error"):
            items.append(JobRefreshResponse(**queued))
            continue
        result = api_module._refresh_service.run_refresh(
            tenant_id,
            queued["job_id"],
            queued["crawl_id"],
        )
        items.append(
            JobRefreshResponse(
                queued=queued["queued"],
                job_id=queued["job_id"],
                crawl_id=result.get("crawl_id"),
                title=queued.get("title"),
                status=result.get("status"),
                changed=result.get("changed"),
                changed_fields=result.get("changed_fields") or [],
                error=result.get("error"),
                job=result.get("job"),
            )
        )
    return JobRefreshAllResponse(items=items)
