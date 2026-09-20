"""Batch alignment endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ...app.context import context
from ...batch import BatchAlignRequest
from ..deps import get_current_user

router = APIRouter()


@router.post('/api/batch-align', status_code=202)
def create_batch_align(
    req: BatchAlignRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue one workbench alignment per library job in a tenant batch."""
    context._enforce_rate_limit(request, context._analyze_rate_limiter)
    context.check_daily_llm_cap(user['user_id'])
    return context._queue_batch_align(user, req)


@router.get('/api/batch-align/{batch_id}')
def get_batch_align_status(
    batch_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return per-row status/results plus an overall batch summary."""
    batch = context._get_batch_align(batch_id, user['user_id'])
    if batch is None:
        raise HTTPException(status_code=404, detail='Batch not found')
    return batch


@router.post('/api/batch-align/{batch_id}/cancel')
def cancel_batch_align(
    batch_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Cancel rows that are still queued; running rows are not interrupted."""
    result = context._cancel_batch_align(batch_id, user['user_id'])
    if result is None:
        raise HTTPException(status_code=404, detail='Batch not found')
    return result
