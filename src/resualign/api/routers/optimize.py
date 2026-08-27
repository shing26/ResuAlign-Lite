from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import OptimizeApplyRequest, OptimizeRequest

router = APIRouter()


@router.post('/api/master-resumes/{resume_id}/optimize', status_code=202)
def optimize_master_resume(
    resume_id: str,
    req: OptimizeRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue the xzjobs-style resume optimization: local overall analysis
    followed by per-module (project experience) LLM polish."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    api_module.enforce_daily_llm_cap(user['user_id'])
    resume = api_module._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    if not (resume.get('content') or '').strip():
        raise HTTPException(status_code=422, detail='Resume content is empty; edit it before optimizing')
    if not api_module.build_config().is_llm_configured:
        raise HTTPException(status_code=503, detail='LLM 未配置。请设置 API Key（远程供应商）或激活 Ollama 本地节点。')
    payload = {
        'optimize_resume': True,
        'resume_text': resume['content'],
        'jd_text': req.jd_text,
        'master_resume_id': resume_id,
    }
    job_id = api_module._queue_job(user, payload)
    return {'job_id': job_id, 'status': 'queued'}


@router.post('/api/master-resumes/{resume_id}/optimize/apply')
def apply_resume_optimize(
    resume_id: str,
    req: OptimizeApplyRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Apply accepted optimized modules onto the resume as a new version."""
    try:
        return api_module.apply_resume_optimize_items(
            user['user_id'],
            resume_id,
            [item.model_dump() for item in req.items],
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc