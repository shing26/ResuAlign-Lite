"""Unit coverage for the bullet-level map-reduce editor (Phase 2, ADR-0032)."""

import re

import pytest

from resualign.llm import LLMResponseError
from resualign.models import TailoredResume
from resualign.schema_registry import TailoredResumeSchema
from resualign.tailor import METRIC_PLACEHOLDER, tailor_resume_map_reduce


class MockBulletLLM:
    """Thread-safe fake LLM for single-bullet and whole-doc editor calls."""

    model = "m-bullet"

    def __init__(self):
        self.calls = []
        self.fail_original = None

    def chat_structured(self, system, user, schema_model, model=None):
        name = getattr(schema_model, "__name__", "")
        if name == TailoredResumeSchema.__name__:
            # Whole-doc fallback shape (no bullets / all-bullets-failed).
            return {
                "sections": {"experience": "Fallback whole-doc text."},
                "diffs": [{
                    "type": "modify",
                    "section": "experience",
                    "original": "original",
                    "proposed": "fallback proposed",
                    "reason": "declined",
                    "confidence": "high",
                    "provenance": "original",
                }],
            }
        self.calls.append(user)
        match = re.search(r"Original bullet:\n(.*?)\n", user)
        original = match.group(1).strip() if match else "bullet"
        if self.fail_original and original == self.fail_original:
            raise LLMResponseError("single bullet generation failed")
        return {
            "proposed": f"{original} (high concurrency)",
            "reason": "Matches JD high-concurrency scenario",
        }


def _gap_report_json(phrases):
    import json

    return json.dumps({
        "missing_keywords": phrases,
        "misaligned_emphasis": [],
        "strength_matches": [],
        "business_scenarios": [],
        "jd_context": phrases[0] if phrases else "",
    }, ensure_ascii=False)


RESUME = (
    "张三\n\n工作经历\n"
    "- 使用 Python 开发后端服务\n"
    "- 使用 Redis 做缓存与会话管理\n"
)


def test_map_reduce_targets_first_bullet_by_fallback():
    llm = MockBulletLLM()
    result = tailor_resume_map_reduce(
        llm, RESUME, _gap_report_json(["FastAPI async endpoints"])
    )
    assert isinstance(result, TailoredResume)
    assert len(result.diffs) == 1
    d = result.diffs[0]
    assert d.original == "使用 Python 开发后端服务"
    assert d.proposed.startswith("使用 Python 开发后端服务 (high concurrency)")
    assert METRIC_PLACEHOLDER in d.proposed
    assert d.section == "工作经历"
    assert d.provenance_state == "verified"
    # source_span must point into the full resume text (not the bare bullet).
    assert d.source_span is not None
    assert RESUME[d.source_span[0]:d.source_span[1]] == d.original
    # Untouched bullet passes through verbatim in the reassembled section.
    assert "使用 Redis 做缓存与会话管理" in result.sections.get("工作经历", "")


def test_map_reduce_targets_bullet_matching_focus_phrase():
    llm = MockBulletLLM()
    result = tailor_resume_map_reduce(
        llm, RESUME, _gap_report_json(["Redis"])
    )
    assert len(result.diffs) == 1
    assert result.diffs[0].original == "使用 Redis 做缓存与会话管理"


def test_map_reduce_records_single_failure_and_keeps_others():
    llm = MockBulletLLM()
    llm.fail_original = "使用 Python 开发后端服务"
    # Match Redis so the other bullet is a target too; the failed Python
    # bullet is not a focus match, so force it via a broad fallback instead.
    # Here both bullets match (Python/focus includes Python) and one fails.
    result = tailor_resume_map_reduce(
        llm, RESUME, _gap_report_json(["Python", "Redis"])
    )
    # The failed Python bullet is recorded as an invalid diff (Phase 4 hook).
    assert any(d.original == "使用 Python 开发后端服务"
               for d in result.invalid_diffs)
    assert any(d.original == "使用 Redis 做缓存与会话管理"
               for d in result.diffs)
    # The run still produced a coherent TailoredResume.
    assert isinstance(result, TailoredResume)


def test_map_reduce_runs_concurrently_for_multiple_targets():
    llm = MockBulletLLM()
    result = tailor_resume_map_reduce(
        llm, RESUME, _gap_report_json(["Python", "Redis"]), parallel=True
    )
    assert {d.original for d in result.diffs} == {
        "使用 Python 开发后端服务",
        "使用 Redis 做缓存与会话管理",
    }


def test_map_reduce_falls_back_to_whole_doc_without_bullets():
    llm = MockBulletLLM()
    result = tailor_resume_map_reduce(
        llm, "Just a title line\nAnother plain line",
        _gap_report_json(["FastAPI"]),
    )
    assert isinstance(result, TailoredResume)


def test_map_reduce_rejects_invalid_granularity():
    with pytest.raises(ValueError, match="granularity"):
        tailor_resume_map_reduce(
            MockBulletLLM(), RESUME, _gap_report_json(["Redis"]),
            granularity="ultra",
        )
