"""Kanban board bulk operations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import (
    KanbanBulkStatusRequest,
    KanbanBulkStatusResponse,
)

router = APIRouter()

_MAX_BULK_ROWS = 200


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
