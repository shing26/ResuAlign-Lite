import json

from resualign.evaluator import evaluate
from resualign.llm import OpenAIClient
from resualign.models import DiffItem, ResuAlignConfig, TailoredResume
from resualign.tailor import (
    METRIC_PLACEHOLDER,
    _unsupported_content,
    derive_section_diffs,
    rewrite_bullet,
    tailor_resume,
)

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


# ---------------------------------------------------------------------------
# P0（2026-09-06 安全审查 #74/#75/#76）：proposed 内容级校验、sections
# 派生旁路封堵、rewrite 洗白封堵。
# ---------------------------------------------------------------------------


def test_fabricated_number_in_proposed_is_blocked():
    """锚点真实但 proposed 编造简历中不存在的数字 → 拦截为 fabricated。"""
    resume = "工作经历\n- 使用 Redis 做缓存与会话管理"
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "工作经历",
                        "original": "使用 Redis 做缓存与会话管理",
                        "proposed": "使用 Redis 支撑日均 500 万订单",
                        "reason": "JD 强调高并发",
                        "confidence": "high",
                        "provenance_quote": "使用 Redis 做缓存与会话管理",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, "Gap report")
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    blocked = result.invalid_diffs[0]
    assert blocked.provenance_state == "fabricated"
    assert "500" in blocked.reason
    assert "已拦截" in blocked.reason


def test_fabricated_org_in_chinese_proposed_is_blocked():
    """中文语境下 proposed 出现简历/JD 都没有的专名 → 拦截。"""
    resume = "项目经历\n- 搭建 Redis 缓存层"
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "项目经历",
                        "original": "搭建 Redis 缓存层",
                        "proposed": "主导 Stanford 大学 20 人团队的缓存建设",
                        "reason": "JD match",
                        "confidence": "high",
                        "provenance_quote": "搭建 Redis 缓存层",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, "Gap report")
    assert result.diffs == []
    blocked = result.invalid_diffs[0]
    assert blocked.provenance_state == "fabricated"
    assert "Stanford" in blocked.reason
    assert "20" in blocked.reason


def test_jd_context_terminology_in_proposed_passes():
    """JD 语料（gap_report jd_context）允许术语复述，不算编造。"""
    resume = "项目经历\n- 搭建 Redis 缓存层"
    gap = json.dumps(
        {
            "missing_keywords": [],
            "misaligned_emphasis": [],
            "strength_matches": [],
            "business_scenarios": [],
            "jd_context": "要求熟悉 Kubernetes production deployment",
        },
        ensure_ascii=False,
    )
    client = SchemaAwareLLMClient(
        [
            {
                "sections": {},
                "diffs": [
                    {
                        "type": "modify",
                        "section": "项目经历",
                        "original": "搭建 Redis 缓存层",
                        "proposed": "搭建 Redis 缓存层支撑 Kubernetes production deployment",
                        "reason": "JD 术语对齐",
                        "confidence": "high",
                        "provenance_quote": "搭建 Redis 缓存层",
                    }
                ],
            }
        ]
    )
    result = tailor_resume(client, resume, gap)
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance_state == "verified"
    assert result.invalid_diffs == []


def test_metric_placeholder_is_exempt_from_support_check():
    """[待人工确认：…] 占位符是待补齐标注，其 QPS/X% 不触发拦截。"""
    unsupported = _unsupported_content(
        f"构建高吞吐服务 {METRIC_PLACEHOLDER}", "构建高吞吐服务"
    )
    assert unsupported == []


def test_derive_section_diffs_blocked_when_strict_gate_rejected_all_diffs():
    """#75：strict 门滤掉全部 diffs 时（invalid_diffs 非空），整章派生
    不得把未校验 sections 包装成 verified（确定性绕过放大器）。"""
    resume = "# 项目经历\n1. 现有项目描述\n"
    tailored = TailoredResume(
        sections={"项目经历": "1. 未经验证的整章重写"},
        diffs=[],
        invalid_diffs=[DiffItem(diff_id="bad", provenance_state="missing")],
    )
    assert derive_section_diffs(tailored, resume) == []


def test_rewrite_bullet_flags_fabricated_number():
    """#76：重写产物编造 original/JD 都没有的数字 → 不标 verified。"""
    mock = SchemaAwareLLMClient(
        [{"proposed": "主导支撑日均 500 万订单的订单中台", "reason": "量化"}]
    )
    diff = rewrite_bullet(mock, "负责订单服务开发", "quantified")
    assert diff.provenance_state == "fabricated"
    assert "500" in diff.reason
    assert "已拦截" in diff.reason


def test_rewrite_bullet_keeps_supported_rewrite_verified():
    mock = SchemaAwareLLMClient(
        [{"proposed": "使用 Redis 构建高并发缓存层", "reason": "术语对齐"}]
    )
    diff = rewrite_bullet(mock, "使用 Redis 做缓存", "high_concurrency")
    assert diff.provenance_state == "verified"
    assert "已拦截" not in diff.reason


def test_rewrite_bullet_cached_fabricated_content_is_flagged():
    """#76：缓存命中的产物同样过内容级校验，旧缓存里的编造内容不得
    借缓存通道洗白。"""
    captured = {}

    class FakeCache:
        def get(self, tenant, model, version, content):
            captured["get"] = True
            return {"proposed": "支撑日均 500 万订单的服务", "reason": "旧缓存"}

        def put(self, *args):
            captured["put"] = True

    mock = SchemaAwareLLMClient([])
    diff = rewrite_bullet(
        mock, "负责订单服务开发", "quantified", cache=FakeCache()
    )
    assert captured.get("get") is True
    assert "put" not in captured
    assert diff.provenance_state == "fabricated"
