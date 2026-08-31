from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

from .evaluator import evaluate
from .extractor import extract_structured
from .gap_analyzer import analyze_gaps
from .jd_analysis import jd_profile_to_dict
from .jd_profiler import profile_jd
from .llm import LLMClient, LLMResponseError, OpenAIClient, diagnose_resume
from .llm_nodes import LLMNodeStore
from .models import GapReport, Report, ResuAlignConfig, TailoredResume
from .role_router import _role_timeout, call_with_role
from .rule_diagnose import diagnose_resume_local
from .tailor import tailor_resume, tailor_resume_map_reduce

logger = logging.getLogger(__name__)

MAX_JD_INPUT_CHARS = 8000
MAX_JD_CONTEXT_CHARS = 6000
# Tailoring is the longest single stage. Two attempts keep a degraded
# provider from multiplying a slow response into a six-minute failure.
TAILOR_MAX_RETRIES = 1
# editor 降级码集合：结构/解析类失败与超时触发空改写降级（对齐 gap 的
# schema/parse/empty 先例并纳入 timeout——慢模型的等待成本已经付过，
# 再吃一个 failed 只会逼用户手动重跑整条管线）。quota/auth/rate_limit
# 等账户类失败仍冒泡：那种情况下后续岗位同样会失败，静默降级会掩盖问题。
_DEGRADED_EDITOR_CODES = frozenset({"schema", "parse", "empty", "timeout"})

# Defensive cap on resume input so an exceptionally long resume cannot
# blow out prompt size and slow the LLM calls. Typical resumes (2-3k
# chars) are far below this limit.
MAX_RESUME_INPUT_CHARS = 15000


def _bullet_editor_enabled(granularity: str) -> bool:
    """Whether the bullet-level map-reduce editor should be used.

    Enabled for fine/medium granularity by default; override with
    ``RESUALIGN_BULLET_EDITOR=0``. Coarse restructuring always keeps the
    whole-document path. ``RESUALIGN_BULLET_EDITOR_CLOUD=1`` extends the
    map-reduce editor to cloud nodes (Phase 3): small per-bullet JSON calls
    are more reliable for models that tend to omit the diffs array on a
    whole-document rewrite.
    """
    if os.environ.get("RESUALIGN_BULLET_EDITOR", "1") != "1":
        return False
    return granularity in {"fine", "medium"}


def _is_local_llm(provider: str, base_url: str | None) -> bool:
    """Whether a provider/base_url pair points at a local inference node."""
    if (provider or "").lower() == "ollama":
        return True
    base = (base_url or "").lower()
    return "localhost" in base or "127.0.0.1" in base


def _editor_call_plan(
    node_store: "LLMNodeStore",
    tenant_id: str,
    granularity: str,
    *,
    resume_text: str,
    gap_report_text: str,
    prompt_focus: str,
    custom_prompt: str,
    jd_context: str,
) -> tuple[Any, dict]:
    """Choose the editor strategy for the role-resolved editor node.

    Local nodes (Ollama/localhost) get the bullet-level map-reduce editor:
    dozens of tiny per-bullet JSON calls fit a small local model far better
    than one whole-document rewrite (measured 2026-08-30: a 7B model at
    ~13 tok/s needs ~200s for the full-editor contract vs the 90s editor
    role timeout, and tends to omit the diffs array entirely). Cloud nodes
    keep the whole-document path for maximum rewrite quality. Coarse
    restructuring always uses the whole-document editor.
    """
    base_kwargs = {
        "resume_text": resume_text,
        "gap_report_text": gap_report_text,
        "granularity": granularity,
        "prompt_focus": prompt_focus,
        "custom_prompt": custom_prompt,
    }
    if _bullet_editor_enabled(granularity):
        editor_node = node_store.resolve_node_for_role(tenant_id, "editor")
        use_map_reduce = LLMNodeStore._is_local_node(editor_node)
        if not use_map_reduce and os.environ.get(
            "RESUALIGN_BULLET_EDITOR_CLOUD", "0"
        ) == "1":
            # Phase 3: opt-in map-reduce for cloud nodes whose whole-document
            # output tends to omit the diffs array.
            use_map_reduce = True
        if use_map_reduce:
            return tailor_resume_map_reduce, {
                **base_kwargs,
                "jd_context": jd_context,
                # Local inference is serialized by the server anyway; keep
                # one connection to avoid VRAM pressure from parallel runs.
                "parallel": not LLMNodeStore._is_local_node(editor_node),
            }
    return tailor_resume, base_kwargs


def truncate_text(text: str, limit: int) -> str:
    """Cut long inputs on a line boundary so prompts stay bounded."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline = cut.rfind("\n")
    if newline >= limit // 2:
        cut = cut[:newline]
    return cut.strip()


def _local_diagnosis(resume_text: str) -> dict:
    """Run local rule-based diagnosis as the LLM-failure fallback.

    Used when the LLM diagnose call fails (exception or role-router error)
    so the pipeline still yields ATS basics. The inner try/except keeps an
    unexpected rule bug from failing the whole pipeline either.
    """
    try:
        return diagnose_resume_local(resume_text)
    except Exception as exc:  # pragma: no cover - defensive only
        logger.warning(
            "Local diagnosis raised unexpectedly; using safe default: %s", exc
        )
        return {
            "score": 75,
            "skills": [],
            "issues": ["建议在项目中补充具体量化指标"],
            "fallback_used": True,
        }


def _profile_progress_message(profile) -> str:
    skills = (
        len(profile.must_have_skills or [])
        + len(profile.nice_to_have_skills or [])
    )
    scenarios = len(profile.business_scenarios or [])
    education = len(profile.education_requirements or [])
    return (
        f"已萃取 {skills} 项核心技能、{scenarios} 类业务场景，"
        f"并核对 {education} 项学历/出勤要求"
    )


def _gap_progress_message(gap_report) -> str:
    missing = len(gap_report.missing_keywords or [])
    misaligned = len(gap_report.misaligned_emphasis or [])
    strength = len(gap_report.strength_matches or [])
    return (
        f"已定位 {missing} 处能力缺口、{misaligned} 处错位强调，"
        f"确认 {strength} 项既有匹配"
    )


def run(
    config: ResuAlignConfig,
    resume_text: str,
    jd_text: Optional[str] = None,
    llm_client: Optional[LLMClient] = None,
    run_eval: bool = False,
    granularity: str = "medium",
    prompt_focus: str = "balanced",
    custom_prompt: str = "",
    diagnosis: Optional[dict] = None,
    on_stage: Optional[Callable[[str, str], None]] = None,
    cache=None,
    tenant: str = "default",
    node_store: LLMNodeStore | None = None,
    tenant_id: str = "default",
) -> Report:
    """Run the full pipeline: diagnose + optional alignment.

    ``diagnosis`` carries a previously computed no-JD diagnosis so repeated
    workbench runs on the same resume skip one LLM round trip.
    """
    client = llm_client or OpenAIClient(config, timeout=_role_timeout("diagnose"))
    jd_client = client
    jd_client_owned = False
    tailor_client = client
    tailor_client_owned = False
    use_roles = node_store is not None and llm_client is None and node_store.get_active_node(tenant_id) is not None
    try:
        def notify(stage: str, message: str) -> None:
            if on_stage is not None:
                on_stage(stage, message)

        notify("diagnose", "正在分析简历结构与 ATS 基础信息...")
        if diagnosis is not None:
            diag_result = diagnosis
        elif use_roles:
            try:
                diag_result, diag_meta = call_with_role(
                    "diagnose", diagnose_resume,
                    node_store, tenant_id,
                    fn_kwargs={
                        "resume_text": resume_text,
                        "cache": cache,
                        "tenant": tenant,
                        "model": config.model,
                    },
                )
                if diag_meta.get("error"):
                    logger.warning(
                        "LLM diagnose failed (%s); falling back to local rules",
                        diag_meta["error"],
                    )
                    diag_result = _local_diagnosis(resume_text)
            except Exception as exc:
                logger.warning(
                    "LLM diagnose raised (%s); falling back to local rules", exc
                )
                diag_result = _local_diagnosis(resume_text)
        else:
            try:
                diag_result = diagnose_resume(
                    client,
                    resume_text,
                    cache=cache,
                    tenant=tenant,
                    model=config.model,
                )
            except Exception as exc:
                logger.warning(
                    "LLM diagnose raised (%s); falling back to local rules", exc
                )
                diag_result = _local_diagnosis(resume_text)

        report = Report(
            score=diag_result.get("score", 0),
            skills=diag_result.get("skills", []),
            issues=diag_result.get("issues", []),
            model=config.model,
        )

        if jd_text:
            # Two-stage extraction: lightweight regex pass narrows scope
            # before the LLM pass, saving tokens on long JDs (see CONTEXT.md).
            extracted = extract_structured(jd_text)
            filtered_jd = "\n\n".join(v for v in extracted.values() if v)
            jd_input = truncate_text(filtered_jd or jd_text, MAX_JD_INPUT_CHARS)
            notify(
                "jd_analysis",
                "正在解析岗位描述并提取技能与业务场景...",
            )

            if use_roles:
                # Diagnose ran above (LLM with local fallback); profile the
                # JD via its role node.
                report.jd_profile, _ = call_with_role(
                    "profiler", profile_jd,
                    node_store, tenant_id,
                    fn_kwargs={
                        "jd_text": jd_input,
                        "cache": cache,
                        "tenant": tenant,
                    },
                )
            else:
                if llm_client is None:
                    jd_client = OpenAIClient(
                        config, timeout=_role_timeout("profiler")
                    )
                    jd_client_owned = True
                report.jd_profile = profile_jd(
                    jd_client,
                    jd_input,
                    cache=cache,
                    tenant=tenant,
                )

            # Gap analysis
            notify("jd_profiled", _profile_progress_message(report.jd_profile))
            notify("jd_analysis", "正在比对岗位画像与主简历...")
            import json as _json
            _profile_str = _json.dumps(
                jd_profile_to_dict(report.jd_profile),
                ensure_ascii=False,
            )
            if use_roles:
                # R4 P0-5（03-AIE §③）：gap 结构失败（code ∈ schema/parse/empty）
                # 降级为空 GapReport + gap_degraded 标记，任务继续而非整体 fail；
                # profiler 维持硬失败（无画像则 gap/tailor 无意义）。timeout/quota/
                # auth/rate_limit 等非结构失败仍冒泡。
                try:
                    gap_result, _ = call_with_role(
                        "gap_analyzer", analyze_gaps,
                        node_store, tenant_id,
                        fn_kwargs={
                            "resume_text": resume_text,
                            "jd_profile_text": _profile_str,
                        },
                    )
                    report.gap_report = gap_result
                except LLMResponseError as exc:
                    if getattr(exc, "code", "") in ("schema", "parse", "empty"):
                        logger.warning(
                            "gap degraded, continuing with empty report: %s", exc
                        )
                        report.gap_report = GapReport()
                        report.gap_degraded = True
                    else:
                        raise
            else:
                try:
                    report.gap_report = analyze_gaps(
                        jd_client,
                        resume_text,
                        _profile_str,
                    )
                except LLMResponseError as exc:
                    if getattr(exc, "code", "") in ("schema", "parse", "empty"):
                        logger.warning(
                            "gap degraded, continuing with empty report: %s", exc
                        )
                        report.gap_report = GapReport()
                        report.gap_degraded = True
                    else:
                        raise

            # Tailoring
            notify("gap_analyzed", _gap_progress_message(report.gap_report))
            notify("tailoring", "正在生成 STAR 精修建议（约 3-15 条）...")
            import json as _json
            gap_report_str = _json.dumps({
                "missing_keywords": report.gap_report.missing_keywords,
                "misaligned_emphasis": report.gap_report.misaligned_emphasis,
                "strength_matches": report.gap_report.strength_matches,
                "business_scenarios": report.jd_profile.business_scenarios,
                "jd_context": truncate_text(
                    filtered_jd or jd_text, MAX_JD_CONTEXT_CHARS
                ),
            }, ensure_ascii=False)
            if use_roles:
                editor_fn, editor_kwargs = _editor_call_plan(
                    node_store,
                    tenant_id,
                    granularity,
                    resume_text=resume_text,
                    gap_report_text=gap_report_str,
                    prompt_focus=prompt_focus,
                    custom_prompt=custom_prompt,
                    jd_context=truncate_text(
                        filtered_jd or jd_text, MAX_JD_CONTEXT_CHARS
                    ),
                )
            if use_roles:
                editor_fn, editor_kwargs = _editor_call_plan(
                    node_store,
                    tenant_id,
                    granularity,
                    resume_text=resume_text,
                    gap_report_text=gap_report_str,
                    prompt_focus=prompt_focus,
                    custom_prompt=custom_prompt,
                    jd_context=truncate_text(
                        filtered_jd or jd_text, MAX_JD_CONTEXT_CHARS
                    ),
                )
                try:
                    tailor_result, _ = call_with_role(
                        "editor",
                        editor_fn,
                        node_store,
                        tenant_id,
                        fn_kwargs=editor_kwargs,
                    )
                    report.tailored_resume = tailor_result
                except LLMResponseError as exc:
                    if getattr(exc, "code", "") in _DEGRADED_EDITOR_CODES:
                        logger.warning(
                            "tailor degraded, continuing with empty resume: %s", exc
                        )
                        report.tailored_resume = TailoredResume()
                        report.tailor_degraded = True
                    else:
                        raise
            else:
                if llm_client is None:
                    tailor_client = OpenAIClient(
                        config,
                        timeout=_role_timeout("editor"),
                        max_retries=TAILOR_MAX_RETRIES,
                    )
                    tailor_client_owned = True
                try:
                    if _bullet_editor_enabled(granularity) and _is_local_llm(
                        config.provider, config.base_url
                    ):
                        report.tailored_resume = tailor_resume_map_reduce(
                            tailor_client,
                            resume_text,
                            gap_report_str,
                            granularity=granularity,
                            prompt_focus=prompt_focus,
                            custom_prompt=custom_prompt,
                            jd_context=truncate_text(
                                filtered_jd or jd_text, MAX_JD_CONTEXT_CHARS
                            ),
                            parallel=False,
                        )
                    else:
                        report.tailored_resume = tailor_resume(
                            tailor_client,
                            resume_text,
                            gap_report_str,
                            granularity=granularity,
                            prompt_focus=prompt_focus,
                            custom_prompt=custom_prompt,
                        )
                except LLMResponseError as exc:
                    if getattr(exc, "code", "") in _DEGRADED_EDITOR_CODES:
                        logger.warning(
                            "tailor degraded, continuing with empty resume: %s", exc
                        )
                        report.tailored_resume = TailoredResume()
                        report.tailor_degraded = True
                    else:
                        raise
            # editor 与 gap 同款降级：schema/parse/empty/timeout 反复失败时
            # 产出空改写并置 tailor_degraded，任务继续而非整体 fail——诊断/
            # 画像/缺口照常保存（重试改写有 precomputed_diagnosis + profiler
            # 缓存兜底），用户等了整个管线不该因最后一个阶段颗粒无收。

            # Diffs from tailor_resume replace the old legacy alignment diffs
            report.diffs = report.tailored_resume.diffs
            # Phase 3: whole-document editors sometimes return sections but
            # no diffs array. Derive section-level diffs so a "succeeded"
            # alignment is never empty of actionable advice.
            if not report.diffs:
                from .tailor import derive_section_diffs

                derived = derive_section_diffs(
                    report.tailored_resume, resume_text
                )
                if derived:
                    report.tailored_resume.diffs = derived
                    report.tailored_resume.invalid_diffs = (
                        report.tailored_resume.invalid_diffs or []
                    )
                    report.diffs = derived

            # Optional evaluation
            if run_eval and report.tailored_resume:
                notify("evaluation", "正在检查经历真实性、量化占位与 ATS 匹配...")
                sections_text = "\n".join(
                    report.tailored_resume.sections.values()
                ) if report.tailored_resume.sections else resume_text
                if use_roles:
                    try:
                        eval_result, _ = call_with_role(
                            "evaluator", evaluate,
                            node_store, tenant_id,
                            fn_kwargs={
                                "original_resume": resume_text,
                                "tailored_text": sections_text,
                                "jd_text": truncate_text(jd_text, MAX_JD_CONTEXT_CHARS),
                                "diffs": report.tailored_resume.diffs,
                            },
                        )
                        report.eval_score = eval_result
                    except Exception as exc:
                        # Eval is a bonus stage: never let it destroy an
                        # otherwise successful alignment.
                        logger.warning(
                            "Evaluation failed; keeping successful alignment: %s", exc
                        )
                        report.eval_score = None
                else:
                    try:
                        report.eval_score = evaluate(
                            tailor_client,
                            resume_text,
                            sections_text,
                            truncate_text(jd_text, MAX_JD_CONTEXT_CHARS),
                            diffs=report.tailored_resume.diffs,
                        )
                    except Exception as exc:
                        # Eval is a bonus stage: never let it destroy an
                        # otherwise successful alignment.
                        logger.warning(
                            "Evaluation failed; keeping successful alignment: %s", exc
                        )
                        report.eval_score = None
        return report
    finally:
        if jd_client_owned:
            jd_client.close()
        if tailor_client_owned:
            tailor_client.close()
        if llm_client is None:
            client.close()


