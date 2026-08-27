from resualign.evaluator import evaluate
from resualign.llm import OpenAIClient
from resualign.models import ResuAlignConfig
from resualign.tailor import tailor_resume

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


def test_section_prefix_provenance_is_verified():
    resume = "工作经历\n- 使用 Python 开发后端服务"
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {"工作经历": "使用 Python 开发后端服务"},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "工作经历",
                        "original": "使用 Python 开发后端服务",
                        "proposed": "使用 Python 构建高并发后端服务",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "工作经历: 使用 Python 开发后端服务",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, "Gap report")
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance_state == "verified"
    assert result.diffs[0].source_span is not None
    assert result.invalid_diffs == []


def test_fullwidth_colon_section_prefix_is_verified():
    resume = "项目经历\n- 搭建 Redis 缓存层"
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {"项目经历": "搭建 Redis 缓存层"},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "项目经历",
                        "original": "搭建 Redis 缓存层",
                        "proposed": "搭建 Redis 缓存层并降低延迟",
                        "reason": "JD match",
                        "confidence": "medium",
                        "provenance_quote": "项目经历：搭建 Redis 缓存层",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, "Gap report")
    assert result.diffs[0].provenance_state == "verified"
    expected_start = resume.find("搭建 Redis 缓存层")
    assert result.diffs[0].source_span == (
        expected_start,
        expected_start + len("搭建 Redis 缓存层"),
    )


def test_section_prefix_prefers_matching_section_for_duplicate_line():
    resume = (
        "工作经历\n- 使用 Python 开发后端服务\n"
        "项目经历\n- 使用 Python 开发后端服务"
    )
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {"项目经历": "使用 Python 开发后端服务"},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "项目经历",
                        "original": "使用 Python 开发后端服务",
                        "proposed": "使用 Python 开发高可用后端服务",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "项目经历: 使用 Python 开发后端服务",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, "Gap report")
    assert result.diffs[0].provenance_state == "verified"
    second_start = resume.find("使用 Python 开发后端服务", resume.find("项目经历"))
    assert result.diffs[0].source_span[0] == second_start


def test_missing_modify_provenance_stays_in_invalid_diffs():
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "项目经历",
                        "original": "Invented line",
                        "proposed": "Rewritten line",
                        "reason": "JD match",
                        "confidence": "medium",
                        "provenance_quote": "Invented line",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, "工作经历\n- 使用 Python 开发后端服务", "Gap report")
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    assert result.invalid_diffs[0].provenance_state == "missing"
    assert result.invalid_diffs[0].source_span is None


def test_missing_diff_does_not_invalidate_verified_batch_mate():
    resume = "工作经历\n- 使用 Python 开发后端服务"
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {"工作经历": "使用 Python 开发后端服务"},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "工作经历",
                        "original": "使用 Python 开发后端服务",
                        "proposed": "使用 Python 构建高并发后端服务",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "工作经历: 使用 Python 开发后端服务",
                    },
                    {
                        "type": "modify",
                        "section": "工作经历",
                        "original": "Invented Kubernetes",
                        "proposed": "Managed Kubernetes",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "Invented Kubernetes",
                    },
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, "Gap report")
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance_state == "verified"
    assert len(result.invalid_diffs) == 1
    assert result.invalid_diffs[0].provenance_state == "missing"


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
