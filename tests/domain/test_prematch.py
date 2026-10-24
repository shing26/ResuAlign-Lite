"""prematch（ADR-0064）：确定性预匹配词面信号的单元测试。"""
import pytest

from resualign.prematch import (
    compute_match_signals,
    prematch_enabled,
    signal_line,
)


def test_alias_resolution_and_word_boundaries():
    signals = compute_match_signals(
        "负责 K8s 集群运维与 JSON 数据处理",
        "要求熟悉 Kubernetes 与 JSON 日志接入",
    )
    # k8s -> kubernetes 命中；JSON 不得让 js -> javascript 误命中
    assert "kubernetes" in signals["matched_skills"]
    assert "javascript" not in signals["matched_skills"]
    assert "javascript" not in signals.get("jd_only", [])


def test_multiword_skill_flexible_whitespace():
    signals = compute_match_signals(
        "Spring\nBoot 微服务实践",
        "需要 Spring Boot 经验",
    )
    assert "spring boot" in signals["matched_skills"]


def test_jd_only_terms_never_returned_as_strings():
    signals = compute_match_signals(
        "三年 Python 后端经验",
        "需要 Python 与 Rust 与 Terraform",
    )
    assert signals["matched_skills"] == ["python"]
    assert signals["jd_skill_total"] == 3
    # rust / terraform 只体现在计数里，绝不出现在任何字符串字段
    assert "rust" not in str(signals)
    assert "terraform" not in str(signals)


def test_signal_line_resume_backed_only_and_format():
    signals = {"matched_skills": ["python", "redis"], "jd_skill_total": 5}
    line = signal_line(signals)
    assert line == "匹配信号：命中核心技能 python、redis（2/5）"


def test_signal_line_empty_when_no_resume_backed_hits():
    assert signal_line({"matched_skills": [], "jd_skill_total": 3}) == ""
    assert signal_line(None) == ""


def test_signal_line_truncates_skill_list():
    signals = {"matched_skills": ["a", "b", "c", "d", "e", "f", "g"], "jd_skill_total": 9}
    line = signal_line(signals, max_skills=6)
    # 截断只影响展示列表；命中数仍是真实值（7/9）
    assert line.endswith("（7/9）")
    assert "g" not in line


def test_prematch_enabled_flag(monkeypatch):
    monkeypatch.delenv("RESUALIGN_PREMATCH", raising=False)
    assert prematch_enabled() is True
    monkeypatch.setenv("RESUALIGN_PREMATCH", "0")
    assert prematch_enabled() is False
    monkeypatch.setenv("RESUALIGN_PREMATCH", "off")
    assert prematch_enabled() is False
    monkeypatch.setenv("RESUALIGN_PREMATCH", "1")
    assert prematch_enabled() is True


def test_compute_handles_empty_inputs():
    signals = compute_match_signals("", "")
    assert signals["matched_skills"] == []
    assert signals["jd_skill_total"] == 0
    assert signals["overlap_ratio"] == 0.0


def test_jd_context_summary_includes_prematch_line_and_keeps_budget():
    from resualign.jd_analysis import jd_context_summary

    profile = {"must_have_skills": ["Java", "Kafka"], "min_years_experience": 3}
    gap = {"supported_keywords": ["Kafka 背景改写"]}
    signals = {"matched_skills": ["java", "kafka"], "jd_skill_total": 4}
    summary = jd_context_summary(profile, gap, prematch=signals)
    assert "匹配信号：命中核心技能 java、kafka（2/4）" in summary
    assert len(summary) <= 300


def test_jd_context_summary_prematch_missing_keywords_still_excluded():
    from resualign.jd_analysis import jd_context_summary

    gap = {
        "supported_keywords": ["Kafka 背景改写"],
        "missing_keywords": ["Rust", "Terraform"],
    }
    signals = {"matched_skills": ["java"], "jd_skill_total": 3}
    summary = jd_context_summary({"must_have_skills": ["Java"]}, gap, prematch=signals)
    # ADR-0061：缺口词与 JD-only 词都不得经信号行重新进入编辑器提示
    assert "Rust" not in summary
    assert "Terraform" not in summary
    assert "匹配信号" in summary


def test_jd_context_summary_without_prematch_unchanged():
    from resualign.jd_analysis import jd_context_summary

    base = jd_context_summary({"must_have_skills": ["Java"]}, None)
    with_none = jd_context_summary({"must_have_skills": ["Java"]}, None, prematch=None)
    assert base == with_none


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_prematch_disabled_values(monkeypatch, value):
    monkeypatch.setenv("RESUALIGN_PREMATCH", value)
    assert prematch_enabled() is False
