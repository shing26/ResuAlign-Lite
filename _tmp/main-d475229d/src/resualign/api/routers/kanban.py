"""Kanban board bulk operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ...reminders import AUTO_FOLLOWUP_MESSAGE, auto_followup_due_at
from ..deps import get_current_user
from ..schemas import (
    KanbanBulkStatusRequest,
    KanbanBulkStatusResponse,
)

router = APIRouter()

_MAX_BULK_ROWS = 200


def _apply_bulk_auto_followups(
    tenant_id: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill the default 3-day follow-up for newly applied jobs."""
    settings = api_module._settings_store.get_settings(tenant_id).get(
        "reminder"
    ) or {}
    if not settings.get("auto_followup_reminder", True):
        return results
    for item in results:
        if not item["updated"] or item["status"] != "updated":
            continue
        job = item.get("job") or {}
        if (
            job.get("status_canonical") != "applied"
            or job.get("next_step_due_at")
        ):
            continue
        updated = api_module._jobs.update_job(
            tenant_id,
            job["job_id"],
            next_step=AUTO_FOLLOWUP_MESSAGE,
            next_step_due_at=auto_followup_due_at(job.get("applied_at")),
        )
        if updated is not None:
            item["job"] = updated
    return results


@router.post(
    "/api/kanban/bulk-status",
    response_model=KanbanBulkStatusResponse,
)
def bulk_update_kanban_status(
    req: KanbanBulkStatusRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Update many kanban job statuses in one transaction.

    ``expected_status`` acts as an optimistic lock. Replaying the same
    ``idempotency_key`` returns the original result without re-applying.
    """
    job_ids = list(dict.fromkeys(req.job_ids))
    if not job_ids:
        raise HTTPException(
            status_code=422, detail="At least one job_id is required"
        )
    if len(job_ids) > _MAX_BULK_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"Bulk update exceeds maximum of {_MAX_BULK_ROWS} rows",
        )
    try:
        api_module._jobs.validate_status(req.status)
        if req.expected_status is not None:
            api_module._jobs.validate_status(req.expected_status)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if req.idempotency_key:
        cached = api_module._jobs.get_bulk_status_op(
            user["user_id"], req.idempotency_key
        )
        if cached is not None:
            return KanbanBulkStatusResponse(**cached["result"])

    results = api_module._jobs.bulk_update_status(
        user["user_id"],
        job_ids,
        req.status,
        expected_status=req.expected_status,
    )
    results = _apply_bulk_auto_followups(user["user_id"], results)
    response = KanbanBulkStatusResponse(
        idempotency_key=req.idempotency_key,
        updated=sum(1 for item in results if item["updated"]),
        total=len(job_ids),
        results=results,
    )
    if req.idempotency_key:
        api_module._jobs.save_bulk_status_op(
            user["user_id"],
            req.idempotency_key,
            {"job_ids": job_ids, "status": req.status, "expected_status": req.expected_status},
            response.model_dump(),
        )
    return response
