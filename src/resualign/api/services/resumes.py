
import hashlib
from typing import Any, Optional

import resualign.api as api_module


def _content_sha256(text: str) -> str:
    """Return a stable content fingerprint for the diagnosis cache."""
    return hashlib.sha256((text or '').encode('utf-8')).hexdigest()

def _cached_diagnosis(resume: dict[str, Any], config: Any, tenant_id: str) -> Optional[dict[str, Any]]:
    """Reuse a previous diagnosis when resume content and model match."""
    latest_job_id = resume.get('latest_diagnosis_job_id')
    if not latest_job_id:
        return None
    snapshot = api_module._registry.snapshot(latest_job_id, tenant_id=tenant_id)
    if snapshot is None or snapshot.get('status') != 'succeeded':
        return None
    result = snapshot.get('result') or {}
    if result.get('diagnosis_source_hash') != api_module._content_sha256(resume.get('content') or ''):
        return None
    diag = result.get('diagnosis') or {}
    if diag.get('model') != config.model:
        return None
    return {'score': diag.get('score', 0), 'skills': diag.get('skills') or [], 'issues': diag.get('issues') or []}

