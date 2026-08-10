"""Fetch pipeline endpoint: submit a JD URL for crawl + library build."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import FetchUrlRequest

router = APIRouter()


@router.post("/api/jobs/fetch-url")
def fetch_url(
    req: FetchUrlRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Submit one JD URL to the fetch pipeline (sync crawl + build).

    Response ``status`` is one of ``created`` / ``duplicate`` /
    ``blocked`` / ``rule_rejected``; ``job_id`` accompanies ``created`` and
    ``duplicate``, ``blocker_id`` accompanies ``blocked`` and
    ``rule_rejected``.
    """
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    try:
        return api_module._fetcher.submit_url(user["user_id"], req.url)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
