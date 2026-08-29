import pytest

from resualign.models import TailoredResume
from resualign.tailor import (
    METRIC_PLACEHOLDER,
    _ensure_metric_placeholder,
    _has_quantified_metric,
    parse_diff_with_provenance,
    rewrite_bullet,
    tailor_resume,
)


class MockLLM:
    def __init__(self, result=None):
        self.result = result or {
            "sections": {
                "experience": "Built high-throughput backend services using Java."
            },
            "diffs": [{
                "type": "modify",
                "original": "Worked on backend",
                "proposed": "Built high-throughput backend services",
                "reason": "JD emphasizes performance",
                "confidence": "high",
                "provenance": "Worked on backend",
            }],
        }
        self.last_system = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        return self.result


def test_tailor_resume_returns_tailoredresume():
    mock = MockLLM()
    result = tailor_resume(mock, "Resume text...", "Gap report...")
    assert isinstance(result, TailoredResume)
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance == "Worked on backend"


def test_tailor_resume_empty_diffs():
    mock = MockLLM(result={"sections": {}, "diffs": []})
    result = tailor_resume(mock, "Resume", "Gap")
    assert len(result.diffs) == 0
    assert result.sections == {}


def test_tailor_resume_provenance_tracked():
    mock = MockLLM()
    result = tailor_resume(mock, "Resume", "Gap")
    assert all(d.provenance != "" for d in result.diffs)


def test_tailor_resume_normalizes_enum_values():
    mock = MockLLM(result={
        "sections": {},
        "diffs": [{
            "type": "rephrase",
            "original": "old",
            "proposed": "new",
            "reason": "JD match",
            "confidence": 0.7,
            "provenance": "old",
        }],
    })
    result = tailor_resume(mock, "Resume", "Gap")
    assert result.diffs[0].type == "modify"
    assert result.diffs[0].confidence == "medium"


def test_tailor_diff_section_filled_from_llm():
    mock = MockLLM(result={
        "sections": {"项目经历": "Built FastAPI services with Redis caching"},
        "diffs": [{
            "type": "modify",
            "section": "项目经历",
            "original": "Worked on backend",
            "proposed": "Built FastAPI services with Redis caching",
            "reason": "JD emphasizes performance",
            "confidence": "high",
            "provenance": "Worked on backend",
        }],
    })
    result = tailor_resume(mock, "Resume", "Gap")
    assert result.diffs[0].section == "项目经历"


def test_tailor_diff_section_defaults_empty_when_absent():
    mock = MockLLM()
    result = tailor_resume(mock, "Resume", "Gap")
    assert result.diffs[0].section == ""


def test_tailor_prompt_instructs_section_per_diff():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "section" in mock.last_system
    assert "项目经历" in mock.last_system


def test_tailor_prompt_caps_diff_output():
    # R4: 04b-PE §2.5 —— diffs 封顶「≤ 10 条」、reason「≤ 40 字」（旧文案
    # "at most 15 diffs / 80 characters" 已被新契约取代）。
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "≤ 10" in mock.last_system
    assert "≤ 40" in mock.last_system


def test_tailor_granularity_fine_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", granularity="fine")
    assert "fine" in mock.last_system.lower()
    assert "preserve" in mock.last_system.lower()


def test_tailor_granularity_coarse_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", granularity="coarse")
    assert "coarse" in mock.last_system.lower()
    assert "restructure" in mock.last_system.lower()


def test_tailor_granularity_default_is_medium():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "medium" in mock.last_system.lower()


def test_tailor_rejects_invalid_granularity():
    mock = MockLLM()
    with pytest.raises(ValueError, match="granularity"):
        tailor_resume(mock, "Resume", "Gap", granularity="ultra")


def test_tailor_prompt_focus_default_is_balanced():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap")
    assert "balanced" in mock.last_system.lower()


def test_tailor_prompt_focus_quantified_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", prompt_focus="quantified")
    assert "quantified" in mock.last_system.lower()
    assert "never invent or inflate" in mock.last_system.lower()


def test_tailor_prompt_focus_skills_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", prompt_focus="skills")
    assert "exact jd skill and scenario phrases" in mock.last_system.lower()


def test_tailor_custom_prompt_appended():
    mock = MockLLM()
    tailor_resume(mock, "Resume", "Gap", custom_prompt="强调高并发缓存场景")
    assert "USER REQUIREMENTS" in mock.last_system
    assert "强调高并发缓存场景" in mock.last_system
    assert "never instruct you to invent, infer, or fabricate" in mock.last_system


def test_tailor_rejects_invalid_prompt_focus():
    mock = MockLLM()
    with pytest.raises(ValueError, match="prompt_focus"):
        tailor_resume(mock, "Resume", "Gap", prompt_focus="wild")


def test_metric_hint_detects_existing_metrics():
    assert _has_quantified_metric("吞吐量提升 30%") is True
    assert _has_quantified_metric("支撑 QPS 达 1200") is True
    assert _has_quantified_metric("负责高并发服务开发") is False


def test_metric_hint_ignores_ascii_short_tokens_inside_words():
    assert _has_quantified_metric("supports") is False
    assert _has_quantified_metric("art") is False
    assert _has_quantified_metric("123 skills") is False
    assert _has_quantified_metric("ROI") is True
    assert _has_quantified_metric("耗时 3s") is True


def test_ensure_metric_placeholder_appends_only_when_missing():
    assert _ensure_metric_placeholder("") == ""
    assert METRIC_PLACEHOLDER in _ensure_metric_placeholder("构建高吞吐后端服务")
    assert _ensure_metric_placeholder("耗时降低 35%") == "耗时降低 35%"


def test_parse_diff_with_provenance_appends_placeholder_for_unquantified_proposal():
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "original": "负责后端开发",
            "proposed": "构建高吞吐后端服务",
            "provenance": "负责后端开发",
        },
        "负责后端开发",
    )
    assert valid is True
    assert METRIC_PLACEHOLDER in diff.proposed


def test_parse_diff_with_provenance_keeps_existing_metric():
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "original": "吞吐量提升 30%",
            "proposed": "吞吐量提升 30%",
            "provenance": "吞吐量提升 30%",
        },
        "吞吐量提升 30%",
    )
    assert valid is True
    assert diff.proposed == "吞吐量提升 30%"


def test_rewrite_bullet_appends_placeholder_for_quantified_instruction():
    mock = MockLLM(result={"proposed": "构建高吞吐后端服务", "reason": "强调指标"})
    diff = rewrite_bullet(mock, "负责后端开发", "quantified")
    assert METRIC_PLACEHOLDER in diff.proposed


def test_rewrite_bullet_does_not_append_placeholder_for_concise_instruction():
    mock = MockLLM(result={"proposed": "构建高吞吐后端服务", "reason": "精炼"})
    diff = rewrite_bullet(mock, "负责后端开发", "concise")
    assert METRIC_PLACEHOLDER not in diff.proposed


# ---------------------------------------------------------------------------
# Fuzzy provenance salvage (2026-08-30): misquoted quotes that clearly refer
# to a real resume span are recovered instead of discarding the suggestion.
# ---------------------------------------------------------------------------

_FUZZY_RESUME = (
    "陈振成 Java 全栈开发工程师\n"
    "联系方式 132-0000-0000\n"
    "## 工作经历\n"
    "- AI 赋能研发效能: 擅长将 AI 辅助开发融入后端研发全流程，"
    "通过提示词工程与自动化脚本提升需求拆解、代码生成、性能诊断与"
    "全链路排错效率，实现人机协同开发。\n"
    "- 主导订单中台建设，支撑日均 500 万订单。\n"
    "## 专业技能\n"
    "- 熟悉 Java 并发编程与 JVM 调优。\n"
)


def test_parse_diff_fuzzy_salvages_truncated_quote():
    """模型截掉句尾（bcb5d7bb 实证形态）应命中并回填真实原文。"""
    truncated = (
        "AI 赋能研发效能: 擅长将 AI 辅助开发融入后端研发全流程，"
        "通过提示词工程与自动化脚本提升需求拆解、代码生成、性能诊断与"
        "全链路排错。"
    )
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "section": "工作经历",
            "original": truncated,
            "proposed": "改写后的句子",
            "reason": "贴合 JD",
            "confidence": "high",
            "provenance": truncated,
        },
        _FUZZY_RESUME,
    )
    assert valid is True
    assert diff.provenance_state == "verified"
    # provenance/original 回填为真实原文（含被截掉的尾巴）
    actual_bullet = (
        "AI 赋能研发效能: 擅长将 AI 辅助开发融入后端研发全流程，"
        "通过提示词工程与自动化脚本提升需求拆解、代码生成、性能诊断与"
        "全链路排错效率，实现人机协同开发。"
    )
    assert diff.original == actual_bullet
    assert diff.provenance == actual_bullet
    assert diff.source_span is not None
    start, end = diff.source_span
    assert _FUZZY_RESUME[start:end] == actual_bullet


def test_parse_diff_fuzzy_salvages_small_edits():
    """句中小幅改动（漏字/多字）走 difflib 路径命中。"""
    actual_bullet = "主导订单中台建设，支撑日均 500 万订单。"
    misquoted = "主导订单中台的建设，支撑日均 500 万订单。"  # 多一个「的」
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "section": "工作经历",
            "original": misquoted,
            "proposed": "重构订单中台，支撑日均 500 万订单。",
            "reason": "强动词",
            "confidence": "medium",
            "provenance": misquoted,
        },
        _FUZZY_RESUME,
    )
    assert valid is True
    assert diff.provenance_state == "verified"
    assert diff.original == actual_bullet


def test_parse_diff_fuzzy_rejects_unrelated_quote():
    """与原文无关的引用不得被模糊命中（防编造铁律）。"""
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "section": "工作经历",
            "original": "精通 Kubernetes 多集群治理与服务网格灰度发布",
            "proposed": "精通 Kubernetes 多集群治理与 服务网格 灰度发布实践",
            "reason": "JD 关键词",
            "confidence": "high",
            "provenance": "精通 Kubernetes 多集群治理与服务网格灰度发布",
        },
        _FUZZY_RESUME,
    )
    assert valid is False
    assert diff.provenance_state == "missing"


def test_tailor_resume_fuzzy_recovers_diff_end_to_end():
    """整链：MockLLM 产出截断引用的 diff，tailor_resume 应保留为有效建议。"""
    truncated = (
        "AI 赋能研发效能: 擅长将 AI 辅助开发融入后端研发全流程，"
        "通过提示词工程与自动化脚本提升需求拆解、代码生成、性能诊断与"
        "全链路排错。"
    )
    mock = MockLLM(result={
        "sections": {"工作经历": "改写后内容"},
        "diffs": [{
            "type": "modify",
            "section": "工作经历",
            "original": truncated,
            "proposed": "重构研发效能工具链，将 AI 辅助开发融入后端全流程",
            "reason": "贴合 JD",
            "confidence": "high",
            "provenance": truncated,
        }],
    })
    result = tailor_resume(mock, _FUZZY_RESUME, "Gap report")
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance_state == "verified"
    assert "全链路排错效率" in result.diffs[0].original


def test_parse_diff_fuzzy_prefix_short_quotes_still_rejected():
    """过短引用（<12 字符归一化）不做模糊匹配，防误命中。"""
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "section": "工作经历",
            "original": "熟悉 Java",
            "proposed": "熟悉 Java 并发",
            "reason": "短引用",
            "confidence": "low",
            "provenance": "熟悉 Java",
        },
        "熟练掌握 Java 并发编程\n",
    )
    assert valid is False
