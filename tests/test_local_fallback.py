from resualign.api.services.jobs import _run_local_fallback_report
from resualign.local_fallback import (
    local_ats_score,
    local_diagnose,
    local_gap_report,
)


def test_empty_input_never_raises():
    diagnosed = local_diagnose("")
    assert set(diagnosed) == {"score", "skills", "issues"}
    assert diagnosed["skills"] == []
    assert diagnosed["score"] == 60

    gap = local_gap_report(None, "")
    assert gap["missing_keywords"] == []
    assert gap["strength_matches"] == []

    ats = local_ats_score("", {})
    assert ats["score"] == 1.0


def test_english_resume_detects_content():
    resume = (
        "Experience\n"
        "Backend engineer skilled in Python, FastAPI, and Docker. "
        "Reduced p95 latency by 40% and cut costs by 30%."
        "\nSkills\nPython, Docker, Redis, SQL"
    )
    result = local_diagnose(resume)
    assert result["score"] > 60
    assert "python" in result["skills"]
    assert "docker" in result["skills"]
    assert "No quantified metrics detected." not in result["issues"]
    assert "No recognizable skills section found." not in result["issues"]


def test_chinese_resume_heuristics():
    resume = (
        "教育背景\n北京某大学\n工作经历\n使用 Python 与 FastAPI 开发服务，"
        "将接口延迟降低 40%。\n专业技能\nPython, Redis, SQL"
    )
    result = local_diagnose(resume)
    assert "python" in result["skills"]
    assert "No quantified metrics detected." not in result["issues"]
    assert len(result["issues"]) <= 1


def test_quantified_metrics_detection():
    with_metrics = local_diagnose("Reduced latency by 30% using Python.")
    assert "No quantified metrics detected." not in with_metrics["issues"]

    without_metrics = local_diagnose("Experience\nBuilt services with Python.")
    assert "No quantified metrics detected." in without_metrics["issues"]


def test_missing_vs_matched_jd_keywords():
    jd = "We need Python, Kubernetes, and Redis experience."
    resume = "Python and Redis for backend services."
    gap = local_gap_report(resume, jd)
    assert "python" in gap["strength_matches"]
    assert "redis" in gap["strength_matches"]
    assert "kubernetes" in gap["missing_keywords"]
    assert "python" not in gap["missing_keywords"]


def test_ats_score_with_no_required_skills():
    result = local_ats_score("Python experience", {"required_skills": []})
    assert result["score"] == 1.0
    assert "No required skills specified." in result["details"]

    also_missing = local_ats_score("Python experience", {})
    assert also_missing["score"] == 1.0


def test_case_insensitive_matching():
    gap = local_gap_report("proficient in python and golang", "Python, Golang, Redis")
    assert "python" in gap["strength_matches"]
    assert "golang" in gap["strength_matches"]
    assert "redis" in gap["missing_keywords"]

    ats = local_ats_score("PYTHON DOCKER", {"must_have_skills": ["Python", "Docker", "Kafka"]})
    assert ats["score"] == round(2 / 3, 3)
    assert "Matched: Python" in ats["details"]
    assert "Missing: Kafka" in ats["details"]


def test_ats_score_totals():
    profile = {"required_skills": ["Python", "SQL", "Kubernetes", "Redis"]}
    result = local_ats_score("Python, SQL, and Redis", profile)
    assert result["score"] == 0.75
    assert sum("Matched:" in d for d in result["details"]) == 3
    assert sum("Missing:" in d for d in result["details"]) == 1


def test_worker_local_fallback_report_marks_engine():
    report = _run_local_fallback_report(
        "Experience\nBackend engineer using Python and FastAPI. "
        "Cut latency by 30%.",
        "",
    )
    assert report.fallback == "local"
    assert report.model == "local-rules"
    assert report.score > 0
    assert "python" in report.skills
    assert report.gap_report is None
    assert report.eval_score is None


def test_worker_local_fallback_report_with_jd():
    report = _run_local_fallback_report(
        "Backend engineer using Python and Redis.",
        "We need Python, Kubernetes, and Redis.",
    )
    assert report.fallback == "local"
    assert report.gap_report is not None
    assert "kubernetes" in report.gap_report.missing_keywords
    assert "python" in report.gap_report.strength_matches
    assert report.eval_score is not None
