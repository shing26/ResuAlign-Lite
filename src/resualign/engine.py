from __future__ import annotations

import logging
from typing import Callable, Optional

from .evaluator import evaluate
from .extractor import extract_structured
from .gap_analyzer import analyze_gaps
from .jd_analysis import jd_profile_to_dict
from .jd_profiler import profile_jd
from .llm import LLMClient, LLMResponseError, OpenAIClient, diagnose_resume
from .llm_nodes import LLMNodeStore
from .models import GapReport, Report, ResuAlignConfig
from .role_router import _role_timeout, call_with_role
from .rule_diagnose import diagnose_resume_local
from .tailor import tailor_resume

logger = logging.getLogger(__name__)

MAX_JD_INPUT_CHARS = 8000
MAX_JD_CONTEXT_CHARS = 6000
# Tailoring is the longest single stage. Two attempts keep a degraded
# provider from multiplying a slow response into a six-minute failure.
TAILOR_MAX_RETRIES = 1

# Defensive cap on resume input so an exceptionally long resume cannot
# blow out prompt size and slow the LLM calls. Typical resumes (2-3k
# chars) are far below this limit.
MAX_RESUME_INPUT_CHARS = 15000


def _bullet_editor_enabled(granularity: str) -> bool:
    """Whether the bullet-level map-reduce editor should be used.

    Enabled for fine/medium granularity by default; override with
    ``RESUALIGN_BULLET_EDITOR=0``. Coarse restructuring always keeps the
    whole-document path.
    """
    if os.environ.get("RESUALIGN_BULLET_EDITOR", "1") != "1":
        return False
    return granularity in {"fine", "medium"}


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
                tailor_result, _ = call_with_role(
                    "editor", tailor_resume,
                    node_store, tenant_id,
                    fn_kwargs={
                        "resume_text": resume_text,
                        "gap_report_text": gap_report_str,
                        "granularity": granularity,
                        "prompt_focus": prompt_focus,
                        "custom_prompt": custom_prompt,
                    },
                )
                report.tailored_resume = tailor_result
            else:
                if llm_client is None:
                    tailor_client = OpenAIClient(
                        config,
                        timeout=_role_timeout("editor"),
                        max_retries=TAILOR_MAX_RETRIES,
                    )
                    tailor_client_owned = True
                report.tailored_resume = tailor_resume(
                    tailor_client,
                    resume_text,
                    gap_report_str,
                    granularity=granularity,
                    prompt_focus=prompt_focus,
                    custom_prompt=custom_prompt,
                )

            # Diffs from tailor_resume replace the old legacy alignment diffs
            report.diffs = report.tailored_resume.diffs

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
                                "tailored_resume": sections_text,
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


def run_with_graph(
    config,
    resume_text,
    jd_text=None,
    llm_client=None,
    run_eval=False,
    granularity="medium",
    prompt_focus="balanced",
    custom_prompt="",
    diagnosis=None,
    on_stage=None,
    cache=None,
    tenant="default",
    node_store=None,
    tenant_id="default",
):
    """Run the alignment pipeline through the GraphExecutor (Compound AI)."""
    from .graph import AlignmentState, GraphExecutor

    try:
        state = AlignmentState(
            job_id=tenant_id,
            resume_text=resume_text,
            jd_text=jd_text or "",
            granularity=granularity,
            prompt_focus=prompt_focus,
            custom_prompt=custom_prompt,
            run_eval=run_eval,
        )

        def _llm_runner(st, node):
            role = node.get("role", "")
            if role == "profiler":
                from .extractor import extract_structured
                from .jd_profiler import profile_jd
                extracted = extract_structured(st.jd_text)
                filtered_jd = "\n\n".join(v for v in extracted.values() if v)
                jd_input = truncate_text(filtered_jd or st.jd_text, MAX_JD_INPUT_CHARS)
                if node_store and node_store.get_active_node(tenant_id):
                    prof_result, _ = call_with_role("profiler", profile_jd, node_store, tenant_id, fn_kwargs={"jd_text": jd_input, "cache": cache, "tenant": tenant})
                else:
                    prof_client = OpenAIClient(config, timeout=node.get("timeout", 15.0))
                    try:
                        prof_result = profile_jd(prof_client, jd_input, cache=cache, tenant=tenant)
                    finally:
                        prof_client.close()
                st.jd_profile = prof_result
                return {"type": "jd_profile", "data": prof_result}

            elif role == "gap_analyzer":
                import json as _json

                from .gap_analyzer import analyze_gaps
                from .jd_analysis import jd_profile_to_dict
                profile_str = _json.dumps(jd_profile_to_dict(st.jd_profile or {}), ensure_ascii=False)
                if node_store and node_store.get_active_node(tenant_id):
                    gap_result, _ = call_with_role("gap_analyzer", analyze_gaps, node_store, tenant_id, fn_kwargs={"resume_text": st.resume_text, "jd_profile_text": profile_str})
                else:
                    gap_client = OpenAIClient(config, timeout=node.get("timeout", 15.0))
                    try:
                        gap_result = analyze_gaps(gap_client, st.resume_text, profile_str)
                    finally:
                        gap_client.close()
                st.gap_report = gap_result
                return {"type": "gap_report", "data": gap_result}

            elif role in ("editor", "tailor", "editor_general"):
                import json as _json

                from .tailor import tailor_resume
                gap_dict = {}
                if st.gap_report:
                    gap_dict = {
                        "missing_keywords": st.gap_report.get("missing_keywords", []) if isinstance(st.gap_report, dict) else (st.gap_report.missing_keywords if hasattr(st.gap_report, "missing_keywords") else []),
                        "misaligned_emphasis": st.gap_report.get("misaligned_emphasis", []) if isinstance(st.gap_report, dict) else (st.gap_report.misaligned_emphasis if hasattr(st.gap_report, "misaligned_emphasis") else []),
                        "strength_matches": st.gap_report.get("strength_matches", []) if isinstance(st.gap_report, dict) else (st.gap_report.strength_matches if hasattr(st.gap_report, "strength_matches") else []),
                        "business_scenarios": st.jd_profile.get("business_scenarios", []) if isinstance(st.jd_profile, dict) else (st.jd_profile.business_scenarios if hasattr(st.jd_profile, "business_scenarios") else []),
                        "jd_context": truncate_text(st.jd_text, MAX_JD_CONTEXT_CHARS),
                    }
                gap_report_str = _json.dumps(gap_dict, ensure_ascii=False)
                if node_store and node_store.get_active_node(tenant_id):
                    editor_kwargs = {"resume_text": st.resume_text, "gap_report_text": gap_report_str, "granularity": st.granularity, "prompt_focus": st.prompt_focus, "custom_prompt": st.custom_prompt}
                    if _bullet_editor_enabled(st.granularity):
                        editor_fn = tailor_resume_map_reduce
                        editor_kwargs["jd_context"] = truncate_text(st.jd_text, MAX_JD_CONTEXT_CHARS)
                        editor_kwargs["parallel"] = is_parallel_safe(node_store, tenant_id, "editor")
                    else:
                        editor_fn = tailor_resume
                    tailor_result, _ = call_with_role("editor", editor_fn, node_store, tenant_id, fn_kwargs=editor_kwargs)
                else:
                    tailor_client = OpenAIClient(config, timeout=node.get("timeout", 40.0), max_retries=1)
                    try:
                        tailor_result = tailor_resume(tailor_client, st.resume_text, gap_report_str, granularity=st.granularity, prompt_focus=st.prompt_focus, custom_prompt=st.custom_prompt)
                    finally:
                        tailor_client.close()
                st.tailored_draft = tailor_result
                return {"type": "tailored_draft", "data": tailor_result}

            elif role in ("evaluator", "eval", "evaluator_general"):
                from .evaluator import evaluate
                if not st.tailored_draft:
                    return {"type": "eval_score", "data": None}
                sections_text = "\n".join(st.tailored_draft.get("sections", {}).values()) if isinstance(st.tailored_draft, dict) else st.resume_text
                diffs = st.tailored_draft.get("diffs", []) if isinstance(st.tailored_draft, dict) else []
                if node_store and node_store.get_active_node(tenant_id):
                    eval_result, _ = call_with_role("evaluator", evaluate, node_store, tenant_id, fn_kwargs={"original_resume": st.resume_text, "tailored_resume": sections_text, "jd_text": truncate_text(st.jd_text, MAX_JD_CONTEXT_CHARS), "diffs": diffs})
                else:
                    eval_client = OpenAIClient(config, timeout=node.get("timeout", 30.0))
                    try:
                        eval_result = evaluate(eval_client, st.resume_text, sections_text, truncate_text(st.jd_text, MAX_JD_CONTEXT_CHARS), diffs=diffs)
                    finally:
                        eval_client.close()
                st.eval_score = eval_result
                return {"type": "eval_score", "data": eval_result}

            return {"type": "unknown", "data": None}

        executor = GraphExecutor(llm_runner=_llm_runner)
        if on_stage:
            on_stage("graph", "Running Compound AI pipeline...")
        result_state = executor.run(state)

        report = Report(score=0, skills=[], issues=[], model=config.model)
        if result_state.jd_profile:
            report.jd_profile = result_state.jd_profile
        if result_state.gap_report:
            report.gap_report = result_state.gap_report
        if result_state.tailored_draft:
            report.tailored_resume = result_state.tailored_draft
            report.diffs = result_state.tailored_draft.get("diffs", [])
        if result_state.eval_score:
            report.eval_score = result_state.eval_score
        report.provenance_ratio = result_state.provenance_ratio
        report.graph_status = result_state.status.value
        report.trace_id = result_state.trace_id

        if on_stage:
            on_stage("graph_complete", "Pipeline " + result_state.status.value)
        return report

    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("GraphExecutor pipeline failed: %s", exc)
        if on_stage:
            on_stage("graph_fallback", "Graph pipeline failed, falling back to legacy...")
        return run(
            config=config, resume_text=resume_text, jd_text=jd_text,
            llm_client=llm_client, run_eval=run_eval, granularity=granularity,
            prompt_focus=prompt_focus, custom_prompt=custom_prompt,
            diagnosis=diagnosis, on_stage=on_stage, cache=cache,
            tenant=tenant, node_store=node_store, tenant_id=tenant_id,
        )
