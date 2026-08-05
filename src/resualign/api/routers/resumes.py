
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..deps import get_current_user
from ..schemas import (
    MasterResumeCreateRequest,
    MasterResumeRollbackRequest,
    MasterResumeUpdateRequest,
)

import resualign.api as api_module

router = APIRouter()

@router.post('/api/master-resumes', status_code=201)
def create_master_resume(req: MasterResumeCreateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Create a master resume with its first version."""
    try:
        return api_module._resumes.create_master_resume(user['user_id'], req.title, req.content)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post('/api/master-resumes/parse')
async def parse_resume_upload(file: UploadFile=File(...), user: dict[str, Any]=Depends(get_current_user)):
    """Parse an uploaded resume file and return prefilled title/content."""
    filename = (file.filename or '').strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in api_module.SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail='Unsupported format. Supported: ' + ', '.join(sorted(api_module.SUPPORTED_EXTENSIONS)))
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail='Uploaded file is empty')
    if len(raw) > api_module._MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f'File exceeds {api_module._MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB')
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / f'resume{suffix}'
            path.write_bytes(raw)
            text = api_module.extract_text(path)
    except api_module.FileParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail='No readable text found in the uploaded file')
    return {
        'filename': filename,
        'title': api_module._derive_title(text),
        'content': text,
        'sections': api_module.structured_resume_sections(text),
        'size': len(raw),
    }

@router.get('/api/master-resumes')
def list_master_resumes(user: dict[str, Any]=Depends(get_current_user)):
    """Return the current user's master resumes."""
    return api_module._resumes.list_master_resumes(user['user_id'])

@router.get('/api/master-resumes/{resume_id}')
def get_master_resume(resume_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return one master resume with its full version history."""
    resume = api_module._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    return resume

@router.post('/api/master-resumes/{resume_id}/diagnose', status_code=202)
def diagnose_master_resume(resume_id: str, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue an independent no-JD diagnosis for one master resume."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    resume = api_module._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    if not (resume.get('content') or '').strip():
        raise HTTPException(status_code=422, detail='Resume content is empty; edit it before diagnosing')
    if not api_module.build_config().api_key:
        raise HTTPException(status_code=503, detail='API key not configured. Set via .env file or environment variables.')
    payload = {'resume_text': resume['content'], 'jd_text': None, 'run_eval': False, 'diagnosis': True, 'master_resume_id': resume_id}
    job_id = api_module._queue_job(user, payload)
    api_module._resumes.set_latest_diagnosis_job(user['user_id'], resume_id, job_id)
    return {'job_id': job_id, 'status': 'queued'}

@router.patch('/api/master-resumes/{resume_id}')
def update_master_resume(resume_id: str, req: MasterResumeUpdateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Append a new version to a master resume."""
    try:
        resume = api_module._resumes.update_master_resume(user['user_id'], resume_id, req.content)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    return resume

@router.post('/api/master-resumes/{resume_id}/rollback')
def rollback_master_resume(resume_id: str, req: MasterResumeRollbackRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Point a master resume back at an existing version."""
    resume = api_module._resumes.rollback_master_resume(user['user_id'], resume_id, req.version)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    return resume

@router.delete('/api/master-resumes/{resume_id}', status_code=204)
def delete_master_resume(resume_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Delete a master resume and its version history."""
    if not api_module._resumes.delete_master_resume(user['user_id'], resume_id):
        raise HTTPException(status_code=404, detail='Master resume not found')
    return None

