
from typing import Any

from fastapi import APIRouter, Depends, Request

from ...app.context import context
from ..deps import get_current_user
from ..schemas import AnalyzeRequest

router = APIRouter()

@router.post('/api/analyze', status_code=202)
def analyze(req: AnalyzeRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue a full ResuAlign pipeline run and return immediately."""
    context._enforce_rate_limit(request, context._analyze_rate_limiter)
    context.check_daily_llm_cap(user['user_id'])
    job_id = context._queue_job(user, req.model_dump())
    return {'job_id': job_id, 'status': 'queued'}

