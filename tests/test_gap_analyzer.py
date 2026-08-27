from resualign.gap_analyzer import analyze_gaps
from resualign.models import GapReport


class MockLLM:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "missing_keywords": ["Kubernetes", "Redis"],
            "misaligned_emphasis": ["Focus on frontend instead of backend"],
            "strength_matches": ["Java experience aligns well"],
        }
        self.last_system = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        return self.result


def test_analyze_gaps_returns_gapreport():
    mock = MockLLM()
    report = analyze_gaps(mock, "Resume text...", "JD profile...")
    assert isinstance(report, GapReport)
    assert "Kubernetes" in report.missing_keywords


def test_analyze_gaps_empty_results():
    mock = MockLLM(result={})
    report = analyze_gaps(mock, "Resume", "JD")
    assert report.missing_keywords == []


def test_analyze_gaps_prompt_mentions_gap():
    mock = MockLLM()
    _ = analyze_gaps(mock, "Resume", "JD")
    # R4: 04b-PE §2.3 新提示词已中文化，首行版本标记作为稳定断言锚点。
    assert "PROMPT_VERSION: gap_analyzer/v2" in mock.last_system
