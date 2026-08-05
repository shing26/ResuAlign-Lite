"""In-memory batch alignment queue and per-row result store."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, model_validator


class BatchAlignRequest(BaseModel):
    master_resume_id: str
    job_ids: list[str]
    jd_urls: list[str] | None = None
    granularity: Literal['fine', 'medium', 'coarse'] = 'fine'
    prompt_focus: Literal['balanced', 'quantified', 'skills'] = 'balanced'
    custom_prompt: str | None = None

    @model_validator(mode='after')
    def _validate_job_ids(self) -> 'BatchAlignRequest':
        urls = self.jd_urls or []
        if urls:
            if self.job_ids:
                raise ValueError('Provide either job_ids or jd_urls, not both')
            if not 2 <= len(urls) <= 5:
                raise ValueError('jd_urls must contain between 2 and 5 URLs')
            if len(set(urls)) != len(urls):
                raise ValueError('jd_urls must be unique')
        else:
            if not 2 <= len(self.job_ids) <= 5:
                raise ValueError('job_ids must contain between 2 and 5 jobs')
            if len(set(self.job_ids)) != len(self.job_ids):
                raise ValueError('job_ids must be unique')
        return self


class BatchAlignStore:
    """Thread-safe in-memory batch registry with TTL cleanup."""

    def __init__(self, ttl_seconds: float = 24 * 3600) -> None:
        self._ttl_seconds = ttl_seconds
        self._batches: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create(
        self,
        tenant_id: str,
        master_resume_id: str,
        rows: list[dict[str, Any]],
        granularity: str = 'fine',
        prompt_focus: str = 'balanced',
        custom_prompt: str | None = None,
    ) -> str:
        batch_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._prune(now)
            self._batches[batch_id] = {
                'batch_id': batch_id,
                'tenant_id': tenant_id,
                'master_resume_id': master_resume_id,
                'granularity': granularity,
                'prompt_focus': prompt_focus,
                'custom_prompt': custom_prompt,
                'created_at': now,
                'rows': [dict(row) for row in rows],
            }
        return batch_id

    def get(self, batch_id: str, tenant_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            self._prune(time.time())
            batch = self._batches.get(batch_id)
            if batch is None or batch['tenant_id'] != tenant_id:
                return None
            return self._copy(batch)

    def set_analysis_job(
        self,
        batch_id: str,
        tenant_id: str,
        job_id: str,
        analysis_job_id: str,
    ) -> bool:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch['tenant_id'] != tenant_id:
                return False
            for row in batch['rows']:
                if row['job_id'] == job_id:
                    row['analysis_job_id'] = analysis_job_id
                    return True
            return False

    def update_rows(
        self,
        batch_id: str,
        tenant_id: str,
        rows: list[dict[str, Any]],
    ) -> bool:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None or batch['tenant_id'] != tenant_id:
                return False
            batch['rows'] = [dict(row) for row in rows]
            return True

    def _copy(self, batch: dict[str, Any]) -> dict[str, Any]:
        copied = dict(batch)
        copied['rows'] = [dict(row) for row in batch['rows']]
        return copied

    def _prune(self, now: float) -> None:
        expired = [
            batch_id
            for batch_id, batch in self._batches.items()
            if now - batch['created_at'] > self._ttl_seconds
        ]
        for batch_id in expired:
            self._batches.pop(batch_id, None)


def _row_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Build the compact comparison-matrix summary for one succeeded row."""
    eval_score = result.get('eval_score') or {}
    gap_report = result.get('gap_report') or {}
    score = result.get('score')
    if score is None:
        score = 0
    if score >= 75:
        next_step = 'Apply'
    elif score >= 55:
        next_step = 'Consider'
    else:
        next_step = 'Skip'
    return {
        'score': score,
        'eval': eval_score.get('jd_match_score'),
        'key_gaps': (gap_report.get('missing_keywords') or [])[:5],
        'next_step': next_step,
    }


def _batch_summary(batch: dict[str, Any]) -> dict[str, Any]:
    rows = batch['rows']
    counts = {
        'queued': 0,
        'running': 0,
        'succeeded': 0,
        'failed': 0,
        'canceled': 0,
    }
    scores: list[float] = []
    for row in rows:
        status = row.get('status')
        if status in counts:
            counts[status] += 1
        summary = row.get('summary') or {}
        if status == 'succeeded' and summary.get('score') is not None:
            scores.append(float(summary['score']))
    best_id = None
    best_score = None
    if scores:
        best_score = max(scores)
        best_id = next(
            row['job_id']
            for row in rows
            if (row.get('summary') or {}).get('score') == best_score
        )
    return {
        'total': len(rows),
        'queued': counts['queued'],
        'running': counts['running'],
        'succeeded': counts['succeeded'],
        'failed': counts['failed'],
        'canceled': counts['canceled'],
        'completed': counts['succeeded'] + counts['failed'] + counts['canceled'],
        'average_score': round(sum(scores) / len(scores), 2) if scores else None,
        'best_job_id': best_id,
        'best_score': best_score,
    }


def _sync_batch(batch_id: str, tenant_id: str) -> None:
    """Refresh row statuses and summaries from the durable job registry."""
    import resualign.api as api_module

    store = api_module._batch_store
    batch = store.get(batch_id, tenant_id)
    if batch is None:
        return
    rows = batch['rows']
    changed = False
    for row in rows:
        analysis_job_id = row.get('analysis_job_id')
        if not analysis_job_id:
            continue
        snapshot = api_module._registry.snapshot(
            analysis_job_id, tenant_id=tenant_id
        )
        if snapshot is None:
            continue
        status = snapshot.get('status')
        if status == 'succeeded':
            row['status'] = 'succeeded'
            row['summary'] = _row_summary(snapshot.get('result') or {})
            row['error'] = None
            changed = True
        elif status == 'failed':
            row['status'] = 'failed'
            row['error'] = snapshot.get('error')
            row['summary'] = None
            changed = True
        elif status == 'canceled':
            row['status'] = 'canceled'
            row['error'] = snapshot.get('error')
            row['summary'] = None
            changed = True
        elif status in ('queued', 'running') and row.get('status') != status:
            row['status'] = status
            changed = True
    if changed:
        store.update_rows(batch_id, tenant_id, rows)


def queue_batch_align(
    user: dict[str, Any],
    request: BatchAlignRequest,
) -> dict[str, Any]:
    """Validate inputs and queue one workbench analysis per target."""
    import resualign.api as api_module

    tenant_id = user['user_id']
    resume = api_module._resumes.get_master_resume(
        tenant_id, request.master_resume_id
    )
    if resume is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail='Master resume not found')

    jobs: list[dict[str, Any]] = []
    if request.jd_urls:
        from fastapi import HTTPException

        for jd_url in request.jd_urls:
            try:
                created = api_module._create_job_from_source(
                    user, {'jd_url': jd_url, 'source_type': 'url'}
                )
            except (api_module.UserStoreError, api_module.CrawlError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            jobs.append(created)
    else:
        for job_id in request.job_ids:
            job = api_module._jobs.get_job(tenant_id, job_id)
            if job is None:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404, detail=f'Job not found: {job_id}'
                )
            jobs.append(job)

    config = api_module.build_config()
    if not config.api_key:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail=(
                'API key not configured. Set via .env file or environment '
                'variables.'
            ),
        )

    cached_diagnosis = api_module._cached_diagnosis(
        resume, config, tenant_id
    )
    rows = [
        {
            'job_id': job['job_id'],
            'title': job.get('title'),
            'company': job.get('company'),
            'status': 'queued',
            'analysis_job_id': None,
            'error': None,
            'summary': None,
        }
        for job in jobs
    ]
    batch_id = api_module._batch_store.create(
        tenant_id,
        request.master_resume_id,
        rows,
        granularity=request.granularity,
        prompt_focus=request.prompt_focus,
        custom_prompt=request.custom_prompt,
    )

    for row, job in zip(rows, jobs):
        payload = {
            'resume_text': resume['content'],
            'jd_text': job.get('jd_text'),
            'jd_url': job.get('source_url'),
            'run_eval': True,
            'granularity': request.granularity,
            'prompt_focus': request.prompt_focus,
            'custom_prompt': request.custom_prompt,
            'master_resume_id': request.master_resume_id,
            'library_job_id': job['job_id'],
        }
        if cached_diagnosis is not None:
            payload['precomputed_diagnosis'] = cached_diagnosis
        analysis_job_id = api_module._queue_job(user, payload, workbench=True)
        api_module._batch_store.set_analysis_job(
            batch_id, tenant_id, job['job_id'], analysis_job_id
        )

    threading.Thread(
        target=_monitor_batch, args=(batch_id, tenant_id), daemon=True
    ).start()
    return {'batch_id': batch_id, 'total': len(rows), 'queued': len(rows)}


def get_batch_align(
    batch_id: str, tenant_id: str
) -> Optional[dict[str, Any]]:
    """Return a synced batch snapshot with per-row results and a summary."""
    _sync_batch(batch_id, tenant_id)
    import resualign.api as api_module

    batch = api_module._batch_store.get(batch_id, tenant_id)
    if batch is None:
        return None
    result = {
        'batch_id': batch['batch_id'],
        'master_resume_id': batch['master_resume_id'],
        'granularity': batch['granularity'],
        'prompt_focus': batch['prompt_focus'],
        'custom_prompt': batch['custom_prompt'],
        'created_at': batch['created_at'],
        'rows': batch['rows'],
        'summary': _batch_summary(batch),
    }
    return result


def cancel_batch_align(
    batch_id: str, tenant_id: str
) -> Optional[dict[str, Any]]:
    """Cancel queued rows; running rows are left for the registry to finish."""
    import resualign.api as api_module

    _sync_batch(batch_id, tenant_id)
    batch = api_module._batch_store.get(batch_id, tenant_id)
    if batch is None:
        return None
    canceled = 0
    for row in batch['rows']:
        if row.get('status') != 'queued':
            continue
        analysis_job_id = row.get('analysis_job_id')
        snapshot = (
            api_module._registry.get(analysis_job_id, tenant_id=tenant_id)
            if analysis_job_id
            else None
        )
        if snapshot is None:
            row['status'] = 'canceled'
            canceled += 1
            continue
        if snapshot.status == 'queued' and api_module._registry.cancel(
            analysis_job_id
        ):
            row['status'] = 'canceled'
            canceled += 1
    api_module._batch_store.update_rows(batch_id, tenant_id, batch['rows'])
    return {'batch_id': batch_id, 'canceled': canceled, 'total': len(batch['rows'])}


def _monitor_batch(batch_id: str, tenant_id: str) -> None:
    """Poll the durable registry until every batch row reaches a terminal state."""
    while True:
        try:
            batch = get_batch_align(batch_id, tenant_id)
            if batch is None:
                return
            if all(
                row.get('status') in ('succeeded', 'failed', 'canceled')
                for row in batch['rows']
            ):
                return
        except Exception:
            pass
        time.sleep(0.1)
