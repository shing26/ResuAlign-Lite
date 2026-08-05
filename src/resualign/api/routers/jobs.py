
import logging
import threading
import uuid
import json
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..deps import get_current_user
from ..schemas import (
    BulkStatusRequest,
    FinalDraftRequest,
    JobPreanalyzeResponse,
    JDParseRequest,
    JobCreateRequest,
    JobImportRequest,
    JobUpdateRequest,
    WorkbenchAcceptRequest,
    WorkbenchRewriteRequest,
    WorkbenchRewriteResponse,
    WorkbenchRunRequest,
)

import resualign.api as api_module

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post('/api/jobs', status_code=201)
def create_library_job(req: JobCreateRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Ingest one job from pasted text or a JD URL."""
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    if not (req.jd_text or '').strip() and (not (req.jd_url or '').strip()):
        raise HTTPException(status_code=422, detail='Either jd_text or jd_url is required')
    try:
        return api_module._create_job_from_source(user, {'title': req.title, 'jd_text': req.jd_text, 'jd_url': req.jd_url, 'company': req.company, 'location': req.location, 'salary_min': req.salary_min, 'salary_max': req.salary_max, 'salary_currency': req.salary_currency, 'source_type': req.source_type, 'source_url': req.source_url, 'job_function': req.job_function, 'seniority': req.seniority, 'tech_tags': req.tech_tags, 'status': req.status, 'posting_date': req.posting_date})
    except api_module.CrawlError as exc:
        raise HTTPException(status_code=502, detail=api_module._jd_parse_error_detail(exc)) from exc
    except api_module.UserStoreError as exc:
        if 'Duplicate job' in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post('/api/jobs/parse-jd')
def parse_jd_preview(req: JDParseRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Crawl a JD URL and return a preview without creating a job."""
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
    jd_url = req.jd_url.strip()
    if not jd_url:
        raise HTTPException(status_code=422, detail='jd_url is required')
    meta: dict[str, Any] = {}
    jd_text = api_module._crawl_jd_or_502(jd_url, meta=meta)
    salary_min, salary_max = api_module.extract_salary_range(jd_text)
    has_salary = salary_min is not None or salary_max is not None
    return {'title': meta.get('title') or api_module._derive_title(jd_text), 'jd_text': jd_text, 'company': meta.get('company'), 'city': meta.get('city'), 'salary_min': salary_min, 'salary_max': salary_max, 'salary_currency': 'CNY' if has_salary else None, 'source_url': jd_url}

@router.post('/api/jobs/import')
def import_library_jobs(req: JobImportRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue a batch import so crawl/classification never blocks the API."""
    api_module._enforce_rate_limit(request, api_module._import_rate_limiter)
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
def list_library_jobs(job_function: str | None=None, seniority: str | None=None, status: str | None=None, search: str | None=None, limit: int=100, offset: int=0, user: dict[str, Any]=Depends(get_current_user)):
    """List library jobs with optional filters."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    return api_module._jobs.list_jobs(user['user_id'], job_function=job_function, seniority=seniority, status=status, search=search, limit=limit, offset=offset)

@router.get('/api/jobs/{job_id}')
def get_library_job(job_id: str, user: dict[str, Any]=Depends(get_current_user)):
    """Return one library job, falling back to an analysis job snapshot."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is not None:
        return job
    return api_module.job_status(job_id, user)

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
    try:
        classification = api_module._classify_job(jd_text, job_functions, seniorities)
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
        saved = api_module._jobs.save_final_draft(user['user_id'], job_id, req.draft)
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if saved is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return saved

@router.patch('/api/jobs/{job_id}')
async def update_library_job(job_id: str, req: JobUpdateRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Update editable job fields such as tags, salary, and status."""
    job_functions, seniorities = api_module._settings_vocabulary(user['user_id'])
    timeline = await api_module._read_timeline_extras(request)
    try:
        job = api_module._jobs.update_job(user['user_id'], job_id, title=req.title, jd_text=req.jd_text, company=req.company, location=req.location, salary_min=req.salary_min, salary_max=req.salary_max, salary_currency=req.salary_currency, source_type=req.source_type, source_url=req.source_url, job_function=req.job_function, seniority=req.seniority, tech_tags=req.tech_tags, status=req.status, posting_date=req.posting_date, applied_at=timeline.get('applied_at'), next_step=timeline.get('next_step'), notes=timeline.get('notes'), offer_at=timeline.get('offer_at'), rejected_at=timeline.get('rejected_at'), tailor_granularity=req.tailor_granularity, tailor_focus=req.tailor_focus, custom_prompt=req.custom_prompt, allowed_job_functions=job_functions, allowed_seniorities=seniorities)
    except api_module.UserStoreError as exc:
        if 'Duplicate job' in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    return job

@router.post('/api/jobs/bulk-status', include_in_schema=False)
def bulk_update_job_status(req: BulkStatusRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Update status for many library jobs, returning per-id results."""
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
    """Delete a library job."""
    if not api_module._jobs.delete_job(user['user_id'], job_id):
        raise HTTPException(status_code=404, detail='Job not found')
    return None

@router.post('/api/jobs/{job_id}/workbench', status_code=202)
def run_workbench(job_id: str, req: WorkbenchRunRequest, request: Request, user: dict[str, Any]=Depends(get_current_user)):
    """Queue a per-job pipeline run pinned to a Master Resume version."""
    api_module._enforce_rate_limit(request, api_module._analyze_rate_limiter)
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    resume = api_module._resumes.get_master_resume(user['user_id'], req.master_resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')
    config = api_module.build_config()
    if not config.api_key:
        raise HTTPException(status_code=503, detail='API key not configured. Set via .env file or environment variables.')
    cached_diagnosis = api_module._cached_diagnosis(resume, config, user['user_id'])
    payload = {'resume_text': resume['content'], 'jd_text': job['jd_text'], 'jd_url': job.get('source_url'), 'run_eval': False, 'granularity': req.granularity, 'prompt_focus': req.prompt_focus, 'custom_prompt': req.custom_prompt, 'master_resume_id': req.master_resume_id, 'library_job_id': job_id}
    if cached_diagnosis is not None:
        payload['precomputed_diagnosis'] = cached_diagnosis
    analysis_job_id = api_module._queue_job(user, payload, workbench=True)
    api_module._jobs.update_job(user['user_id'], job_id, workbench_job_id=analysis_job_id, workbench_resume_id=req.master_resume_id, tailor_granularity=req.granularity, tailor_focus=req.prompt_focus, custom_prompt=req.custom_prompt)
    return {'job_id': analysis_job_id, 'status': 'queued', 'workbench': True}

@router.get('/api/jobs/{job_id}/appraisal')
def get_workbench_appraisal(
    job_id: str,
    commute_minutes: int | None = None,
    commute_cost_per_minute: float | None = None,
    living_cost_adjustment: float | None = None,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Return the worth appraisal for one library job."""
    job = api_module._jobs.get_job(user['user_id'], job_id)
    if job is None:
        raise HTTPException(status_code=404, detail='Job not found')
    library_median = api_module._jobs.salary_median(user['user_id'], job_function=job.get('job_function'))
    latest = api_module._registry.snapshot(job.get('workbench_job_id'), tenant_id=user['user_id']) if job.get('workbench_job_id') else None
    match_score = None
    if latest and latest.get('status') == 'succeeded' and latest.get('result'):
        result = latest['result']
        eval_score = result.get('eval_score') or {}
        match_score = eval_score.get('jd_match_score')
        if match_score is None:
            match_score = api_module._gap_match_score(result)
        if match_score is None:
            match_score = result.get('score')
    pinned = None
    if job.get('workbench_resume_id'):
        pinned = api_module._resumes.get_master_resume(user['user_id'], job['workbench_resume_id'])
    profile = api_module.resume_profile(pinned['content']) if pinned else {'years': None, 'education': None}
    settings = api_module._settings_store.get_settings(user['user_id'])
    try:
        return api_module.compute_appraisal(
            job,
            resume_match_score=match_score,
            resume_years=profile['years'],
            resume_education=profile['education'],
            weights=settings['appraisal_weights'],
            settings=settings,
            library_median=library_median,
            commute_minutes=commute_minutes,
            commute_cost_per_minute=commute_cost_per_minute,
            living_cost_adjustment=living_cost_adjustment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
            prompt_version = 'jd-analysis-v1'
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
            classification=classification,
            cache_hit=True,
        )

    job_functions, seniorities = api_module._settings_vocabulary(user['user_id'])
    try:
        classification = api_module._classify_job(
            jd_text, job_functions, seniorities
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
    config = api_module.build_config()
    if not config.api_key:
        raise HTTPException(
            status_code=503,
            detail='API key not configured. Set via .env file or environment variables.',
        )
    cache_hit = _preanalyze_cache_hit(
        user['user_id'], config, resume_text, jd_text
    )
    profile_dict = None
    gap_dict = None
    with api_module.OpenAIClient(config, timeout=60.0) as client:
        if resume_text.strip():
            profile, gap = api_module.profile_and_gaps(
                client,
                resume_text,
                jd_text,
                cache=api_module._cache,
                tenant=user['user_id'],
            )
            profile_dict = api_module.jd_profile_to_dict(profile)
            gap_dict = asdict(gap)
        else:
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
        classification=classification,
        cache_hit=cache_hit,
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
    if not config.api_key:
        raise HTTPException(
            status_code=503,
            detail='API key not configured. Set via .env file or environment variables.',
        )
    jd_context = json.dumps(
        {
            'jd_profile': job.get('jd_profile'),
            'gap_report': job.get('gap_report'),
            'jd_text': (job.get('jd_text') or '')[:6000],
        },
        ensure_ascii=False,
    )
    with api_module.OpenAIClient(config, timeout=45.0) as client:
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
    api_module._jobs.update_job(user['user_id'], job_id, diffs=new_diffs)
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

