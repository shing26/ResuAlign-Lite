from resualign.evaluator import evaluate
from resualign.models import EvalScore

class MockLLM:
    def __init__(self, result=None):
        self.result = result if result is not None else {
            "jd_match_score": 85,
            "improvement": 15,
            "hallucination_detected": False,
            "hallucination_details": [],
            "gap_coverage": 0.8,
        }
        self.last_system = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        return self.result

def test_evaluate_returns_eval_score():
    mock = MockLLM()
    score = evaluate(mock, "orig", "tailored", "jd")
    assert isinstance(score, EvalScore)
    assert score.jd_match_score == 85
    assert score.gap_coverage == 0.8

def test_evaluate_empty_results():
    mock = MockLLM(result={})
    score = evaluate(mock, "a", "b", "c")
    assert score.jd_match_score == 0
    assert score.hallucination_detected == False
    assert score.gap_coverage == 0.0

def test_evaluate_hallucination_detected():
    mock = MockLLM(result={
        "jd_match_score": 60, "improvement": 10,
        "hallucination_detected": True,
        "hallucination_details": ["Claimed Kubernetes experience"],
        "gap_coverage": 0.5,
    })
    score = evaluate(mock, "orig", "tailored", "jd")
    assert score.hallucination_detected == True
    assert "Kubernetes" in score.hallucination_details[0]
