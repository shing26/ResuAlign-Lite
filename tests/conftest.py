from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class MockLLMClient:
    """Sequence-based fake LLM client for unit testing pipeline stages.

    Each call to ``chat_json`` consumes the next response from *responses*.
    Records calls for later assertion.
    """

    def __init__(self, responses=None):
        self.responses = list(responses or [
            {"score": 80, "skills": ["Python", "Java"], "issues": []},
        ])
        self.call_count = 0
        self.calls = []

    def chat_json(self, system, user, model=None):
        self.calls.append((system[:50], user[:50]))
        if self.call_count < len(self.responses):
            r = self.responses[self.call_count]
            self.call_count += 1
            return r
        return {}


def _diag(score=80):
    return {"score": score, "skills": ["Python"], "issues": []}


def _profile():
    return {"must_have_skills": ["Java"], "nice_to_have_skills": ["Redis"],
            "soft_skills": [], "business_scenarios": ["Microservices"],
            "min_years_experience": None, "education_requirements": []}


def _gap():
    return {"missing_keywords": ["Redis"], "misaligned_emphasis": [],
            "strength_matches": ["Java"]}


def _jd_analysis():
    return {"jd_profile": _profile(), "gap_report": _gap()}


def _tailor():
    return {"sections": {"experience": "Built services using Java"},
            "diffs": [{"type": "modify", "original": "old", "proposed": "new",
                        "reason": "match", "confidence": "high", "provenance": "old"}]}


def _eval():
    return {"jd_match_score": 82, "improvement": 12,
            "hallucination_detected": False, "hallucination_details": [],
            "gap_coverage": 0.75}


@pytest.fixture(scope="session")
def sample_pdf():
    """Dynamically generate a minimal PDF fixture using PyMuPDF."""
    path = FIXTURES / "sample.pdf"
    if not path.exists():
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Python developer resume.\nJava experience.\nSpring Boot.")
        doc.save(str(path))
        doc.close()
    return path


@pytest.fixture(scope="session")
def sample_txt():
    return FIXTURES / "sample.txt"


@pytest.fixture(scope="session")
def sample_docx():
    """Dynamically generate a minimal DOCX fixture."""
    path = FIXTURES / "sample.docx"
    if not path.exists():
        from docx import Document
        doc = Document()
        doc.add_paragraph("Python developer resume.")
        doc.add_paragraph("Java experience.")
        doc.save(str(path))
    return path
