"""Tests for deterministic salary range extraction."""

from resualign.salary import extract_salary_range


def test_monthly_k_range():
    assert extract_salary_range("15-25K") == (15000.0, 25000.0)


def test_monthly_k_lowercase_and_spaces():
    assert extract_salary_range("20k-30k") == (20000.0, 30000.0)
    assert extract_salary_range("20K - 30K") == (20000.0, 30000.0)


def test_annual_wan_range():
    assert extract_salary_range("30-50万/年") == (25000.0, 41666.67)


def test_monthly_wan_range():
    assert extract_salary_range("1-2万/月") == (10000.0, 20000.0)


def test_single_floor():
    assert extract_salary_range("15K以上") == (15000.0, None)


def test_negotiable():
    assert extract_salary_range("薪资面议") == (None, None)


def test_no_salary_text():
    assert extract_salary_range("Python backend engineer.") == (None, None)


def test_compensation_multiplier_suffix():
    assert extract_salary_range("20-30K·14薪") == (20000.0, 30000.0)
