from typing import Callable, Optional

from .models import Report, ResuAlignConfig
from .llm import LLMClient, OpenAIClient, DIAG_PROMPT
from .jd_analysis import profile_and_gaps
from .tailor import tailor_resume
from .evaluator import evaluate
from .extractor import extract_structured


MAX_JD_INPUT_CHARS = 8000
MAX_JD_CONTEXT_CHARS = 6000


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
) -> Report:
    """Run the full pipeline: diagnose + optional alignment.

    ``diagnosis`` carries a previously computed no-JD diagnosis so repeated
    workbench runs on the same resume skip one LLM round trip.
    """
    client = llm_client or OpenAIClient(config)
    try:
        def notify(stage: str, message: str) -> None:
            if on_stage is not None:
                on_stage(stage, message)

        notify("diagnose", "Analyzing resume...")
        if diagnosis is not None:
            diag_result = diagnosis
        else:
            diag_result = client.chat_json(DIAG_PROMPT, resume_text)

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
                client, resume_text, jd_input
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
            report.tailored_resume = tailor_resume(
                client,
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
                    client,
                    resume_text,
                    sections_text,
                    truncate_text(jd_text, MAX_JD_CONTEXT_CHARS),
                )
        return report
    finally:
        if llm_client is None:
            client.close()
