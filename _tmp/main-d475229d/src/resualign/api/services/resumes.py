
import hashlib
import logging
from typing import Any, Optional

import resualign.api as api_module

logger = logging.getLogger(__name__)


def _content_sha256(text: str) -> str:
    """Return a stable content fingerprint for the diagnosis cache."""
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()

def _cached_diagnosis(resume: dict[str, Any], config: Any, tenant_id: str) -> Optional[dict[str, Any]]:
    """Reuse a previous diagnosis when resume content and model match."""
    latest_job_id = resume.get('latest_diagnosis_job_id')
    diag: Optional[dict[str, Any]] = None
    if latest_job_id:
        snapshot = api_module._registry.snapshot(
            latest_job_id, tenant_id=tenant_id
        )
        if snapshot is not None and snapshot.get('status') == 'succeeded':
            result = snapshot.get('result') or {}
            if result.get('diagnosis_source_hash') == api_module._content_sha256(
                resume.get('content') or ''
            ):
                diag = result.get('diagnosis') or {}
    if not diag and resume.get('resume_id'):
        persisted = api_module._resumes.get_latest_diagnosis_snapshot(
            tenant_id, resume['resume_id']
        )
        if persisted is not None:
            stored_diag, source_hash = persisted
            if source_hash == api_module._content_sha256(
                resume.get('content') or ''
            ):
                diag = stored_diag
    if not diag:
        return None
    if diag.get('model') != config.model:
        return None
    return {'score': diag.get('score', 0), 'skills': diag.get('skills') or [], 'issues': diag.get('issues') or []}


def backfill_diagnosis_snapshots() -> int:
    """Persist currently-valid registry diagnosis results into master resumes."""
    written = 0
    for ref in api_module._resumes.list_resume_diagnosis_refs():
        if ref['has_snapshot']:
            continue
        snapshot = api_module._registry.snapshot(
            ref['latest_diagnosis_job_id'],
            tenant_id=ref['tenant_id'],
        )
        if snapshot is None or snapshot.get('status') != 'succeeded':
            continue
        result = snapshot.get('result') or {}
        source_hash = result.get('diagnosis_source_hash') or ''
        if source_hash != _content_sha256(ref['content']):
            continue
        diagnosis = result.get('diagnosis') or {}
        if not diagnosis:
            continue
        updated = api_module._resumes.set_latest_diagnosis_snapshot(
            ref['tenant_id'],
            ref['resume_id'],
            diagnosis,
            source_hash,
        )
        if updated is not None:
            written += 1
    if written:
        logger.info('Backfilled %s persisted resume diagnosis snapshots', written)
    return written

