from resualign.evaluator import evaluate
from resualign.tailor import tailor_resume
from resualign.llm import OpenAIClient
from resualign.models import ResuAlignConfig

from .conftest import SchemaAwareLLMClient


def test_valid_provenance_quote_passes_hard_gate():
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {"experience": "Built backend services"},
                "diffs": [
                    {
                        "type": "modify",
                        "original": "Built backend",
                        "proposed": "Built scalable backend",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "Built backend",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, "Built backend services", "Gap report")
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance_quote == "Built backend"
    assert result.diffs[0].source_span == (0, 13)
    assert result.invalid_diffs == []


def test_invented_provenance_is_dropped_and_flagged():
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {},
                "diffs": [
                    {
                        "type": "modify",
                        "original": "Invented Kubernetes",
                        "proposed": "Managed Kubernetes",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "Invented Kubernetes",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, "Built backend services", "Gap report")
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    assert result.invalid_diffs[0].source_span is None


def test_add_with_empty_original_goes_to_invalid_diffs():
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {},
                "diffs": [
                    {
                        "type": "add",
                        "original": "",
                        "proposed": "New JD-aligned line",
                        "reason": "JD match",
                        "confidence": "medium",
                        "provenance_quote": "not in resume",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, "Built backend services", "Gap report")
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    assert result.invalid_diffs[0].source_span is None
    assert result.invalid_diffs[0].provenance_state == "missing"


def test_evaluator_marks_invalid_diff_provenance_as_hallucination():
    client = SchemaAwareLLMClient(
        [
            {
                "jd_match_score": 80,
                "improvement": 10,
                "hallucination_detected": False,
                "hallucination_details": [],
                "gap_coverage": "0.75",
            }
        ]
    )
    score = evaluate(
        client,
        "Built backend services",
        "Built scalable backend",
        "JD text",
        diffs=[{"type": "modify", "provenance": "Invented fact"}],
    )
    assert score.hallucination_detected is True
    assert "Invented fact" in score.hallucination_details[0]
    assert score.gap_coverage == 0.75


def test_evaluator_keeps_valid_diff_provenance_clean():
    client = SchemaAwareLLMClient(
        [
            {
                "jd_match_score": 85,
                "improvement": 12,
                "hallucination_detected": False,
                "hallucination_details": [],
                "gap_coverage": 0.8,
            }
        ]
    )
    score = evaluate(
        client,
        "Built backend services",
        "Built scalable backend",
        "JD text",
        diffs=[{"type": "modify", "provenance_quote": "Built backend"}],
    )
    assert score.hallucination_detected is False
    assert score.gap_coverage == 0.8


def test_production_client_drops_invented_provenance(httpx_mock):
    client = OpenAIClient(
        ResuAlignConfig(
            provider="deepseek",
            api_key="sk-test",
            model="test-model",
        )
    )
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"sections":{},"diffs":[{"type":"modify",'
                            '"original":"Invented Kubernetes",'
                            '"proposed":"Managed Kubernetes",'
                            '"reason":"JD match","confidence":"high",'
                            '"provenance_quote":"Invented Kubernetes"}]}'
                        )
                    }
                }
            ]
        }
    )
    result = tailor_resume(
        client,
        "Built backend services",
        "Gap report",
    )
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    client.close()
