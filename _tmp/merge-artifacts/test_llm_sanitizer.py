"""Sanitizer coverage for provider-model JSON noise (Phase 1 of ADR-0032)."""

import pytest

from resualign.llm import LLMResponseError, _parse_json_object


def test_plain_json_object():
    assert _parse_json_object('{"score": 85, "skills": ["Python"]}') == {
        "score": 85,
        "skills": ["Python"],
    }


def test_leading_prose_before_json():
    raw = 'Here is the revised resume: {"diffs": [{"type": "modify"}]}'
    assert _parse_json_object(raw)["diffs"][0]["type"] == "modify"


def test_markdown_fence_wrapped():
    raw = '```json\n{"a": 1, "b": [2, 3]}\n```'
    assert _parse_json_object(raw) == {"a": 1, "b": [2, 3]}


def test_trailing_text_after_json():
    raw = '{"status": "ok"} plus some notes here.'
    assert _parse_json_object(raw) == {"status": "ok"}


def test_brace_inside_string_is_not_a_delimiter():
    raw = '{"note": "uses {braces} in prose", "keep": true}'
    assert _parse_json_object(raw) == {"note": "uses {braces} in prose", "keep": True}


def test_truncated_unclosed_brackets_are_repaired():
    raw = '{"diffs": [{"type": "modify", "section": "工作经历"'
    parsed = _parse_json_object(raw)
    assert parsed["diffs"][0]["type"] == "modify"
    assert parsed["diffs"][0]["section"] == "工作经历"


def test_truncated_top_level_value_is_repaired():
    assert _parse_json_object('{"score": 8') == {"score": 8}


def test_trailing_comma_is_cleaned():
    raw = '{"skills": ["Python", "Java",]}'
    assert _parse_json_object(raw) == {"skills": ["Python", "Java"]}


def test_missing_brace_raises():
    with pytest.raises(LLMResponseError):
        _parse_json_object("no json here at all")


def test_non_object_json_raises():
    with pytest.raises(LLMResponseError):
        _parse_json_object("[1, 2, 3]")

