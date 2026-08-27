
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

import resualign.api as api_module

from ...llm_usage import llm_tenant_context
from ...role_router import call_with_role
from ..deps import get_current_user, get_local_ingest_user
from ..schemas import (
    BulkStatusRequest,
    FinalDraftRequest,
    JDParseRequest,
    JobCreateRequest,
    JobExportRequest,
    JobExportResponse,
    JobImportRequest,
    JobPreanalyzeResponse,
    JobUpdateRequest,
    LocalIngestRequest,
    MatchScoreResponse,
    WorkbenchAcceptRequest,
    WorkbenchRewriteRequest,
    WorkbenchRewriteResponse,
    WorkbenchRunRequest,
)
from ..services.jobs import build_job_export

logger = logging.getLogger(__name__)
router = APIRouter()


def _match_inputs(user_id: str, job: dict[str, Any]) -> tuple[str, str | None]:
    """Return the pinned master resume text and id for match scoring."""
    resume_id = job.get("workbench_resume_id")
    if not resume_id:
        return "", None
    resume = api_module._resumes.get_master_resume(user_id, resume_id)
    return (resume["content"] if resume else ""), resume_id


def _match_stale(user_id: str, job: dict[str, Any]) -> bool:
    """Return whether a job's match score no longer reflects its inputs."""
    if not job.get("match_updated_at"):
        return True
    resume_text, resume_id = _match_inputs(user_id, job)
    return not api_module.snapshot_matches(
        job.get("match_score_detail"),
        job.get("jd_text"),
        resume_text,
        resume_id,
    )


def _match_reason_source(job: dict[str, Any]) -> str | None:
    reason = job.get("match_reason") or ""
    if reason.startswith("基于规则评分："):
        return "fallback"
    return "llm" if reason else None


def _llm_match_reason(
    job: dict[str, Any],
    detail: dict[str, Any],
    resume_text: str,
) -> str | None:
    """Generate a one-sentence recommendation, returning None on failure."""
    try:
        config = api_module.build_config()
        if not config.is_llm_configured:
            return None
        system = (
            "你是一名求职匹配顾问。根据给定的岗位、主简历和四维匹配分，"
            "只输出一句中文推荐理由，说明建议投递或不投递的核心原因，"
            "不输出 Markdown，不超过 80 字。"
        )
        user = (
            f"岗位：{job.get('title') or ''}\n"
            f"JD：{(job.get('jd_text') or '')[:2000]}\n"
            f"简历：{(resume_text or '')[:2000]}\n"
            f"四维分：{detail}"
        )
        with api_module.OpenAIClient(config, timeout=30.0) as client:
            result = client.chat_json(system, user)
        if isinstance(result, str):
            return result.strip() or None
        if isinstance(result, dict):
            reason = result.get("reason") or result.get("text") or ""
            return str(reason).strip() or None
    except Exception:
        logger.exception("LLM match reason failed for job %s", job.get("job_id"))
    return None


@router.post('/api/jobs', status_code=201)
def create_library_job(req: JobCreateRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Ingest one job from pasted text or a JD URL."""
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    api_module.enforce_daily_llm_cap(user['user_id'])
    if not (req.jd_text or '').strip() and (not (req.jd_url or '').strip()):
        raise HTTPException(status_code=422, detail='Either jd_text or jd_url is required')
    try:
        with llm_tenant_context(user['user_id']):
            return api_module._create_job_from_source(user, {'title': req.title, 'jd_text': req.jd_text, 'jd_url': req.jd_url, 'company': req.company, 'location': req.location, 'salary_min': req.salary_min, 'salary_max': req.salary_max, 'salary_currency': req.salary_currency, 'source_type': req.source_type, 'source_url': req.source_url, 'job_function': req.job_function, 'seniority': req.seniority, 'tech_tags': req.tech_tags, 'status': req.status, 'posting_date': req.posting_date})
    except api_module.UserStoreError as exc:
        if 'Duplicate job' in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post('/api/jobs/parse-jd')
def parse_jd_preview(req: JDParseRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Preview a JD URL.

    De-bloat (2026-08-27): backend crawling is retired; JD intake goes
    through the collector userscript (local-ingest) or pasted text. URL-only
    previews are rejected with a pointer to those flows.
    """
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    jd_url = req.jd_url.strip()
    if not jd_url:
        raise HTTPException(status_code=422, detail='jd_url is required')
    raise HTTPException(
        status_code=422,
        detail=(
            '后端已不再抓取 JD 链接：请用浏览器油猴插件一键抓取岗位，'
            '或改用「粘贴 JD」方式'
        ),
    )


@router.post('/api/jobs/local-ingest')
def local_ingest(
    req: LocalIngestRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_local_ingest_user),
):
    """Ingest a job from the collector userscript without LLM classification."""
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    if not (req.jd_text or '').strip():
        raise HTTPException(status_code=422, detail='jd_text is required')
    try:
        return api_module._local_ingest_job(
            user,
            {
                'title': req.title,
                'company': req.company,
                'location': req.location,
                'salary_text': req.salary_text,
                'job_page_url': req.job_page_url,
                'jd_text': req.jd_text,
                'site': req.site,
            },
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post('/api/jobs/import')
def import_library_jobs(req: JobImportRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue a batch import so crawl/classification never blocks the API."""
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    api_module.enforce_daily_llm_cap(user['user_id'])
    rows = api_module._collect_import_rows(req)
    if not rows:
        return {'queued': False, 'total': 0, 'created': 0, 'skipped': 0}
    if len(rows) > api_module._MAX_IMPORT_ROWS:
        raise HTTPException(status_code=422, detail=f'Import exceeds maximum of {api_module._MAX_IMPORT_ROWS} rows')
    import_id = uuid.uuid4().hex
    api_module._import_batches[import_id] = {'user_id': user['user_id'], 'rows': rows, 'created': 0, 'skipped': 0, 'errors': [], 'done': False}
    threading.Thread(target=api_module._run_import, args=(import_id,), daemon=True).start()
    return {'queued': True, 'import_id': import_id, 'total': len(rows), 'created': 0, 'skipped': 0, 'errors': []}

@router.get('/api/jobs/import/{import_id}')
def import_status(import_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return the progress of a queued import batch."""
    batch = api_module._import_batches.get(import_id)
    if batch is None or batch['user_id'] != user['user_id']:
        raise HTTPException(status_code=404, detail='Import batch not found')
    return {'queued': not batch['done'], 'total': len(batch['rows']), 'created': batch['created'], 'skipped': batch['skipped'], 'errors': batch['errors']}

@router.get('/api/jobs')
def list_library_jobs(job_function: str | None=None, seniority: str | None=None, status: str | None=None, search: str | None=None, limit: int=100, offset: int=0, sort: str="updated_at_desc", user: dict[str, Any]=Depends(get_current_user)):
    """List library jobs with optional filters."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    try:
        jobs = api_module._jobs.list_jobs(
            user['user_id'],
            job_function=job_function,
            seniority=seniority,
            status=status,
            search=search,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for job in jobs:
        job["match_stale"] = _match_stale(user['user_id'], job)
    return jobs

@router.get('/api/jobs/{job_id}')
def get_library_job(job_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return one library job, falling back to an analysis job snapshot."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is not None:
        job["match_stale"] = _match_stale(user['user_id'], job)
        return job
    return api_module.job_status(job_id, user)


@router.get('/api/jobs/{job_id}/snapshots')
def list_application_snapshots(
    job_id: str, user: dict[str, Any] = Depends(get_current_user)
):
    """Return a job's immutable applied-draft snapshots, newest first."""
    return api_module._jobs.list_application_snapshots(
        user['user_id'], job_id
    )


@router.get('/api/jobs/{job_id}/analysis-status')
def get_analysis_status(
    job_id: str, user: dict[str, Any]=Depends(get_current_user)
):
    """Return an analysis job snapshot, treating a missing job as expired."""
    snapshot = api_module._registry.snapshot(
        job_id, tenant_id=user['user_id']
    )
    if snapshot is None:
        return {'job_id': job_id, 'status': 'expired'}
    return snapshot

@router.post('/api/jobs/{job_id}/cancel')
def cancel_analysis_job(job_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Cancel a queued analysis job; running jobs cannot be interrupted."""
    job = api_module._registry.get(job_id, tenant_id=user['user_id'])
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if not api_module._registry.cancel(job_id):
        raise HTTPException(status_code=409, detail='Only queued jobs can be canceled')
    stored = api_module._registry.get_payload(job_id)
    if stored and stored[2]:
        api_module._applications.set_application_job(user['user_id'], stored[2], job_id, 'draft')
    return {'job_id': job_id, 'status': 'canceled'}

@router.post('/api/jobs/{job_id}/reclassify')
def reclassify_library_job(job_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Rerun LLM classification and clear the pending flag on success."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    jd_text = (job.get('jd_text') or '').strip()
    if not jd_text:
        raise HTTPException(status_code=422, detail='Job description text is required')
    job_functions, seniorities = api_module._settings_vocabulary(user['user_id'])
    api_module.enforce_daily_llm_cap(user['user_id'])
    with llm_tenant_context(user['user_id']):
        try:
            classification = api_module._classify_job(
                jd_text, job_functions, seniorities, tenant=user['user_id']
            )
        except api_module.LLMResponseError as exc:
            logger.warning('Reclassification failed for job %s: %s', job_id, exc)
            raise HTTPException(status_code=502, detail='自动分类暂时不可用，岗位已保留为分类待定，可稍后重试') from exc
    try:
        updated = api_module._jobs.update_job(user['user_id'], job_id, job_function=classification.get('job_function'), seniority=classification.get('seniority'), tech_tags=classification.get('tech_tags') or [], classification_pending=0, allowed_job_functions=job_functions, allowed_seniorities=seniorities)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return updated

@router.post('/api/jobs/{job_id}/final-draft')
def save_final_draft(job_id: str, req: FinalDraftRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Persist a job-specific final draft and return its new version."""
    try:
        saved = api_module._jobs.save_final_draft(
            user['user_id'],
            job_id,
            req.draft,
            accepted_diff_ids=req.accepted_diff_ids,
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return saved


@router.post(
    '/api/jobs/{job_id}/exports',
    response_model=JobExportResponse,
)
def export_final_draft(
    job_id: str,
    req: JobExportRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> JobExportResponse:
    """Export a persisted final draft as Markdown, JSON, or print HTML."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    if not (job.get('final_draft') or '').strip():
        raise HTTPException(
            status_code=422,
            detail='尚未保存定稿，请先在工作台保存定稿后再导出',
        )
    payload = build_job_export(job, req.format)
    return JobExportResponse(**payload)

@router.patch('/api/jobs/{job_id}')
async def update_library_job(job_id: str, req: JobUpdateRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Update editable job fields such as tags, salary, and status."""
    job_functions, seniorities = api_module._settings_vocabulary(user['user_id'])
    raw_timeline = await api_module._read_timeline_extras(request)
    # Explicit null and empty string both clear a timeline field (U10);
    # the store turns "" into a NULL write while None stays "unchanged".
    timeline = {
        key: ("" if value is None else value)
        for key, value in raw_timeline.items()
    }
    try:
        job = api_module._jobs.update_job(user['user_id'], job_id, title=req.title, jd_text=req.jd_text, company=req.company, location=req.location, salary_min=req.salary_min, salary_max=req.salary_max, salary_currency=req.salary_currency, source_type=req.source_type, source_url=req.source_url, job_function=req.job_function, seniority=req.seniority, tech_tags=req.tech_tags, status=req.status, posting_date=req.posting_date, applied_at=timeline.get('applied_at'), next_step=timeline.get('next_step'), notes=timeline.get('notes'), offer_at=timeline.get('offer_at'), rejected_at=timeline.get('rejected_at'), next_step_due_at=timeline.get('next_step_due_at'), interview_stage=timeline.get('interview_stage'), tailor_granularity=req.tailor_granularity, tailor_focus=req.tailor_focus, custom_prompt=req.custom_prompt, allowed_job_functions=job_functions, allowed_seniorities=seniorities)
    except api_module.UserStoreError as exc:
        if 'Duplicate job' in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return job

@router.post('/api/jobs/bulk-status', include_in_schema=False)
def bulk_update_job_status(req: BulkStatusRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Update status for many library jobs, returning per-id results.

    Deprecated: this hidden endpoint is superseded by the kanban bulk-status
    flow (``/api/kanban/bulk-status``) with optimistic locking and
    idempotency keys. It is kept for backward compatibility only and will be
    removed in a future release; new callers must use the kanban endpoint.
    """
    results: list[dict[str, Any]] = []
    updated = 0
    for job_id in req.job_ids:
        try:
            job = api_module._jobs.update_job(user['user_id'], job_id, status=req.status)
        except api_module.UserStoreError as exc:
            results.append({'job_id': job_id, 'updated': False, 'status': 'error', 'error': str(exc)})
            continue
        if job is None:
            results.append({'job_id': job_id, 'updated': False, 'status': 'not_found'})
        else:
            updated += 1
            results.append({'job_id': job_id, 'updated': True, 'status': 'updated', 'job': job})
    return {'updated': updated, 'total': len(req.job_ids), 'results': results}

@router.delete('/api/jobs/{job_id}', status_code=204)
def delete_library_job(job_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Delete a library job, its crawl tasks, and any pinned analysis job."""
    deleted, workbench_job_id = api_module._jobs.delete_job(
        user['user_id'], job_id
    )
    if not deleted:
        raise HTTPException(status_code=404, detail='Job not found')
    if workbench_job_id:
        api_module._registry.delete(workbench_job_id, tenant_id=user['user_id'])
    return None

@router.post('/api/jobs/{job_id}/workbench', status_code=202)
def run_workbench(job_id: str, req: WorkbenchRunRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue a per-job pipeline run pinned to a Master Resume version."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    api_module.enforce_daily_llm_cap(user['user_id'])
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    resume = api_module._resumes.get_master_resume(user['user_id'], req.master_resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    config = api_module.build_config()
    if not config.is_llm_configured:
        raise HTTPException(status_code=503, detail='LLM 未配置。请设置 API Key（远程供应商）或激活 Ollama 本地节点。')
    cached_diagnosis = api_module._cached_diagnosis(resume, config, user['user_id'])
    # F1: per-run Eval switch. Explicit True/False from the request wins;
    # None (not specified) falls back to the settings-page global default.
    run_eval = req.run_eval
    if run_eval is None:
        run_eval = api_module._settings_store.get_settings(
            user['user_id']
        ).get('eval_default', False)
    payload = {'resume_text': resume['content'], 'jd_text': job['jd_text'], 'jd_url': job.get('source_url'), 'run_eval': run_eval, 'granularity': req.granularity, 'prompt_focus': req.prompt_focus, 'custom_prompt': req.custom_prompt, 'master_resume_id': req.master_resume_id, 'library_job_id': job_id}
    if cached_diagnosis is not None:
        payload['precomputed_diagnosis'] = cached_diagnosis
    analysis_job_id = api_module._queue_job(user, payload, workbench=True)
    # 重跑时把 alignment_status 拉回 queued：否则上一轮的 succeeded 会残留，
    # 轮询方（前端/冒烟）会误判新任务已完成而读到旧的 diffs（2026-08-27 CI 复现）。
    api_module._jobs.update_job(user['user_id'], job_id, workbench_job_id=analysis_job_id, workbench_resume_id=req.master_resume_id, tailor_granularity=req.granularity, tailor_focus=req.prompt_focus, custom_prompt=req.custom_prompt, alignment_status='queued')
    return {'job_id': analysis_job_id, 'status': 'queued', 'workbench': True}

@router.post('/api/jobs/{job_id}/workbench/accept')
def accept_workbench_diffs(job_id: str, req: WorkbenchAcceptRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Apply accepted diff indices to the pinned resume and return a draft."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    analysis_job = api_module._registry.get(job.get('workbench_job_id') or '', tenant_id=user['user_id'])
    if analysis_job is None or analysis_job.status != 'succeeded':
        raise HTTPException(status_code=404, detail='Workbench job not found or not finished')
    result = analysis_job.result or {}
    diffs = result.get('diffs') or []
    pinned = api_module._resumes.get_master_resume(user['user_id'], job.get('workbench_resume_id') or '')
    if pinned is None:
        raise HTTPException(status_code=404, detail='Pinned master resume not found')
    base_text = pinned['content']
    draft, applied_count = api_module._apply_diffs(base_text, diffs, req.accepted_indices)
    return {'draft': draft, 'accepted_count': applied_count, 'total_diffs': len(diffs)}


def _preanalyze_cache_hit(
    user_id: str,
    config: Any,
    resume_text: str,
    jd_text: str,
) -> bool:
    """Return whether the preanalyze LLM product is already cached."""
    try:
        if (resume_text or '').strip():
            content = f"{resume_text}\n\n{jd_text}"
            from resualign.jd_analysis import JD_ANALYSIS_PROMPT_VERSION

            prompt_version = JD_ANALYSIS_PROMPT_VERSION
        else:
            content = jd_text
            from resualign.jd_profiler import JD_PROFILER_PROMPT_VERSION

            prompt_version = JD_PROFILER_PROMPT_VERSION
        cached = api_module._cache.get(
            user_id,
            config.model,
            prompt_version,
            content,
        )
        return cached is not None
    except Exception:
        return False


@router.post(
    '/api/jobs/{job_id}/preanalyze',
    response_model=JobPreanalyzeResponse,
)
def preanalyze_library_job(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Run classifier + JD profile/gap without tailoring; idempotent."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    jd_text = (job.get('jd_text') or '').strip()
    if not jd_text:
        raise HTTPException(status_code=422, detail='Job description text is required')
    classification = {
        'job_function': job.get('job_function'),
        'seniority': job.get('seniority'),
        'tech_tags': job.get('tech_tags') or [],
    }
    if job.get('jd_profile') and not job.get('classification_pending'):
        return JobPreanalyzeResponse(
            job_id=job_id,
            status='ready',
            jd_profile=job.get('jd_profile'),
            gap_report=job.get('gap_report'),
            match_score=job.get('match_score'),
            match_score_detail=job.get('match_score_detail'),
            match_reason=job.get('match_reason'),
            match_reason_source=_match_reason_source(job),
            match_updated_at=job.get('match_updated_at'),
            match_stale=_match_stale(user['user_id'], job),
            classification=classification,
            cache_hit=True,
        )

    job_functions, seniorities = api_module._settings_vocabulary(user['user_id'])
    api_module.enforce_daily_llm_cap(user['user_id'])
    with llm_tenant_context(user['user_id']):
        try:
            classification = api_module._classify_job(
                jd_text, job_functions, seniorities, tenant=user['user_id']
            )
        except api_module.LLMResponseError as exc:
            logger.warning('Preanalyze classification failed for %s: %s', job_id, exc)
            classification = {}

    resume = None
    if job.get('workbench_resume_id'):
        resume = api_module._resumes.get_master_resume(
            user['user_id'], job['workbench_resume_id']
        )
    resume_text = resume['content'] if resume else ''
    resume_id = resume['resume_id'] if resume else None
    config = api_module.build_config()
    if not config.is_llm_configured:
        raise HTTPException(
            status_code=503,
            detail='LLM 未配置。请设置 API Key（远程供应商）或激活 Ollama 本地节点。',
        )
    cache_hit = _preanalyze_cache_hit(
        user['user_id'], config, resume_text, jd_text
    )
    profile_dict = None
    gap_dict = None
    with llm_tenant_context(user['user_id']):
        with api_module.OpenAIClient(config, timeout=60.0) as client:
            if resume_text.strip():
                try:
                    profile, _ = call_with_role(
                        'profiler', api_module.profile_jd,
                        api_module._llm_nodes, user['user_id'],
                        fn_kwargs={
                            'jd_text': jd_text,
                            'cache': api_module._cache,
                            'tenant': user['user_id'],
                        },
                    )
                except Exception:
                    profile = api_module.profile_jd(
                        client,
                        jd_text,
                        cache=api_module._cache,
                        tenant=user['user_id'],
                    )
                profile_dict = api_module.jd_profile_to_dict(profile)
                import json as _json
                _profile_str = _json.dumps(profile_dict, ensure_ascii=False)
                try:
                    gap, _ = call_with_role(
                        'gap_analyzer', api_module.analyze_gaps,
                        api_module._llm_nodes, user['user_id'],
                        fn_kwargs={
                            'resume_text': resume_text,
                            'jd_profile_text': _profile_str,
                        },
                    )
                except Exception:
                    gap = api_module.analyze_gaps(
                        client,
                        resume_text,
                        _profile_str,
                    )
                gap_dict = asdict(gap)
            else:
                try:
                    profile, _ = call_with_role(
                        'profiler', api_module.profile_jd,
                        api_module._llm_nodes, user['user_id'],
                        fn_kwargs={
                            'jd_text': jd_text,
                            'cache': api_module._cache,
                            'tenant': user['user_id'],
                        },
                    )
                except Exception:
                    profile = api_module.proactive_jd_profile(
                        client,
                        jd_text,
                        cache=api_module._cache,
                        tenant=user['user_id'],
                    )
                profile_dict = api_module.jd_profile_to_dict(profile)
    match_score = api_module._gap_match_score(
        {'gap_report': gap_dict}
    ) if gap_dict else None
    match_detail = None
    match_reason = None
    if resume_id and profile_dict and gap_dict:
        match_detail = api_module.compute_match_score(
            jd_text,
            profile_dict,
            gap_dict,
            None,
            resume_text,
            resume_id,
        )
        match_reason = api_module.fallback_match_reason(
            match_detail,
            gap_dict.get("missing_keywords") or [],
        )
        match_score = match_detail["total"]

    updated = api_module._jobs.update_job(
        user['user_id'],
        job_id,
        job_function=classification.get('job_function'),
        seniority=classification.get('seniority'),
        tech_tags=classification.get('tech_tags') or [],
        classification_pending=0,
        jd_profile=profile_dict,
        gap_report=gap_dict,
        match_score=match_score,
        match_score_detail=match_detail,
        match_reason=match_reason,
        match_updated_at=time.time() if match_detail else None,
        allowed_job_functions=job_functions,
        allowed_seniorities=seniorities,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail='Job not found')

    session = api_module._session_store.find_by_job(job_id, user['user_id'])
    if session is not None:
        api_module._session_store.update(
            session['session_id'],
            {
                'status': 'ready',
                'job': updated,
                'jd': {'profile': profile_dict, 'status': 'ready', 'error': None},
                'gap': {
                    'status': 'ready' if gap_dict else 'blocked',
                    'score': match_score,
                    'gap_report': gap_dict,
                    'cache_hit': cache_hit,
                    'error': None,
                },
            },
        )
        api_module._session_store.emit(
            session['session_id'],
            'job.gap_ready',
            {
                'job_id': job_id,
                'jd_profile': profile_dict,
                'gap_report': gap_dict,
                'status': 'ready' if gap_dict else 'blocked',
                'cache_hit': cache_hit,
            },
        )
    return JobPreanalyzeResponse(
        job_id=job_id,
        status='ready',
        jd_profile=profile_dict,
        gap_report=gap_dict,
        match_score=match_score,
        match_score_detail=updated.get("match_score_detail"),
        match_reason=updated.get("match_reason"),
        match_reason_source=_match_reason_source(updated),
        match_updated_at=updated.get("match_updated_at"),
        match_stale=False,
        classification=classification,
        cache_hit=cache_hit,
    )


@router.post(
    '/api/jobs/{job_id}/match',
    response_model=MatchScoreResponse,
)
def recompute_job_match(
    job_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> MatchScoreResponse:
    """Recompute the four-dimension match score with a one-sentence reason."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    resume_text, resume_id = _match_inputs(user['user_id'], job)
    if (
        not resume_id
        or not job.get("jd_profile")
        or not job.get("gap_report")
    ):
        return MatchScoreResponse(
            job_id=job_id,
            status="blocked",
            recomputed=False,
            match_reason="请先选择主简历并完成 JD 画像与差距分析",
            match_stale=True,
        )
    detail = api_module.compute_match_score(
        job.get("jd_text"),
        job.get("jd_profile"),
        job.get("gap_report"),
        job.get("eval_score"),
        resume_text,
        resume_id,
    )
    if job.get("match_updated_at") and api_module.snapshot_matches(
        job.get("match_score_detail"),
        job.get("jd_text"),
        resume_text,
        resume_id,
    ):
        return MatchScoreResponse(
            job_id=job_id,
            status="ready"
            if _match_reason_source(job) == "llm"
            else "fallback",
            recomputed=False,
            match_score=job.get("match_score"),
            match_score_detail=job.get("match_score_detail"),
            match_reason=job.get("match_reason"),
            match_reason_source=_match_reason_source(job),
            match_updated_at=job.get("match_updated_at"),
            match_stale=False,
        )
    api_module.enforce_daily_llm_cap(user['user_id'])
    with llm_tenant_context(user['user_id']):
        reason = _llm_match_reason(job, detail, resume_text)
    source = "llm" if reason else "fallback"
    if reason is None:
        reason = api_module.fallback_match_reason(
            detail,
            (job.get("gap_report") or {}).get("missing_keywords") or [],
        )
    now = time.time()
    updated = api_module._jobs.update_job(
        user['user_id'],
        job_id,
        match_score=detail["total"],
        match_score_detail=detail,
        match_reason=reason,
        match_updated_at=now,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return MatchScoreResponse(
        job_id=job_id,
        status="ready" if source == "llm" else "fallback",
        recomputed=True,
        match_score=updated.get("match_score"),
        match_score_detail=updated.get("match_score_detail"),
        match_reason=updated.get("match_reason"),
        match_reason_source=source,
        match_updated_at=updated.get("match_updated_at"),
        match_stale=False,
    )


@router.post(
    '/api/jobs/{job_id}/workbench/rewrite',
    response_model=WorkbenchRewriteResponse,
)
def rewrite_workbench_bullet(
    job_id: str,
    req: WorkbenchRewriteRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Rewrite one persisted bullet by stable diff_id."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    diffs = list(job.get('diffs') or []) + list(job.get('invalid_diffs') or [])
    target = next(
        (diff for diff in diffs if diff.get('diff_id') == req.diff_id),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail='Diff not found')
    original = (target.get('original') or '').strip()
    if not original:
        raise HTTPException(status_code=422, detail='Original bullet is empty')
    config = api_module.build_config()
    if not config.is_llm_configured:
        raise HTTPException(
            status_code=503,
            detail='LLM 未配置。请设置 API Key（远程供应商）或激活 Ollama 本地节点。',
        )
    api_module.enforce_daily_llm_cap(user['user_id'])
    jd_context = json.dumps(
        {
            'jd_profile': job.get('jd_profile'),
            'gap_report': job.get('gap_report'),
            'jd_text': (job.get('jd_text') or '')[:6000],
        },
        ensure_ascii=False,
    )
    with llm_tenant_context(user['user_id']):
        with api_module.OpenAIClient(
            config,
            timeout=45.0,
            # R4 P0-2：bullet 改写非 role 直连调用，输出钳制 256（03-AIE §③）。
            max_tokens=256,
        ) as client:
            rewritten = api_module.rewrite_bullet(
                client,
                original,
                req.instruction,
                jd_context=jd_context,
                cache=api_module._cache,
                tenant=user['user_id'],
            )

    replacement = {
        'diff_id': target.get('diff_id'),
        'section': target.get('section', ''),
        'type': target.get('type', 'modify'),
        'original': original,
        'proposed': rewritten.proposed,
        'reason': rewritten.reason,
        'confidence': rewritten.confidence,
        'provenance': original,
        'provenance_quote': original,
        'source_span': (
            list(rewritten.source_span)
            if rewritten.source_span is not None
            else None
        ),
        'provenance_state': 'verified',
    }
    new_diffs = []
    replaced = False
    for diff in job.get('diffs') or []:
        if diff.get('diff_id') == req.diff_id:
            new_diffs.append(replacement)
            replaced = True
        else:
            new_diffs.append(diff)
    if not replaced:
        new_diffs.append(replacement)
    new_invalid_diffs = [
        diff
        for diff in (job.get('invalid_diffs') or [])
        if diff.get('diff_id') != req.diff_id
    ]
    api_module._jobs.update_job(
        user['user_id'],
        job_id,
        diffs=new_diffs,
        invalid_diffs=new_invalid_diffs,
    )
    return WorkbenchRewriteResponse(
        diff_id=replacement['diff_id'],
        original=original,
        proposed=rewritten.proposed,
        reason=rewritten.reason,
        provenance_state='verified',
    )

def job_status(job_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return the current state of a queued/running/completed job.

    Not registered as a route: GET /api/jobs/{job_id} is served by
    get_library_job, which falls back here for analysis job snapshots.
    """
    snapshot = api_module._registry.snapshot(job_id, tenant_id=user['user_id'])
    if snapshot is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return snapshot

