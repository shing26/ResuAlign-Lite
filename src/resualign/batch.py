"""In-memory batch alignment queue and per-row result store.

This module is deliberately free of ``resualign.api`` imports (A2): the
pure queue/store/summary primitives live here, while the HTTP-facing
orchestration that touches API state lives in ``api/services/batch.py``.
Importing this module must not cascade-import the FastAPI layer.
"""

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
    # 'pending'：忽略 job_ids（传空数组），自动选中岗位库里全部待处理岗位
    # （idle/failed，以及 registry 已终态或缺失的陈旧 queued）；
    # master_resume_id 传空串时回退到最近更新的主简历。
    selector: Optional[Literal['pending']] = None
    granularity: Literal['fine', 'medium', 'coarse'] = 'fine'
    prompt_focus: Literal['balanced', 'quantified', 'skills'] = 'balanced'
    custom_prompt: str | None = None
    run_eval: bool | None = None

    @model_validator(mode='after')
    def _validate_job_ids(self) -> 'BatchAlignRequest':
        if self.selector == 'pending':
            return self
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
