"""Tests for the deterministic worth appraisal engine."""

import pytest

from resualign.appraisal import (
    compute_appraisal,
    normalize_city,
    resolve_salary_benchmark,
)


def _job(**overrides):
    payload = {
        "job_id": "job-1",
        "title": "Backend Engineer",
        "company": "Acme",
        "location": "Shanghai",
        "salary_min": 20000,
        "salary_max": 30000,
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Python", "FastAPI"],
        "source_type": "paste",
        "status": "未投递",
    }
    payload.update(overrides)
    return payload


def test_appraisal_formula_and_default_weights():
    result = compute_appraisal(
        _job(),
        resume_match_score=80,
        salary_benchmark=25000,
    )
    assert result["verdict"] in {"投递", "考虑", "放弃"}
    assert result["score"] == pytest.approx(
        80 * 0.4 + 100 * 0.3 + 100 * 0.2 + 100 * 0.1
    )
    assert result["components"]["match"] == 80
    assert result["components"]["salary"] == 100
    assert result["components"]["hard_conditions"] == 100
    assert result["components"]["quality"] == 100
    assert any("薪资" in r for r in result["reasons"])


def test_appraisal_salary_below_benchmark_scales_down():
    result = compute_appraisal(
        _job(salary_min=15000, salary_max=25000),
        resume_match_score=50,
        salary_benchmark=25000,
    )
    assert result["components"]["salary"] == pytest.approx(80.0)


def test_appraisal_missing_salary_is_neutral():
    result = compute_appraisal(
        _job(salary_min=None, salary_max=None),
        resume_match_score=50,
        salary_benchmark=25000,
    )
    assert result["components"]["salary"] == 50


def test_appraisal_missing_benchmark_is_neutral():
    result = compute_appraisal(
        _job(),
        resume_match_score=50,
        salary_benchmark=None,
    )
    assert result["components"]["salary"] == 50


def test_appraisal_missing_match_is_neutral():
    result = compute_appraisal(
        _job(),
        resume_match_score=None,
        salary_benchmark=25000,
    )
    assert result["components"]["match"] == 50


def test_appraisal_hard_conditions_use_resume_years_and_education():
    junior = compute_appraisal(
        _job(seniority="高级"),
        resume_match_score=80,
        salary_benchmark=25000,
        resume_years=2,
        resume_education="本科",
    )
    assert junior["components"]["hard_conditions"] == 80

    masters_required = compute_appraisal(
        _job(seniority="高级", education_requirement="硕士"),
        resume_match_score=80,
        salary_benchmark=25000,
        resume_years=5,
        resume_education="本科",
    )
    assert masters_required["components"]["hard_conditions"] == 80

    doctorate_satisfies_masters = compute_appraisal(
        _job(seniority="高级", education_requirement="硕士"),
        resume_match_score=80,
        salary_benchmark=25000,
        resume_years=5,
        resume_education="博士",
    )
    assert (
        doctorate_satisfies_masters["components"]["hard_conditions"] == 100
    )


def test_resume_profile_parses_years_and_education():
    from resualign.appraisal import resume_profile

    assert resume_profile("5 years backend experience, 硕士") == {
        "years": 5.0,
        "education": "硕士",
    }
    assert resume_profile("Python developer with 3年经验，本科")["years"] == 3.0
    assert resume_profile("No obvious years, 博士")["education"] == "博士"
    assert resume_profile("2024年毕业，本科")["years"] is None
    assert resume_profile("") == {"years": None, "education": None}


def test_appraisal_verdict_thresholds():
    high = compute_appraisal(
        _job(), resume_match_score=100, salary_benchmark=20000
    )
    low = compute_appraisal(
        _job(
            company=None,
            location=None,
            salary_min=10000,
            salary_max=12000,
            tech_tags=[],
        ),
        resume_match_score=10,
        salary_benchmark=25000,
    )
    assert high["verdict"] == "投递"
    assert low["verdict"] == "放弃"


def test_appraisal_rejects_invalid_weights():
    with pytest.raises(ValueError, match="weights"):
        compute_appraisal(
            _job(),
            resume_match_score=50,
            salary_benchmark=25000,
            weights={"match": 40, "salary": 30, "hard_conditions": 20},
        )


def test_normalize_city_handles_suffixes_and_aliases():
    assert normalize_city("北京市") == "北京"
    assert normalize_city("北京") == "北京"
    assert normalize_city("北京朝阳区") == "北京"
    assert normalize_city("北京市朝阳区") == "北京"
    assert normalize_city("上海市") == "上海"
    assert normalize_city("上海市浦东新区") == "上海"
    assert normalize_city("shenzhen") == "深圳"
    assert normalize_city(" 北京 ") == "北京"
    assert normalize_city("") == ""
    assert normalize_city(None) == ""


def test_resolve_salary_benchmark_prefers_settings_row():
    settings = {
        "salary_reference": [
            {
                "job_function": "后端",
                "city": "北京市",
                "p50": 30000,
                "p75": 45000,
            },
            {
                "job_function": "前端",
                "city": "北京",
                "p50": 28000,
                "p75": 42000,
            },
        ]
    }
    value, source = resolve_salary_benchmark(
        settings, _job(location="北京朝阳区"), 20000
    )
    assert value == 30000
    assert source == "设置表（城市）"


def test_resolve_salary_benchmark_uses_first_matching_row():
    settings = {
        "salary_reference": [
            {"job_function": "后端", "city": "北京", "p50": 30000, "p75": 48000},
            {"job_function": "后端", "city": "北京市", "p50": 32000, "p75": 50000},
        ]
    }
    value, _ = resolve_salary_benchmark(
        settings, _job(location="北京"), 20000
    )
    assert value == 30000


def test_resolve_salary_benchmark_falls_back_to_library_median():
    value, source = resolve_salary_benchmark(
        {"salary_reference": []}, _job(), 22000
    )
    assert value == 22000
    assert source == "库内同类中位"


def test_resolve_salary_benchmark_neutral_when_no_benchmark():
    value, source = resolve_salary_benchmark({}, _job(), None)
    assert value is None
    assert source == "暂无基准"


def test_compute_appraisal_uses_settings_benchmark_and_marks_source():
    settings = {
        "salary_reference": [
            {
                "job_function": "后端",
                "city": "上海",
                "p50": 25000,
                "p75": 40000,
            }
        ]
    }
    result = compute_appraisal(
        _job(salary_min=15000, salary_max=25000),
        resume_match_score=50,
        settings=settings,
        library_median=20000,
    )
    assert result["salary_benchmark"] == 25000
    assert result["benchmark_source"] == "设置表（城市）"
    assert result["components"]["salary"] == pytest.approx(80.0)
    assert any("设置表（城市）" in r for r in result["reasons"])
    assert result["city_normalized"] == "上海"


def test_compute_appraisal_falls_back_to_library_median():
    result = compute_appraisal(
        _job(),
        resume_match_score=50,
        settings={"salary_reference": []},
        library_median=30000,
    )
    assert result["benchmark_source"] == "库内同类中位"
    assert result["salary_benchmark"] == 30000


def test_compute_appraisal_neutral_when_no_benchmark():
    result = compute_appraisal(
        _job(),
        resume_match_score=50,
        settings={"salary_reference": []},
        library_median=None,
    )
    assert result["benchmark_source"] == "暂无基准"
    assert result["salary_benchmark"] is None
    assert any("暂无基准" in r for r in result["reasons"])


def test_compute_appraisal_legacy_benchmark_keeps_source_semantics():
    result = compute_appraisal(
        _job(), resume_match_score=50, salary_benchmark=25000
    )
    assert result["benchmark_source"] == "库内同类中位"
    assert result["city_normalized"] == "上海"
