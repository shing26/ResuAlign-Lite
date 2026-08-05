from .llm import LLMClient
from .models import GapReport

GAP_ANALYSIS_PROMPT = (
    "You are a resume gap analyst. Given a resume and a structured JD profile, \n"
    "identify gaps. Return JSON with: \n"
    "missing_keywords (list of concrete JD keyword phrases, including the \n"
    "business scenario when the JD pairs it with a skill, e.g. 'Redis caching \n"
    "for high concurrency'; when the JD names a platform-level scenario such \n"
    "as 'high concurrency', include it in the paired phrase), \n"
    "missing_keywords must also include evidence-oriented phrases when the JD \n"
    "asks for deployment, performance, latency, observability, or \n"
    "containerization, e.g. 'production Kubernetes deployment evidence', \n"
    "'low latency performance metrics', 'observability and tracing', 'Docker \n"
    "and Kubernetes deployment workflows'. When the JD pairs a skill with a \n"
    "scenario (e.g., 'Redis caching for high concurrency') and the resume \n"
    "states the skill without the scenario, list the full paired phrase as a \n"
    "missing_keyword even if the skill itself is already a strength, \n"
    "misaligned_emphasis (list of strings), \n"
    "strength_matches (list of strings). \n"
    "Output ONLY JSON."
)


def analyze_gaps(client: LLMClient, resume_text: str, jd_profile_text: str) -> GapReport:
    user = f"Resume:\n{resume_text}\n\nJD Profile:\n{jd_profile_text}"
    result = client.chat_json(GAP_ANALYSIS_PROMPT, user)
    return GapReport(
        missing_keywords=result.get("missing_keywords", []),
        misaligned_emphasis=result.get("misaligned_emphasis", []),
        strength_matches=result.get("strength_matches", []),
    )
