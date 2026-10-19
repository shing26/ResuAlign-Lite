import json

import pytest

from resualign.engine.tailor import (
    METRIC_PLACEHOLDER,
    _ensure_metric_placeholder,
    _has_quantified_metric,
    parse_diff_with_provenance,
    rewrite_bullet,
    tailor_resume,
)
from resualign.models import TailoredResume


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
        self.last_user = None

    def chat_json(self, system, user, model=None):
        self.last_system = system
        self.last_user = user
        return self.result


def test_tailor_resume_returns_tailoredresume():
    mock = MockLLM()
    result = tailor_resume(mock, "Worked on backend", "Gap report...")
    assert isinstance(result, TailoredResume)
    assert len(result.diffs) == 1
    assert result.diffs[0].provenance == "Worked on backend"


def test_tailor_resume_empty_diffs():
    mock = MockLLM(result={"sections": {}, "diffs": []})
    result = tailor_resume(mock, "Worked on backend", "Gap")
    assert len(result.diffs) == 0
    assert result.sections == {}


def test_tailor_resume_provenance_tracked():
    mock = MockLLM()
    result = tailor_resume(mock, "Worked on backend", "Gap")
    assert all(d.provenance != "" for d in result.diffs)


def test_tailor_resume_normalizes_enum_values():
    mock = MockLLM(result={
        "sections": {},
        "diffs": [{
            "type": "rephrase",
            "original": "Worked on backend",
            "proposed": "Refactored backend",
            "reason": "JD match",
            "confidence": 0.7,
            "provenance": "Worked on backend",
        }],
    })
    result = tailor_resume(mock, "Worked on backend", "Gap")
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
    # 内容级校验（#74）：proposed 的 FastAPI 必须在简历原文中有依据，
    # 否则会被拦截进 invalid_diffs 而非 diffs。
    result = tailor_resume(
        mock, "Worked on backend with FastAPI and Redis caching", "Gap"
    )
    assert result.diffs[0].section == "项目经历"


def test_tailor_blocks_unsourced_english_proper_noun():
    """2026-09-15 狗食发现（#112 周 2）：#74 的专名检查只看缩写与驼峰，
    英文简历里句中的 Title-case 专名（Java/Kafka/公司名）完全不查——
    「Python dev」可以被改成「Built services using Java」并标成 verified。
    现在句中大写词必须有出处，句首大写与常见英文词不算专名。"""
    mock = MockLLM(result={
        "sections": {},
        "diffs": [{
            "type": "modify",
            "section": "项目经历",
            "original": "Python dev built services.",
            "proposed": "Built services using Java",
            "reason": "JD asks for Java",
            "confidence": "high",
            "provenance": "Python dev built services.",
        }],
    })
    result = tailor_resume(mock, "Python dev built services.", "Gap")
    assert result.diffs == []
    assert result.invalid_diffs[0].provenance_state == "fabricated"
    assert "Java" in result.invalid_diffs[0].reason


def test_tailor_diff_section_defaults_empty_when_absent():
    mock = MockLLM()
    result = tailor_resume(mock, "Worked on backend", "Gap")
    assert result.diffs[0].section == ""


def test_tailor_prompt_instructs_section_per_diff():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap")
    assert "section" in mock.last_system
    assert "项目经历" in mock.last_system


def test_tailor_drops_supported_keywords_without_resume_evidence():
    resume = "使用 Redis 做缓存。"
    gap = json.dumps(
        {
            "supported_keywords": ["Redis caching", "Kubernetes"],
            "supported_keyword_evidence": {
                "Redis caching": "使用 Redis 做缓存。",
                "Kubernetes": "使用 Kubernetes 部署服务。",
            },
            "missing_keywords": [],
            "misaligned_emphasis": [],
            "strength_matches": [],
        },
        ensure_ascii=False,
    )
    mock = MockLLM(result={"sections": {}, "diffs": []})

    tailor_resume(mock, resume, gap)

    assert "Redis caching" in mock.last_user
    assert "使用 Redis 做缓存。" in mock.last_user
    assert "Kubernetes" not in mock.last_user


def test_tailor_returns_no_safe_rewrite_without_anchored_directions():
    resume = "使用 Java 与 Spring Boot 开发后端服务。"
    gap = json.dumps(
        {
            "supported_keywords": ["Kubernetes"],
            "supported_keyword_evidence": {
                "Kubernetes": "使用 Kubernetes 部署服务。",
            },
            "missing_keywords": ["Kubernetes"],
            "misaligned_emphasis": [],
            "strength_matches": [],
        },
        ensure_ascii=False,
    )
    mock = MockLLM(result={"sections": {}, "diffs": []})

    result = tailor_resume(mock, resume, gap)

    assert result.diffs == []
    assert result.invalid_diffs == []
    assert result.no_safe_rewrite is True
    assert "原文" in result.no_safe_rewrite_reason
    assert mock.last_user is None


def test_tailor_rejects_supported_keyword_with_unrelated_evidence():
    resume = "使用 Java 与 Spring Boot 开发后端服务。"
    gap = json.dumps(
        {
            "supported_keywords": ["Kubernetes"],
            "supported_keyword_evidence": {
                "Kubernetes": "使用 Java 与 Spring Boot 开发后端服务。",
            },
            "missing_keywords": ["Kubernetes"],
            "misaligned_emphasis": [],
            "strength_matches": [],
        },
        ensure_ascii=False,
    )
    mock = MockLLM(result={"sections": {}, "diffs": []})

    result = tailor_resume(mock, resume, gap)

    assert result.no_safe_rewrite is True
    assert mock.last_user is None


def test_tailor_keeps_editing_with_anchored_strength_matches():
    resume = "使用 Java 与 Spring Boot 开发后端服务。"
    gap = json.dumps(
        {
            "supported_keywords": [],
            "supported_keyword_evidence": {},
            "missing_keywords": ["Kubernetes"],
            "misaligned_emphasis": [],
            "strength_matches": ["Java"],
        },
        ensure_ascii=False,
    )
    mock = MockLLM(result={"sections": {}, "diffs": []})

    result = tailor_resume(mock, resume, gap)

    assert result.no_safe_rewrite is False
    assert mock.last_user is not None
    assert "Java" in mock.last_user


def test_tailor_prompt_caps_diff_output():
    # R4: 04b-PE §2.5 —— diffs 封顶「≤ 10 条」、reason「≤ 40 字」（旧文案
    # "at most 15 diffs / 80 characters" 已被新契约取代）。
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap")
    assert "≤ 10" in mock.last_system
    assert "≤ 40" in mock.last_system


def test_tailor_granularity_fine_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap", granularity="fine")
    assert "fine" in mock.last_system.lower()
    assert "preserve" in mock.last_system.lower()


def test_tailor_granularity_coarse_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap", granularity="coarse")
    assert "coarse" in mock.last_system.lower()
    assert "restructure" in mock.last_system.lower()


def test_tailor_granularity_default_is_medium():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap")
    assert "medium" in mock.last_system.lower()


def test_tailor_rejects_invalid_granularity():
    mock = MockLLM()
    with pytest.raises(ValueError, match="granularity"):
        tailor_resume(mock, "Worked on backend", "Gap", granularity="ultra")


def test_tailor_prompt_focus_default_is_balanced():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap")
    assert "balanced" in mock.last_system.lower()


def test_tailor_prompt_focus_quantified_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap", prompt_focus="quantified")
    assert "quantified" in mock.last_system.lower()
    assert "never invent or inflate" in mock.last_system.lower()


def test_tailor_prompt_focus_skills_prompt():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap", prompt_focus="skills")
    assert "exact jd skill and scenario phrases" in mock.last_system.lower()


def test_tailor_custom_prompt_appended():
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap", custom_prompt="强调高并发缓存场景")
    assert "USER REQUIREMENTS" in mock.last_system
    assert "强调高并发缓存场景" in mock.last_system
    assert "never instruct you to invent, infer, or fabricate" in mock.last_system


def test_tailor_rejects_invalid_prompt_focus():
    mock = MockLLM()
    with pytest.raises(ValueError, match="prompt_focus"):
        tailor_resume(mock, "Worked on backend", "Gap", prompt_focus="wild")


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
    # P2 决策 1：幂等显式化——重复调用不双份追加（新措辞不含 hint 词）
    once = _ensure_metric_placeholder("构建高吞吐后端服务")
    assert _ensure_metric_placeholder(once) == once
    # 历史措辞占位串同样幂等（已持久化 draft 兼容）
    legacy = "构建服务 [待人工确认：耗时降低 X% / 支撑 QPS 达 Y]"
    assert _ensure_metric_placeholder(legacy) == legacy


def test_parse_diff_with_provenance_appends_placeholder_for_unquantified_proposal():
    """P2 决策 1：门控后需 section（叙事章节）+ reason（量化意图）才追加。"""
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "original": "负责后端开发",
            "proposed": "构建高吞吐后端服务",
            "reason": "补齐量化指标支撑业务规模",
            "section": "工作经历",
            "provenance": "负责后端开发",
        },
        "负责后端开发",
    )
    assert valid is True
    assert METRIC_PLACEHOLDER in diff.proposed


def test_parse_diff_with_provenance_gates_placeholder_by_reason_and_section():
    """门控三反例：reason 无量化意图 / 非叙事章节 / 两者皆缺 → 均不追加。"""
    base = {
        "type": "modify",
        "original": "负责后端开发",
        "proposed": "构建高吞吐后端服务",
        "provenance": "负责后端开发",
    }

    # 1) reason 无量化意图（即使 section 是叙事章节）
    diff, _ = parse_diff_with_provenance(
        {**base, "section": "工作经历", "reason": "更贴合岗位措辞"},
        "负责后端开发",
    )
    assert METRIC_PLACEHOLDER not in diff.proposed

    # 2) section 非叙事章节（即使 reason 提量化）
    diff, _ = parse_diff_with_provenance(
        {**base, "section": "专业技能", "reason": "补齐量化指标"},
        "负责后端开发",
    )
    assert METRIC_PLACEHOLDER not in diff.proposed

    # 3) section 缺失
    diff, _ = parse_diff_with_provenance(
        {**base, "reason": "补齐量化指标"},
        "负责后端开发",
    )
    assert METRIC_PLACEHOLDER not in diff.proposed


def test_parse_diff_with_provenance_placeholder_forced_by_prompt_focus():
    """信号 A：prompt_focus="quantified" 时叙事章节无条件追加。"""
    diff, _ = parse_diff_with_provenance(
        {
            "type": "modify",
            "original": "负责后端开发",
            "proposed": "构建高吞吐后端服务",
            "reason": "更贴合岗位措辞",
            "section": "项目经历",
            "provenance": "负责后端开发",
        },
        "负责后端开发",
        prompt_focus="quantified",
    )
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


def test_parse_diff_original_fallback_when_provenance_missing():
    """Phase 3: 模型省略 provenance 但 original 逐字在原文时，用 original 回退匹配。"""
    resume = "# 项目经历\n1. ResuAlign-Lite 智能简历对齐与求职工作台\n技术栈: Python / FastAPI\n"
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "section": "项目经历",
            "original": "1. ResuAlign-Lite 智能简历对齐与求职工作台",
            "proposed": "重构 ResuAlign-Lite 工作台",
            "reason": "测试回退",
            "confidence": "high",
        },
        resume,
    )
    assert valid is True
    assert diff.provenance_state == "verified"
    assert diff.provenance_quote == diff.original


def test_parse_diff_original_fallback_still_rejects_invented():
    """Phase 3: original 不在原文时，回退匹配仍失败（不编造原则不变）。"""
    resume = "# 项目经历\n1. ResuAlign-Lite 智能简历对齐与求职工作台\n"
    diff, valid = parse_diff_with_provenance(
        {
            "type": "modify",
            "section": "项目经历",
            "original": "主导了 500 人团队",
            "proposed": "主导 500 人团队",
            "reason": "测试",
            "confidence": "high",
        },
        resume,
    )
    assert valid is False
    assert diff.provenance_state == "missing"


def test_derive_section_diffs_from_sections_when_diffs_empty():
    """Phase 3: 模型只回 sections 不回 diffs 时，推导章节级 diff（verified）。"""
    from resualign.engine.tailor import _locate_section_span, derive_section_diffs

    resume = (
        "# 项目经历\n1. ResuAlign-Lite 智能简历对齐与求职工作台\n"
        "技术栈: Python / FastAPI\n\n# 技能清单\nLLM 应用\n"
    )
    span = _locate_section_span("项目经历", resume)
    assert span is not None
    tailored = TailoredResume(
        sections={
            "项目经历": (
                "1. ResuAlign-Lite 智能简历对齐与求职工作台\n"
                "技术栈: Python / FastAPI / SQLite (WAL)\n重写后的描述"
            )
        },
        diffs=[],
        invalid_diffs=[],
    )
    derived = derive_section_diffs(tailored, resume)
    assert len(derived) == 1
    assert derived[0].type == "modify"
    assert derived[0].provenance_state == "verified"
    assert derived[0].original.startswith("1. ResuAlign-Lite")
    assert "SQLite (WAL)" in derived[0].proposed


def test_derive_section_diffs_noop_when_sections_match():
    """Phase 3: 章节与原文一致时不应产出假 diff。"""
    from resualign.engine.tailor import derive_section_diffs

    resume = "# 项目经历\n1. 现有项目描述\n"
    tailored = TailoredResume(
        sections={"项目经历": "1. 现有项目描述"},
        diffs=[],
        invalid_diffs=[],
    )
    assert derive_section_diffs(tailored, resume) == []


def test_derive_section_diffs_keeps_existing_bullet_diffs():
    """Phase 3: 已有 bullet diffs 时不覆盖。"""
    from resualign.engine.tailor import derive_section_diffs

    resume = "# 项目经历\n1. 现有项目描述\n"
    tailored = TailoredResume(
        sections={"项目经历": "1. 改写后的项目描述"},
        diffs=[{"diff_id": "x"}],
        invalid_diffs=[],
    )
    assert derive_section_diffs(tailored, resume) == tailored.diffs


# ---------------------------------------------------------------------------
# Editor output contract（2026-10-19，#163 P0）：技能清单禁止增长。
# 实证形态：腾讯后台开发 JD，整卷编辑器把 missing_keyword 拼成一条新技能
# 写进「专业技能清单」。这些词经由 gap report 的 missing_keywords 进入
# allowlist 语料，所以内容级校验会放行——约束必须独立于 allowlist 语义，
# 按「条目数」判定。
# ---------------------------------------------------------------------------

_SKILLS_RESUME = (
    "专业技能清单\n"
    "- 后端工程深度：熟练 Java 与 Spring Boot，具备多租户与幂等设计经验。\n"
)

# missing_keywords 里的词就是 JD 要、简历没有的；它们同时是 allowlist 语料，
# 因此能穿过内容级校验（这正是 #163 要堵的洞）。
_SKILLS_GAP = json.dumps(
    {
        "supported_keywords": ["Java"],
        "supported_keyword_evidence": {"Java": "Java"},
        "missing_keywords": ["TCP/UDP网络协议", "进程间通讯编程", "设计模式"],
        "misaligned_emphasis": [],
        "strength_matches": ["Java Spring Boot 后端开发"],
    },
    ensure_ascii=False,
)


def test_tailor_blocks_skills_list_growth_from_jd_keywords():
    """JD 关键词直灌技能清单 → 必须拦成 invalid，不得冒充 verified。"""
    original = (
        "- 后端工程深度：熟练 Java 与 Spring Boot，具备多租户与幂等设计经验。"
    )
    injected = (
        original
        + "\n- 系统基础能力：掌握常用设计模式（如单例、工厂、观察者）。"
    )
    mock = MockLLM(result={
        "sections": {"专业技能清单": injected},
        "diffs": [{
            "type": "modify",
            "section": "专业技能清单",
            "original": original,
            "proposed": injected,
            "reason": "补齐缺失关键词",
            "confidence": "high",
            "provenance": original,
        }],
    })
    result = tailor_resume(mock, _SKILLS_RESUME, _SKILLS_GAP)
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    blocked = result.invalid_diffs[0]
    assert blocked.provenance_state == "fabricated"
    assert "技能清单" in blocked.reason


def test_tailor_blocks_two_skills_growth_diffs_like_tencent_run():
    """腾讯实证形态：两条 diff 都靠追加条目「覆盖缺口」，两条都要拦。"""
    original = (
        "- 后端工程深度：熟练 Java 与 Spring Boot，具备多租户与幂等设计经验。"
    )
    extra = "\n- 系统基础能力：熟悉 TCP/UDP 网络协议与进程间通讯，掌握设计模式。"
    mock = MockLLM(result={
        "sections": {"专业技能清单": original + extra},
        "diffs": [
            {
                "type": "modify",
                "section": "专业技能清单",
                "original": original,
                "proposed": original + extra,
                "reason": "补齐缺失关键词",
                "confidence": "high",
                "provenance": original,
            },
            {
                "type": "modify",
                "section": "专业技能清单",
                "original": original,
                "proposed": original + extra,
                "reason": "补齐缺失关键词",
                "confidence": "high",
                "provenance": original,
            },
        ],
    })
    result = tailor_resume(mock, _SKILLS_RESUME, _SKILLS_GAP)
    assert result.diffs == []
    assert len(result.invalid_diffs) == 2
    assert all(d.provenance_state == "fabricated" for d in result.invalid_diffs)


def test_tailor_allows_skills_rewrite_without_new_entries():
    """改写已有技能条目（不新增条目）仍应可用。"""
    original = "- 熟悉 Java 与 Spring Boot，具备多租户设计经验。"
    resume = f"专业技能清单\n{original}\n"
    mock = MockLLM(result={
        "sections": {"专业技能清单": "- 熟练 Java 与 Spring Boot，具备多租户与幂等设计经验。"},
        "diffs": [{
            "type": "modify",
            "section": "专业技能清单",
            "original": original,
            "proposed": "- 熟练 Java 与 Spring Boot，具备多租户与幂等设计经验。",
            "reason": "重强调已有事实",
            "confidence": "high",
            "provenance": original,
        }],
    })
    result = tailor_resume(mock, resume, _SKILLS_GAP)
    assert len(result.diffs) == 1
    assert result.invalid_diffs == []


def test_editor_output_contract_only_guards_skills_sections():
    """叙事章节（项目/工作经历）不受「禁止新增条目」约束。"""
    original = "- 搭建 Redis 缓存层"
    resume = f"项目经历\n{original}\n"
    mock = MockLLM(result={
        "sections": {"项目经历": original + "\n- 补充一条项目要点"},
        "diffs": [{
            "type": "modify",
            "section": "项目经历",
            "original": original,
            "proposed": original + "\n- 补充一条项目要点",
            "reason": "补充项目细节",
            "confidence": "high",
            "provenance": original,
        }],
    })
    result = tailor_resume(mock, resume, "Gap report")
    assert len(result.diffs) == 1
    assert result.invalid_diffs == []


def test_tailor_blocks_missing_keyword_appended_to_existing_bullet():
    """中文缺口词续写进已有条目时，条目数不变也必须拦下。"""
    original = "- 熟练 Java 与 Spring Boot，具备多租户设计经验。"
    proposed = (
        "- 熟练 Java 与 Spring Boot，具备多租户设计经验；"
        "掌握常用设计模式（如单例、工厂、观察者）。"
    )
    resume = f"专业技能清单\n{original}\n"
    mock = MockLLM(result={
        "sections": {"专业技能清单": proposed},
        "diffs": [{
            "type": "modify",
            "section": "专业技能清单",
            "original": original,
            "proposed": proposed,
            "reason": "强化岗位关键词",
            "confidence": "high",
            "provenance": original,
        }],
    })
    result = tailor_resume(mock, resume, _SKILLS_GAP)
    assert result.diffs == []
    assert len(result.invalid_diffs) == 1
    blocked = result.invalid_diffs[0]
    assert blocked.provenance_state == "fabricated"
    assert "设计模式" in blocked.reason


def test_tailor_allows_missing_keyword_when_resume_already_supports_it():
    """同一术语若简历原文已有事实，不得被临时 guard 误拦。"""
    original = "- 熟练 Java 与 Spring Boot，掌握常用设计模式。"
    proposed = (
        "- 熟练 Java 与 Spring Boot，具备多租户与幂等设计经验，"
        "掌握常用设计模式。"
    )
    resume = f"专业技能清单\n{original}\n"
    mock = MockLLM(result={
        "sections": {"专业技能清单": proposed},
        "diffs": [{
            "type": "modify",
            "section": "专业技能清单",
            "original": original,
            "proposed": proposed,
            "reason": "重强调已有事实",
            "confidence": "high",
            "provenance": original,
        }],
    })
    result = tailor_resume(mock, resume, _SKILLS_GAP)
    assert len(result.diffs) == 1
    assert result.invalid_diffs == []


def test_skills_entry_growth_is_structural_not_keyword_based():
    """按条目数判定：改写变长不算增长，新增一条才算；非技能章节不设限。"""
    from resualign.engine.tailor import _skills_entry_growth
    from resualign.models import DiffItem

    def diff(section, original, proposed, kind="modify"):
        return DiffItem(
            section=section, type=kind, original=original, proposed=proposed
        )

    assert _skills_entry_growth(diff("专业技能", "- a", "- a 更长的改写")) is False
    assert _skills_entry_growth(diff("专业技能清单", "- a", "- a\n- b")) is True
    assert _skills_entry_growth(diff("Skills", "- a", "- a\n- b")) is True
    assert _skills_entry_growth(diff("项目经历", "- a", "- a\n- b")) is False
    # remove 型不受约束（只删不增）
    assert (
        _skills_entry_growth(
            diff("专业技能", "- a", "- a\n- b", kind="remove")
        ) is False
    )


def test_tailor_prompt_forbids_skills_list_growth():
    """提示词契约：#163 的两个新增约束必须真的在 system prompt 里。"""
    mock = MockLLM()
    tailor_resume(mock, "Worked on backend", "Gap")
    assert "禁止新增条目" in mock.last_system
    assert "没有安全改写" in mock.last_system
    assert "diffs：0-10 条" in mock.last_system
    assert "允许 diffs 为空" in mock.last_system
    # 旧措辞（要求覆盖每个 missing_keyword）已移除——它正是诱导直灌的指令。
    assert "每个 missing_keyword / misaligned_emphasis 至少被一条 diff" not in (
        mock.last_system
    )


def test_tailor_filters_unsupported_missing_keywords_from_editor_prompt():
    """无简历依据的缺口词不送编辑器，也不进 allowlist 语料。"""
    resume = "专业技能清单\n- 熟悉 Java 与 Spring Boot，做过 Redis 缓存。\n"
    gap = json.dumps(
        {
                "supported_keywords": ["Java"],
                "supported_keyword_evidence": {"Java": "Java"},
            "missing_keywords": ["Redis", "设计模式"],
            "misaligned_emphasis": [],
            "strength_matches": ["Java 与 Spring Boot"],
        },
        ensure_ascii=False,
    )
    mock = MockLLM(result={"sections": {}, "diffs": []})
    tailor_resume(mock, resume, gap)
    assert "Redis" in mock.last_user
    assert "设计模式" not in mock.last_user
