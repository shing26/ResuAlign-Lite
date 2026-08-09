"""HTTP-facing helpers for the batch alignment queue.

The API-dependent orchestration (registry polling, resume/job lookups, job
queueing) lives here so ``resualign.batch`` stays importable without pulling
in the FastAPI layer (A2).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

import resualign.api as api_module

from ...batch import (
    BatchAlignRequest,
    BatchAlignStore,
    _batch_summary,
    _row_summary,
)

__all__ = [
    "BatchAlignRequest",
    "BatchAlignStore",
    "cancel_batch_align",
    "get_batch_align",
    "queue_batch_align",
]


def _sync_batch(batch_id: str, tenant_id: str) -> None:
    """Refresh row statuses and summaries from the durable job registry."""
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
    from fastapi import HTTPException

    tenant_id = user['user_id']
    resume = api_module._resumes.get_master_resume(
        tenant_id, request.master_resume_id
    )
    if resume is None:
        raise HTTPException(status_code=404, detail='Master resume not found')

    jobs: list[dict[str, Any]] = []
    if request.jd_urls:
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
                raise HTTPException(
                    status_code=404, detail=f'Job not found: {job_id}'
                )
            jobs.append(job)

    config = api_module.build_config()
    if not config.api_key:
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
    _sync_batch(batch_id, tenant_id)
    batch = api_module._batch_store.get(batch_id, tenant_id)
    if batch is None:
        return None
    canceled = 0
    failed = 0
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
            # The analysis job no longer exists (TTL-purged or lost on
            # restart). That is an anomaly, not a user cancel: mark the row
            # failed with a readable reason so the UI does not misreport it
            # as "canceled" (which implies the user chose to stop it).
            row['status'] = 'failed'
            row['error'] = '分析任务已过期或丢失，请重新运行'
            failed += 1
            continue
        if snapshot.status == 'queued' and api_module._registry.cancel(
            analysis_job_id
        ):
            row['status'] = 'canceled'
            canceled += 1
    api_module._batch_store.update_rows(batch_id, tenant_id, batch['rows'])
    return {
        'batch_id': batch_id,
        'canceled': canceled,
        'failed': failed,
        'total': len(batch['rows']),
    }


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
