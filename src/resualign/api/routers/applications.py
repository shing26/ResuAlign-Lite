
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

import resualign.api as api_module

from ..deps import get_current_user
from ..schemas import ApplicationCreateRequest, ApplicationUpdateRequest

router = APIRouter()

@router.post('/api/applications', status_code=201)
def create_application(req: ApplicationCreateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Create an application pinned to the master resume's current version.

    Deprecated: application records are being replaced by the Job Library
    entity (per-job workbench runs, status, and timeline fields). The
    endpoint stays available for existing callers; migrate historical
    records with ``merge_applications_into_jobs`` before retiring it.
    """
    try:
        return api_module._applications.create_application(tenant_id=user['user_id'], title=req.title, master_resume_id=req.master_resume_id, jd_text=req.jd_text, jd_url=req.jd_url)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get('/api/applications')
def list_applications(user: dict[str, Any]=Depends(get_current_user)):
    """Return the current user's applications."""
    return api_module._applications.list_applications(user['user_id'])

@router.get('/api/applications/{application_id}')
def get_application(application_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return one application and its pinned resume snapshot."""
    application = api_module._applications.get_application(user['user_id'], application_id)
    if application is None:
        raise HTTPException(status_code=404, detail='Application not found')
    return application

@router.patch('/api/applications/{application_id}')
def update_application(application_id: str, req: ApplicationUpdateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Update application metadata without changing its resume snapshot.

    Deprecated: application records are being replaced by the Job Library
    entity. Kept available for existing callers; the frontend no longer
    surfaces this form.
    """
    try:
        application = api_module._applications.update_application(user['user_id'], application_id, title=req.title, jd_text=req.jd_text, jd_url=req.jd_url, status=req.status)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if application is None:
        raise HTTPException(status_code=404, detail='Application not found')
    return application

@router.delete('/api/applications/{application_id}', status_code=204)
def delete_application(application_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Delete an application record.

    Deprecated: application records are being replaced by the Job Library
    entity. Kept available for existing callers.
    """
    if not api_module._applications.delete_application(user['user_id'], application_id):
        raise HTTPException(status_code=404, detail='Application not found')
    return None

@router.post('/api/applications/{application_id}/run', status_code=202)
def run_application(application_id: str, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue an analysis using the application's pinned resume and JD."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    application = api_module._applications.get_application(user['user_id'], application_id)
    if application is None:
        raise HTTPException(status_code=404, detail='Application not found')
    if not api_module.build_config().api_key:
        raise HTTPException(status_code=503, detail='API key not configured. Set via .env file or environment variables.')
    payload = {'resume_text': application['resume_snapshot'], 'jd_text': application['jd_text'], 'jd_url': application['jd_url'], 'run_eval': False}
    job_id = api_module._queue_job(user, payload, application_id=application_id)
    return {'job_id': job_id, 'status': 'queued'}

