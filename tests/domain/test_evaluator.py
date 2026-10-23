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
    assert not score.hallucination_detected
    assert score.gap_coverage == 0.0

def test_evaluate_hallucination_detected():
    mock = MockLLM(result={
        "jd_match_score": 60, "improvement": 10,
        "hallucination_detected": True,
        "hallucination_details": ["Claimed Kubernetes experience"],
        "hallucinated_diff_ids": ["diff-2"],
        "gap_coverage": 0.5,
    })
    score = evaluate(
        mock,
        "orig",
        "tailored",
        "jd",
        diffs=[
            {
                "diff_id": "diff-2",
                "type": "modify",
                "original": "orig",
                "proposed": "tailored",
                "provenance": "orig",
            }
        ],
    )
    assert score.hallucination_detected
    assert score.hallucinated_diff_ids == ["diff-2"]
    assert "Kubernetes" in score.hallucination_details[0]


def test_evaluate_maps_invalid_provenance_to_diff_id():
    mock = MockLLM(result={
        "jd_match_score": 80,
        "improvement": 10,
        "hallucination_detected": False,
        "hallucination_details": [],
        "hallucinated_diff_ids": [],
        "gap_coverage": 0.5,
    })
    score = evaluate(
        mock,
        "Built backend services",
        "Built scalable backend",
        "jd",
        diffs=[
            {
                "diff_id": "diff-valid",
                "type": "modify",
                "provenance_quote": "Built backend services",
            },
            {
                "diff_id": "diff-invalid",
                "type": "modify",
                "provenance_quote": "Invented fact",
            },
        ],
    )
    assert score.hallucination_detected is True
    assert score.hallucinated_diff_ids == ["diff-invalid"]


def test_nonempty_hallucinated_ids_force_detection():
    mock = MockLLM(result={
        "jd_match_score": 80,
        "improvement": 10,
        "hallucination_detected": False,
        "hallucination_details": [],
        "hallucinated_diff_ids": ["diff-2"],
        "gap_coverage": 0.5,
    })
    score = evaluate(
        mock,
        "orig",
        "tailored",
        "jd",
        diffs=[
            {
                "diff_id": "diff-2",
                "type": "modify",
                "original": "orig",
                "proposed": "tailored",
                "provenance": "orig",
            }
        ],
    )

    assert score.hallucination_detected is True
    assert score.hallucinated_diff_ids == ["diff-2"]


def test_unknown_hallucinated_id_falls_back_to_global_block():
    mock = MockLLM(result={
        "jd_match_score": 80,
        "improvement": 10,
        "hallucination_detected": False,
        "hallucination_details": [],
        "hallucinated_diff_ids": ["not-in-input"],
        "gap_coverage": 0.5,
    })
    score = evaluate(
        mock,
        "orig",
        "tailored",
        "jd",
        diffs=[
            {
                "diff_id": "diff-2",
                "type": "modify",
                "original": "orig",
                "proposed": "tailored",
                "provenance": "orig",
            }
        ],
    )

    assert score.hallucination_detected is True
    assert score.hallucinated_diff_ids == []
