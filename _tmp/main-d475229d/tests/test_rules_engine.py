"""Tests for the zero-LLM RuleFilterEngine (Sprint 3)."""

import pytest

from resualign.job_library import JobLibraryStore
from resualign.rules import RuleFilterEngine


@pytest.fixture
def store(tmp_path):
    return JobLibraryStore(db_path=tmp_path / "rules.db")


@pytest.fixture
def engine(store):
    return RuleFilterEngine(store)


def _meta(**overrides):
    meta = {
        "title": "后端开发工程师",
        "jd_text": "负责后端服务开发，双休，月薪 25-35K。",
        "location": "上海",
        "salary_min": 25000,
        "salary_max": 35000,
        "url": "https://example.com/jobs/1",
    }
    meta.update(overrides)
    return meta


def test_no_rules_accepts(engine, store):
    verdict = engine.check("tenant-1", _meta())
    assert verdict.accepted
    assert verdict.reason is None


def test_blacklist_keyword_rejects(engine, store):
    store.create_rule("tenant-1", "blacklist", "外包")
    verdict = engine.check("tenant-1", _meta(jd_text="负责外包项目的交付"))
    assert not verdict.accepted
    assert verdict.rule_type == "blacklist"
    assert "外包" in verdict.reason


def test_blacklist_checks_title(engine, store):
    store.create_rule("tenant-1", "blacklist", "单休")
    verdict = engine.check("tenant-1", _meta(title="单休客服专员"))
    assert not verdict.accepted
    assert verdict.rule_type == "blacklist"


def test_blacklist_matches_url_during_preflight(engine, store):
    store.create_rule("tenant-1", "blacklist", "outsource")
    verdict = engine.check(
        "tenant-1",
        {"url": "https://outsource.example.com/jobs/1"},
        preflight=True,
    )
    assert not verdict.accepted
    assert verdict.rule_type == "blacklist"


def test_blacklist_multiple_tokens_and_chinese_comma(engine, store):
    store.create_rule("tenant-1", "blacklist", "外包，单休,无底薪")
    verdict = engine.check("tenant-1", _meta(jd_text="大小周，无底薪"))
    assert not verdict.accepted
    assert "无底薪" in verdict.reason


def test_blacklist_english_case_insensitive(engine, store):
    store.create_rule("tenant-1", "blacklist", "outsourcing")
    verdict = engine.check("tenant-1", _meta(jd_text="OutSourcing project"))
    assert not verdict.accepted


def test_blacklist_no_match_accepts(engine, store):
    store.create_rule("tenant-1", "blacklist", "外包")
    verdict = engine.check("tenant-1", _meta())
    assert verdict.accepted


def test_city_whitelist_accepts(engine, store):
    store.create_rule("tenant-1", "city_whitelist", "上海,北京")
    verdict = engine.check("tenant-1", _meta(location="上海"))
    assert verdict.accepted


def test_city_whitelist_rejects_outside(engine, store):
    store.create_rule("tenant-1", "city_whitelist", "上海")
    verdict = engine.check("tenant-1", _meta(location="广州"))
    assert not verdict.accepted
    assert verdict.rule_type == "city_whitelist"
    assert "广州" in verdict.reason


def test_city_whitelist_accepts_with_suffix(engine, store):
    store.create_rule("tenant-1", "city_whitelist", "上海市")
    verdict = engine.check("tenant-1", _meta(location="上海"))
    assert verdict.accepted
    verdict = engine.check("tenant-1", _meta(location="上海市"))
    assert verdict.accepted


def test_city_whitelist_empty_value_skips(engine, store):
    # A value that splits into no tokens behaves like an empty whitelist.
    store.create_rule("tenant-1", "city_whitelist", "，")
    verdict = engine.check("tenant-1", _meta(location=None))
    assert verdict.accepted


def test_city_whitelist_unknown_location_rejects(engine, store):
    store.create_rule("tenant-1", "city_whitelist", "上海")
    verdict = engine.check("tenant-1", _meta(location=None))
    assert not verdict.accepted
    assert verdict.rule_type == "city_whitelist"


def test_city_whitelist_unknown_location_skipped_during_preflight(engine, store):
    store.create_rule("tenant-1", "city_whitelist", "上海")
    verdict = engine.check(
        "tenant-1",
        {"url": "https://example.com/jobs/1"},
        preflight=True,
    )
    assert verdict.accepted


def test_min_salary_rejects_below(engine, store):
    store.create_rule("tenant-1", "min_salary", "30000")
    verdict = engine.check("tenant-1", _meta(salary_min=15000, salary_max=20000))
    assert not verdict.accepted
    assert verdict.rule_type == "min_salary"


def test_min_salary_rejects_when_max_below(engine, store):
    store.create_rule("tenant-1", "min_salary", "30000")
    verdict = engine.check("tenant-1", _meta(salary_min=25000, salary_max=29000))
    assert not verdict.accepted


def test_min_salary_accepts_at_threshold(engine, store):
    store.create_rule("tenant-1", "min_salary", "30000")
    verdict = engine.check("tenant-1", _meta(salary_min=30000, salary_max=40000))
    assert verdict.accepted


def test_min_salary_accepts_above(engine, store):
    store.create_rule("tenant-1", "min_salary", "30000")
    verdict = engine.check("tenant-1", _meta(salary_min=32000, salary_max=45000))
    assert verdict.accepted


def test_min_salary_unknown_salary_skips(engine, store):
    store.create_rule("tenant-1", "min_salary", "30000")
    verdict = engine.check("tenant-1", _meta(salary_min=None, salary_max=None))
    assert verdict.accepted


def test_disabled_rule_ignored(engine, store):
    store.create_rule("tenant-1", "blacklist", "外包", enabled=0)
    store.create_rule("tenant-1", "city_whitelist", "上海", enabled=0)
    verdict = engine.check(
        "tenant-1",
        _meta(jd_text="负责外包项目", location="广州"),
    )
    assert verdict.accepted


def test_blacklist_checked_first(engine, store):
    store.create_rule("tenant-1", "city_whitelist", "上海")
    store.create_rule("tenant-1", "blacklist", "外包")
    verdict = engine.check("tenant-1", _meta(location="广州", jd_text="外包项目"))
    assert not verdict.accepted
    assert verdict.rule_type == "blacklist"


def test_rules_scoped_to_tenant(engine, store):
    store.create_rule("tenant-1", "blacklist", "外包")
    verdict = engine.check("tenant-2", _meta(jd_text="负责外包项目"))
    assert verdict.accepted
