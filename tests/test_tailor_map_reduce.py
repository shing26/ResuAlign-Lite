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


def test_map_reduce_parallel_propagates_tenant_context():
    """P1-3（#77）：ThreadPoolExecutor 必须传播 contextvars——工作线程里的
    LLM 调用要能读到 llm_tenant，否则云节点用量静默逃逸租户计量。"""
    import threading

    from resualign.llm_usage import current_llm_tenant, llm_tenant_context

    seen = []
    lock = threading.Lock()

    class ProbeLLM(MockBulletLLM):
        def chat_structured(self, system, user, schema_model, model=None):
            result = super().chat_structured(system, user, schema_model, model)
            name = getattr(schema_model, "__name__", "")
            if name != TailoredResumeSchema.__name__:
                with lock:
                    seen.append((threading.current_thread().name, current_llm_tenant()))
            return result

    llm = ProbeLLM()
    with llm_tenant_context("tenant-probe"):
        tailor_resume_map_reduce(
            llm, RESUME, _gap_report_json(["Python", "Redis"]), parallel=True
        )
    assert seen, "并行路径应发生多次 bullet 调用"
    assert {tenant for _, tenant in seen} == {"tenant-probe"}


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


class FailAllBulletsLLM(MockBulletLLM):
    """Fails every per-bullet call; whole-doc editor calls still succeed."""

    def chat_structured(self, system, user, schema_model, model=None):
        if getattr(schema_model, "__name__", "") != TailoredResumeSchema.__name__:
            raise LLMResponseError("single bullet generation failed")
        return super().chat_structured(system, user, schema_model, model)


class ProbeWholeDocLLM(FailAllBulletsLLM):
    """Counts whole-document editor calls (TailoredResumeSchema)."""

    def __init__(self):
        super().__init__()
        self.whole_doc_calls = 0

    def chat_structured(self, system, user, schema_model, model=None):
        if getattr(schema_model, "__name__", "") == TailoredResumeSchema.__name__:
            self.whole_doc_calls += 1
        return super().chat_structured(system, user, schema_model, model)


def test_map_reduce_all_failed_falls_back_to_whole_doc_by_default():
    """全败 + 默认 whole_doc_fallback=True：走整文档编辑器（云节点语义）。"""
    llm = ProbeWholeDocLLM()
    tailor_resume_map_reduce(llm, RESUME, _gap_report_json(["Python", "Redis"]))
    assert llm.whole_doc_calls == 1


def test_map_reduce_local_node_all_failed_keeps_partial_result():
    """P1（2026-09-07）：本地节点全败不再走整文档 fallback——7B 模型整文档
    契约 ~200s 必超 editor 90s deadline（engine._editor_call_plan 实测注释），
    fallback 只会把 deadline 烧两遍后整 run 失败。应保留 invalid_diffs
    「生成失败，可单条重试」的诚实部分结果。"""
    llm = ProbeWholeDocLLM()
    result = tailor_resume_map_reduce(
        llm, RESUME, _gap_report_json(["Python", "Redis"]),
        parallel=False, whole_doc_fallback=False,
    )
    assert llm.whole_doc_calls == 0
    assert result.diffs == []
    assert {d.original for d in result.invalid_diffs} == {
        "使用 Python 开发后端服务",
        "使用 Redis 做缓存与会话管理",
    }
    assert all("可单条重试" in (d.reason or "") for d in result.invalid_diffs)
    # Sections reassembled verbatim — no whole-doc text leaked in.
    assert "使用 Python 开发后端服务" in result.sections.get("工作经历", "")
    assert "使用 Redis 做缓存与会话管理" in result.sections.get("工作经历", "")
