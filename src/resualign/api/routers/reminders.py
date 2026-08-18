"""Follow-up reminder endpoints for the personal workbench."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import ReminderItem, ReminderListResponse

router = APIRouter()


@router.get("/api/reminders", response_model=ReminderListResponse)
def list_reminders(
    scope: str = "today",
    user: dict[str, Any] = Depends(get_current_user),
) -> ReminderListResponse:
    """Return the tenant's today/overdue follow-up list."""
    if scope != "today":
        raise HTTPException(
            status_code=422,
            detail="Unsupported reminder scope; expected 'today'",
        )
    items = api_module._jobs.list_reminders(user["user_id"], scope=scope)
    return ReminderListResponse(items=[ReminderItem(**item) for item in items])
