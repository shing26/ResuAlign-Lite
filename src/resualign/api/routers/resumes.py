
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ...app.context import context
from ...store_base import resolve_upload_dir
from ..deps import get_current_user
from ..schemas import (
    MasterResumeCreateRequest,
    MasterResumeRollbackRequest,
    MasterResumeUpdateRequest,
    ResumeProfileEditRequest,
)

router = APIRouter()

@router.post('/api/master-resumes', status_code=201)
def create_master_resume(req: MasterResumeCreateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Create a master resume with its first version."""
    try:
        return context._resumes.create_master_resume(user['user_id'], req.title, req.content)
    except context.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post('/api/master-resumes/parse')
async def parse_resume_upload(file: UploadFile=File(...), user: dict[str, Any]=Depends(get_current_user)):
    """Parse an uploaded resume file and return prefilled title/content."""
    filename = (file.filename or '').strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in context.SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=415, detail='Unsupported format. Supported: ' + ', '.join(sorted(context.SUPPORTED_EXTENSIONS)))
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail='Uploaded file is empty')
    if len(raw) > context._MAX_RESUME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f'File exceeds {context._MAX_RESUME_UPLOAD_BYTES // (1024 * 1024)}MB')
    # Keep the original upload under <DataDir>/uploads/ so backups and
    # restores can cover it; parsing still happens on a temp copy.
    upload_dir = resolve_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or f'resume{suffix}'
    stored_path = upload_dir / f'{int(time.time())}-{safe_name}'
    stored_path.write_bytes(raw)
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / f'resume{suffix}'
            path.write_bytes(raw)
            text = context.extract_text(path)
    except context.FileParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    text = text.strip()
    if not text:
        raise HTTPException(status_code=422, detail='No readable text found in the uploaded file')
    return {
        'filename': filename,
        'title': context._derive_title(text),
        'content': text,
        'sections': context.structured_resume_sections(text),
        'size': len(raw),
        'stored_upload': str(stored_path),
    }

@router.get('/api/master-resumes')
def list_master_resumes(user: dict[str, Any]=Depends(get_current_user)):
    """Return the current user's master resumes."""
    return context._resumes.list_master_resumes(user['user_id'])

@router.get('/api/master-resumes/{resume_id}')
def get_master_resume(resume_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return one master resume, dropping dangling diagnosis job references."""
    resume = context._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    job_id = resume.get('latest_diagnosis_job_id')
    if job_id and context._registry.snapshot(job_id, tenant_id=user['user_id']) is None:
        cleared = context._resumes.clear_latest_diagnosis_job(
            user['user_id'], resume_id
        )
        if cleared is not None:
            resume = cleared
    return resume

@router.post('/api/master-resumes/{resume_id}/diagnose', status_code=202)
def diagnose_master_resume(resume_id: str, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue an independent no-JD diagnosis for one master resume."""
    context._enforce_rate_limit(request, context._analyze_rate_limiter)
    # P1-1：_queue_job 内部会原子预留每日 cap 名额，这里只做非预留预检。
    context.check_daily_llm_cap(user['user_id'])
    resume = context._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    if not (resume.get('content') or '').strip():
        raise HTTPException(status_code=422, detail='Resume content is empty; edit it before diagnosing')
    payload = {'resume_text': resume['content'], 'jd_text': None, 'run_eval': False, 'diagnosis': True, 'master_resume_id': resume_id}
    job_id = context._queue_job(user, payload)
    context._resumes.set_latest_diagnosis_job(user['user_id'], resume_id, job_id)
    return {'job_id': job_id, 'status': 'queued'}

@router.post('/api/master-resumes/{resume_id}/profile/extract')
def extract_resume_profile_endpoint(
    resume_id: str, user: dict[str, Any] = Depends(get_current_user)
):
    """LLM-extract the structured profile (网申回填数据源）。

    与 diagnosis 不同：这是同步调用（单次结构化抽取），任务小且前端
    需要立即拿到结果渲染档案面板。
    """
    context.enforce_daily_llm_cap(user['user_id'])
    return context.extract_resume_profile(user, resume_id)


@router.get('/api/master-resumes/{resume_id}/profile')
def get_resume_profile(
    resume_id: str, user: dict[str, Any] = Depends(get_current_user)
):
    """Return the stored structured profile plus staleness flag."""
    resume = context._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    profile = resume.get('profile')
    return {
        'profile': profile,
        'resume_updated_at': resume.get('updated_at'),
    }


@router.patch('/api/master-resumes/{resume_id}/profile')
def edit_resume_profile(
    resume_id: str,
    req: ResumeProfileEditRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Manually edit the structured profile (model 标 manual-edit）。"""
    resume = context._resumes.get_master_resume(user['user_id'], resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    import hashlib as _hashlib

    content = resume.get('content') or ''
    saved = context._resumes.save_resume_profile(
        user['user_id'],
        resume_id,
        req.profile.model_dump(),
        # 手动编辑基于当前内容：保持与内容的绑定关系（sha 照内容算），
        # 内容未变则不 stale，变了照常提示重抽。
        _hashlib.sha256(content.strip().encode('utf-8')).hexdigest(),
        'manual-edit',
    )
    if saved is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    return {'profile': saved['profile']}


@router.patch('/api/master-resumes/{resume_id}')
def update_master_resume(resume_id: str, req: MasterResumeUpdateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Append a new version to a master resume."""
    try:
        resume = context._resumes.update_master_resume(user['user_id'], resume_id, req.content)
    except context.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    return resume

@router.post('/api/master-resumes/{resume_id}/rollback')
def rollback_master_resume(resume_id: str, req: MasterResumeRollbackRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Point a master resume back at an existing version."""
    resume = context._resumes.rollback_master_resume(user['user_id'], resume_id, req.version)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    return resume

@router.delete('/api/master-resumes/{resume_id}', status_code=204)
def delete_master_resume(resume_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Delete a master resume and its version history."""
    if not context._resumes.delete_master_resume(user['user_id'], resume_id):
        raise HTTPException(status_code=404, detail='Master resume not found')
    return None

