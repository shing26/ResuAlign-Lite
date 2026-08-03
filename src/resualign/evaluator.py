from .models import EvalScore

EVAL_PROMPT = (
    "You are a resume quality judge. "
    "Return JSON with jd_match_score (0-100), improvement (0-100), "
    "hallucination_detected (bool), hallucination_details (list), "
    "gap_coverage (0.0-1.0). Output ONLY JSON."
)

def evaluate(client, original_resume, tailored_text, jd_text):
    user = f"Original:{original_resume} Tailored:{tailored_text} JD:{jd_text}"
    result = client.chat_json(EVAL_PROMPT, user)
    return EvalScore(
        jd_match_score=result.get("jd_match_score", 0),
        improvement=result.get("improvement", 0),
        hallucination_detected=result.get("hallucination_detected", False),
        hallucination_details=result.get("hallucination_details", []),
        gap_coverage=result.get("gap_coverage", 0.0),
    )
