"""Resume-optimize job runner: overall analysis + modular polish.

Used by ``resualign.api._run_job`` when a payload carries
``optimize_resume: True``. The overview step is local (never calls the LLM);
each experience module is polished in its own isolated LLM call so a timeout
or provider error on one entry never blocks the rest (xzjobs-style 模块化).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from fastapi import HTTPException

import resualign.api as api_module

from ...engine import MAX_RESUME_INPUT_CHARS, truncate_text
from ...resume_optimize import (
    build_overview,
    extract_project_modules,
    module_failure_detail,
    polish_project_module,
    polish_timeout,
)

logger = logging.getLogger(__name__)


def run_resume_optimize(
    payload: dict[str, Any],
    on_stage: Callable[[str, str], None] | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Execute the two-step xzjobs-style resume optimization and return the
    job result dict (overview + per-module polish outcomes).

    The job always succeeds as long as the local overview is produced; module
    failures are recorded per item (``status: "failed"`` + readable error).
    """
    t0 = time.monotonic()
    resume_text = truncate_text(
        payload.get("resume_text") or "", MAX_RESUME_INPUT_CHARS
    )
    jd_text = truncate_text((payload.get("jd_text") or "").strip(), 8000)
    notify = on_stage or (lambda stage, message: None)

    notify("overview", "正在进行整体分析与核心优势提炼（本地规则）...")
    overview = build_overview(resume_text, jd_text)

    modules = extract_project_modules(resume_text)
    items: list[dict[str, Any]] = []
    llm_used = False
    total = len(modules)
    if total:
        config = api_module.build_config()
        client = None
        build_error = None
        try:
            client = api_module.OpenAIClient(config, timeout=polish_timeout())
        except Exception as exc:  # noqa: BLE001 - report as per-module failure
            logger.warning("Failed to build LLM client for resume optimize: %s", exc)
            build_error = module_failure_detail(exc, "模型客户端")
        if client is not None:
            with client:
                for index, module in enumerate(modules):
                    label = module.get("title") or f"{module.get('module')} 第{index + 1}条"
                    notify(
                        "polishing",
                        f"正在润色第 {index + 1}/{total} 条：{label[:24]}",
                    )
                    try:
                        item = polish_project_module(
                            client, module, jd_context=jd_text
                        )
                        llm_used = True
                        items.append(item)
                    except Exception as exc:  # noqa: BLE001 - isolation
                        logger.warning(
                            "Resume optimize module %s failed: %s", label, exc
                        )
                        items.append(
                            {
                                "module": module.get("module", ""),
                                "index": index,
                                "title": module.get("title", ""),
                                "original": module.get("original", ""),
                                "status": "failed",
                                "optimized": "",
                                "rationale": "",
                                "error": module_failure_detail(exc, label),
                            }
                        )
        elif build_error:
            for index, module in enumerate(modules):
                label = module.get("title") or f"{module.get('module')} 第{index + 1}条"
                items.append(
                    {
                        "module": module.get("module", ""),
                        "index": index,
                        "title": module.get("title", ""),
                        "original": module.get("original", ""),
                        "status": "failed",
                        "optimized": "",
                        "rationale": "",
                        "error": build_error,
                    }
                )

    return {
        "overview": overview,
        "modules": items,
        "llm_used": llm_used,
        "model": api_module.build_config().model if llm_used else None,
        "elapsed_seconds": round(time.monotonic() - t0, 1),
        "note": (
            "未识别到项目经历/工作经历模块，跳过逐项润色" if not total else None
        ),
    }


def _find_module(modules: list[dict[str, Any]], module: str, index: int):
    for candidate in modules:
        if candidate.get("module") == module and candidate.get("index") == index:
            return candidate
    return None


def apply_resume_optimize_items(
    tenant_id: str,
    resume_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply accepted optimized entries onto the master resume as a new version.

    Re-extracts modules from the *current* resume so edits made after the
    optimize job ran are never silently overwritten; exact one-occurrence
    substring replacement keeps unrelated text untouched.
    """
    if not items:
        raise HTTPException(status_code=422, detail="没有要采纳的优化项")
    resume = api_module._resumes.get_master_resume(tenant_id, resume_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="Master resume not found")
    content = resume.get("content") or ""
    modules = extract_project_modules(content)
    new_content = content
    applied: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in items:
        module_name = str(item.get("module") or "")
        index = int(item.get("index", -1))
        optimized = (item.get("optimized") or "").strip()
        key = (module_name, index)
        if key in seen:
            raise HTTPException(
                status_code=422,
                detail=f"重复的优化项：{module_name} 第 {index + 1} 条",
            )
        seen.add(key)
        if not optimized:
            raise HTTPException(
                status_code=422,
                detail=f"第 {index + 1} 条的优化内容为空",
            )
        module = _find_module(modules, module_name, index)
        if module is None:
            raise HTTPException(
                status_code=422,
                detail="简历内容已变化，请重新运行优化后再采纳（找不到对应模块）",
            )
        original = module["original"]
        occurrences = new_content.count(original)
        if occurrences != 1:
            raise HTTPException(
                status_code=422,
                detail="简历内容已变化，请重新运行优化后再采纳（原文不唯一）",
            )
        new_content = new_content.replace(original, optimized)
        applied.append(
            {
                "module": module_name,
                "index": index,
                "title": module.get("title", ""),
            }
        )
    if not applied:
        raise HTTPException(status_code=422, detail="没有可应用的优化项")
    updated = api_module._resumes.update_master_resume(tenant_id, resume_id, new_content)
    return {
        "resume": updated,
        "applied": applied,
        "applied_count": len(applied),
    }


__all__ = ["apply_resume_optimize_items", "run_resume_optimize"]