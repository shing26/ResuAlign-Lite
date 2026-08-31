
import hashlib
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

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



# ---------------------------------------------------------------------------
# 结构化档案抽取（网申回填数据源，#61 预研方案 A）
# ---------------------------------------------------------------------------

PROFILE_PROMPT_VERSION = "resume-profile:v1"


class ResumeProfileOut(BaseModel):
    """chat_structured 的目标形状（与 ResumeProfileData 对齐）。"""

    basic: dict[str, Any] = Field(default_factory=dict)
    education: list[dict[str, Any]] = Field(default_factory=list)
    work: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    summary: str = ""

_PROFILE_SYSTEM = (
    "你是简历结构化引擎。从主简历 Markdown 中抽取原子字段供网申表单自动填充。"
    "只抽取简历中明确存在的事实，缺失字段留空字符串或空数组，绝不编造。"
    "日期统一为 YYYY-MM 或 YYYY 格式（以简历原文为准）。"
)


class _ProfileSchema(BaseModel):
    """LLM structured output 的目标形状（与 ResumeProfileData 对齐）。"""

    basic: dict[str, Any] = Field(default_factory=dict)
    education: list[dict[str, Any]] = Field(default_factory=list)
    work: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    summary: str = ""


def extract_resume_profile(user: dict[str, Any], resume_id: str) -> dict[str, Any]:
    """Extract (and persist) the structured profile for one master resume."""
    tenant_id = user["user_id"]
    resume = api_module._resumes.get_master_resume(tenant_id, resume_id)
    if resume is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Master resume not found")
    content = resume.get("content") or ""
    if not content.strip():
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="主简历内容为空，无法抽取")

    config = api_module.build_config()
    if not config.is_llm_configured:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503,
            detail="LLM 未配置。结构化抽取需要模型，请先在设置页配置节点。",
        )

    from ...llm import OpenAIClient

    client = OpenAIClient(config, timeout=45.0, max_tokens=2048)
    try:
        result = client.chat_structured(
            _PROFILE_SYSTEM,
            content[:12000],
            ResumeProfileOut,
        )
    finally:
        client.close()

    profile = {
        "basic": {
            "name": str((result.get("basic") or {}).get("name", "")),
            "phone": str((result.get("basic") or {}).get("phone", "")),
            "email": str((result.get("basic") or {}).get("email", "")),
            "gender": str((result.get("basic") or {}).get("gender", "")),
            "birth": str((result.get("basic") or {}).get("birth", "")),
            "location": str((result.get("basic") or {}).get("location", "")),
            "id_number": "",
        },
        "education": result.get("education") or [],
        "work": result.get("work") or [],
        "projects": result.get("projects") or [],
        "skills": result.get("skills") or [],
        "summary": str(result.get("summary", "")),
    }
    # 证件号绝不自动抽取（敏感字段，用户在编辑 UI 自行补充）
    saved = api_module._resumes.save_resume_profile(
        tenant_id,
        resume_id,
        profile,
        _content_sha256(content),
        config.model,
    )
    if saved is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Master resume not found")
    return {"profile": saved["profile"], "extracted_with": config.model}
