"""Blocker queue endpoints for the Sprint 3 fetch pipeline."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import BlockerResolveRequest

router = APIRouter()


@router.get("/api/blockers")
def list_blockers(
    status: str | None = None,
    user: dict[str, Any] = Depends(get_current_user),
):
    """List the tenant's blocker queue, optionally filtered by status.

    status 参数缺省时返回全部状态（含 pending/ignored/resolved）；统计与展示请显式传 status=pending。
    """
    try:
        return api_module._fetcher.list_blockers(
            user["user_id"], status=status
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/blockers/{blocker_id}/ignore")
def ignore_blocker(
    blocker_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Mark a pending blocker ignored so it leaves the pending queue."""
    blocker = api_module._fetcher.ignore_blocker(
        user["user_id"], blocker_id
    )
    if blocker is None:
        raise HTTPException(status_code=404, detail="Blocker not found")
    return blocker


@router.post("/api/blockers/{blocker_id}/resolve")
def resolve_blocker(
    blocker_id: str,
    req: BlockerResolveRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Create a library job from pasted text and resolve the blocker.

    Returns ``{"blocker": ..., "job": ...}``. When the text cannot be
    turned into a job the blocker stays pending and the caller receives a
    4xx so the frontend can keep it in the queue.
    """
    try:
        result = api_module._fetcher.resolve_blocker_with_text(
            user["user_id"], blocker_id, req.manual_text
        )
    except api_module.UserStoreError as exc:
        if "Duplicate job" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Blocker not found")
    return result
