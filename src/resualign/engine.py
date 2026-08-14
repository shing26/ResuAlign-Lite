from typing import Callable, Optional

from .evaluator import evaluate
from .extractor import extract_structured
from .jd_analysis import profile_and_gaps
from .llm import LLMClient, OpenAIClient, diagnose_resume
from .models import Report, ResuAlignConfig
from .tailor import tailor_resume

MAX_JD_INPUT_CHARS = 8000
MAX_JD_CONTEXT_CHARS = 6000
TAILOR_LLM_TIMEOUT = 120.0


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
) -> Report:
    """Run the full pipeline: diagnose + optional alignment.

    ``diagnosis`` carries a previously computed no-JD diagnosis so repeated
    workbench runs on the same resume skip one LLM round trip.
    """
    client = llm_client or OpenAIClient(config)
    tailor_client = client
    tailor_client_owned = False
    try:
        def notify(stage: str, message: str) -> None:
            if on_stage is not None:
                on_stage(stage, message)

        notify("diagnose", "Analyzing resume...")
        if diagnosis is not None:
            diag_result = diagnosis
        else:
            diag_result = diagnose_resume(
                client,
                resume_text,
                cache=cache,
                tenant=tenant,
                model=config.model,
            )

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
                "Extracting JD profile and analyzing gaps...",
            )
            report.jd_profile, report.gap_report = profile_and_gaps(
                client,
                resume_text,
                jd_input,
                cache=cache,
                tenant=tenant,
            )

            # Tailoring
            notify("tailoring", "Tailoring resume to JD...")
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
            if llm_client is None:
                tailor_client = OpenAIClient(
                    config, timeout=TAILOR_LLM_TIMEOUT
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
                notify("evaluation", "Evaluating tailored resume...")
                sections_text = "\n".join(
                    report.tailored_resume.sections.values()
                ) if report.tailored_resume.sections else resume_text
                report.eval_score = evaluate(
                    tailor_client,
                    resume_text,
                    sections_text,
                    truncate_text(jd_text, MAX_JD_CONTEXT_CHARS),
                    diffs=report.tailored_resume.diffs,
                )
        return report
    finally:
        if tailor_client_owned:
            tailor_client.close()
        if llm_client is None:
            client.close()
