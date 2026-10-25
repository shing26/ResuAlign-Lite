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


# ---------------------------------------------------------------- A 组扩充的误报防线


def test_vocab_batch_a_word_boundaries():
    """A 组词的边界误报（2026-10-25 离线分析后人工筛过的案例）。"""
    # git 不得命中 GitHub（后续词是词字符，\b 不成立）
    signals = compute_match_signals("GitHub Actions CI", "需要 git 经验")
    assert signals["matched_skills"] == []  # GitHub ≠ git
    # css 不得命中 scss/less 变体
    signals = compute_match_signals("熟悉 SCSS 预处理", "需要 CSS 能力")
    assert signals["matched_skills"] == []  # SCSS ≠ css
    # excel 不得命中 excellent
    signals = compute_match_signals("excellent communication", "需要 Excel 报表")
    assert signals["matched_skills"] == []


def test_vocab_batch_a_alias_and_case():
    # vue.js 别名归一到 vue
    signals = compute_match_signals("Vue.js 单页应用", "需要 Vue 经验")
    assert "vue" in signals["matched_skills"]
    # vLLM 大小写变体由 IGNORECASE 覆盖
    signals = compute_match_signals("vLLM 部署", "需要 vLLM 推理")
    assert "vllm" in signals["matched_skills"]
    # llm 不得命中 hell 之类（\b 边界）
    signals = compute_match_signals("hello world", "需要 LLM 微调经验")
    assert "llm" not in signals["matched_skills"]


def test_signal_line_resume_backed_only_and_format():
    signals = {"matched_skills": ["python", "redis"], "jd_skill_total": 5}
    line = signal_line(signals)
    assert line == "匹配信号：命中核心技能 python、redis（2/5）"


def test_signal_line_empty_when_no_resume_backed_hits():
    assert signal_line({"matched_skills": [], "jd_skill_total": 3}) == ""
    assert signal_line(None) == ""


def test_signal_line_truncates_skill_list():
    signals = {"matched_skills": ["a", "b", "c", "d", "e", "f", "g"], "jd_skill_total": 9}
    line = signal_line(signals)
    # 审阅第二轮：展示上限默认前 3 项；命中数仍是真实值（7/9），
    # 未展示的以「等 4 项」汇总——信号行自身不可能吃掉 300 字预算
    assert line == "匹配信号：命中核心技能 a、b、c（7/9，等 4 项）"
    assert "d" not in line
    assert "g" not in line


def test_signal_line_no_suffix_when_all_shown():
    """审阅第三轮边界：命中 ≤ 展示上限时不渲染「等 0 项」。"""
    boundary = signal_line(
        {"matched_skills": ["java", "kafka", "redis"], "jd_skill_total": 5}
    )
    assert boundary == "匹配信号：命中核心技能 java、kafka、redis（3/5）"
    assert "等" not in boundary
    single = signal_line({"matched_skills": ["java"], "jd_skill_total": 5})
    assert single == "匹配信号：命中核心技能 java（1/5）"
    assert "等" not in single


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


def test_jd_context_summary_signal_survives_tight_budget():
    """审阅第二轮：顺位为核心要求 > 匹配信号 > 其余。

    预算 60 字时核心要求保得住、软技能/学历被收紧，信号行紧随核心要求
    之后且自身有展示上限，不会吃掉预算。
    """
    from resualign.jd_analysis import jd_context_summary

    profile = {
        "must_have_skills": ["Java", "Kafka", "Spark", "Airflow", "Redis"],
        "business_scenarios": ["数据平台", "实时数仓", "湖仓一体"],
        "soft_skills": ["Communication"],
        "education_requirements": ["本科及以上"],
        "min_years_experience": 5,
    }
    signals = {"matched_skills": ["java", "kafka"], "jd_skill_total": 6}
    tight = jd_context_summary(profile, None, max_chars=60, prematch=signals)
    assert "岗位要求" in tight
    assert "匹配信号" in tight
    assert tight.index("岗位要求") < tight.index("匹配信号")
    assert "命中核心技能" in tight


def test_vocab_blind_spot_logged_at_info(caplog):
    """审阅意见 1：词表盲区（JD 无词表内技能）必须可见，只记计数不落原文。"""
    import logging

    with caplog.at_level(logging.INFO, logger="resualign.prematch"):
        compute_match_signals("三年 Java 后端经验", "需要 Cobol 与 Perl 与 Delphi")
    blind_spots = [
        record
        for record in caplog.records
        if "vocab blind spot" in record.message
    ]
    assert len(blind_spots) == 1
    record = blind_spots[0]
    assert record.levelno == logging.INFO
    assert "Cobol" not in record.getMessage()
    assert "Delphi" not in record.getMessage()


def test_genuine_no_overlap_logged_at_debug(caplog):
    import logging

    with caplog.at_level(logging.DEBUG, logger="resualign.prematch"):
        compute_match_signals("三年 Java 后端经验", "需要 Kubernetes 与 Rust")
    debugs = [
        record
        for record in caplog.records
        if record.levelno == logging.DEBUG and "no overlap" in record.message
    ]
    assert len(debugs) == 1
    assert debugs[0].getMessage().startswith("prematch: no overlap (jd_skills=2)")


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_prematch_disabled_values(monkeypatch, value):
    monkeypatch.setenv("RESUALIGN_PREMATCH", value)
    assert prematch_enabled() is False
