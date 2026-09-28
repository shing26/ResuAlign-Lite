"""Unit tests for the local rule-based diagnose stage (取舍一方案 A).

The rule diagnose replaces the LLM diagnose call in the alignment pipeline:
it must be deterministic, require no client/network, and return the same
``score`` / ``skills`` / ``issues`` shape as the LLM ``AnalysisSchema``.
"""

from resualign.rule_diagnose import diagnose_resume_local

GOOD_RESUME = (
    "张三\n"
    "13800138000\n"
    "zhangsan@example.com\n"
    "\n"
    "教育背景\n"
    "2015-2019 某某大学 计算机科学与技术 本科\n"
    "\n"
    "技能\n"
    "Python, Redis, Docker, Kubernetes\n"
    "\n"
    "项目经历\n"
    "- 负责订单服务模块开发，使用 Redis 缓存热点数据，QPS 提升 30%，接口耗时降低 40%\n"
    "- 使用 Docker 部署服务，通过 CI/CD 流水线发布\n"
    "- 参与数据库索引优化，慢查询数量下降 50%\n"
)


def test_good_resume_gets_clean_baseline():
    result = diagnose_resume_local(GOOD_RESUME)
    assert result["score"] == 75
    assert result["issues"] == []
    assert result["fallback_used"] is True


def test_output_shape_matches_analysis_schema():
    result = diagnose_resume_local(GOOD_RESUME)
    assert set(result) >= {"score", "skills", "issues"}
    assert isinstance(result["score"], int)
    assert 0 <= result["score"] <= 100
    assert isinstance(result["skills"], list)
    assert isinstance(result["issues"], list)


def test_empty_text_scores_zero():
    result = diagnose_resume_local("")
    assert result["score"] == 0
    assert result["issues"]


def test_missing_phone_and_email_raise_issues():
    no_contact = GOOD_RESUME.replace("13800138000\n", "").replace(
        "zhangsan@example.com\n", ""
    )
    result = diagnose_resume_local(no_contact)
    assert any("手机号" in item for item in result["issues"])
    assert any("邮箱" in item for item in result["issues"])
    assert result["score"] < 75


def test_phone_with_separators_is_detected():
    # Bug-10: 138-0000-0000 / 138 0000 0000 must count as phone present.
    for phone in ("138-0000-0000", "138 0000 0000", "13800000000"):
        text = GOOD_RESUME.replace("13800138000\n", f"{phone}\n")
        result = diagnose_resume_local(text)
        assert not any("手机号" in item for item in result["issues"]), phone
        assert result["score"] == 75, phone


def test_phone_plus86_with_separators_is_detected():
    for phone in ("+86 138-0000-0000", "86-138 0000 0000"):
        text = GOOD_RESUME.replace("13800138000\n", f"{phone}\n")
        result = diagnose_resume_local(text)
        assert not any("手机号" in item for item in result["issues"]), phone


def test_garbled_text_detected():
    garbled = GOOD_RESUME.replace("教育背景", "\ufffd\ufffd")
    result = diagnose_resume_local(garbled)
    assert any("乱码" in item or "编码" in item for item in result["issues"])
    assert result["score"] < 75


def test_abnormal_line_breaks_detected():
    result = diagnose_resume_local("技能\n\n\n\n\n\nPython")
    assert any("换行" in item or "排版" in item for item in result["issues"])


def test_short_content_detected():
    result = diagnose_resume_local("Python developer.")
    assert any("简短" in item for item in result["issues"])
    assert result["score"] == 45


def test_missing_quantification_flagged():
    text = (
        GOOD_RESUME.replace("QPS 提升 30%", "提升性能")
        .replace("耗时降低 40%", "降低耗时")
        .replace("下降 50%", "下降明显")
    )
    result = diagnose_resume_local(text)
    assert any("量化" in item for item in result["issues"])
    assert result["score"] < 75


def test_skills_extraction_is_deterministic():
    result = diagnose_resume_local(GOOD_RESUME)
    for skill in ("Python", "Redis", "Docker", "Kubernetes"):
        assert skill in result["skills"]


def test_keyword_boundary_avoids_substring_matches():
    # "Java" must not be reported just because "JavaScript" appears.
    result = diagnose_resume_local("熟悉 JavaScript 与 React")
    assert "Java" not in result["skills"]
    assert "JavaScript" in result["skills"]


def test_no_llm_client_needed_and_never_raises():
    # Pure function: weird inputs must not raise.
    assert diagnose_resume_local("   ")
    assert diagnose_resume_local("\n" * 20)
    assert diagnose_resume_local("x" * 20000)