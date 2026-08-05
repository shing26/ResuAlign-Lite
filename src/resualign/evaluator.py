from .llm import _structured_or_json
from .models import EvalScore
from .schema_registry import EvalScoreSchema
from .tailor import parse_diff_with_provenance

EVAL_PROMPT = (
    "You are a resume quality judge. "
    "Return JSON with jd_match_score (0-100), improvement (0-100), "
    "hallucination_detected (bool), hallucination_details (list), "
    "gap_coverage (0.0-1.0). Output ONLY JSON."
)

def evaluate(client, original_resume, tailored_text, jd_text, diffs=None):
    user = f"Original:{original_resume} Tailored:{tailored_text} JD:{jd_text}"
    result = _structured_or_json(client, EVAL_PROMPT, user, EvalScoreSchema)
    hallucination_detected = bool(result.get("hallucination_detected", False))
    try:
        gap_coverage = float(result.get("gap_coverage", 0.0))
    except (TypeError, ValueError):
        gap_coverage = 0.0
    gap_coverage = max(0.0, min(1.0, gap_coverage))
    hallucination_details = list(result.get("hallucination_details") or [])
    if diffs:
        for diff in diffs:
            if isinstance(diff, dict):
                _, valid = parse_diff_with_provenance(diff, original_resume)
                quote = str(
                    diff.get("provenance_quote")
                    or diff.get("provenance")
                    or ""
                ).strip()
            else:
                quote = str(
                    getattr(diff, "provenance_quote", "")
                    or getattr(diff, "provenance", "")
                    or ""
                ).strip()
                original = str(getattr(diff, "original", "") or "")
                valid = bool(
                    quote and quote in original_resume
                ) or (
                    getattr(diff, "type", "") == "add"
                    and not original.strip()
                )
            if not valid:
                hallucination_detected = True
                hallucination_details.append(
                    "Diff provenance not found in original resume: "
                    + (quote or "<empty>")
                )
    return EvalScore(
        jd_match_score=result.get("jd_match_score", 0),
        improvement=result.get("improvement", 0),
        hallucination_detected=hallucination_detected,
        hallucination_details=hallucination_details,
        gap_coverage=gap_coverage,
    )
