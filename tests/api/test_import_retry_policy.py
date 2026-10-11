"""Preanalyze retry policy (grilling module 1, error-handling chain).

Only transient LLM failures (timeout / connection / rate limit) are retried,
with 3 retries and a fixed 1s/2s/4s backoff, per failed row, inline.
Deterministic failures (auth/quota/parse/schema/empty) are never retried.

Both preanalysis sweeps share one helper: the import auto-preanalyze chain and
the one-click "preanalyze all unanalyzed" batch, so the two paths must agree
on which failures are retried and on the recorded error text.
"""
from unittest.mock import patch

from resualign.api.services import jobs as jobs_service
from resualign.api.services.jobs import PreanalyzeUnavailable
from resualign.contracts.errors import LlmFailureCode
from resualign.engine.llm import LLMResponseError


def _run(side_effect, batch=None):
    batch = batch if batch is not None else {"preanalyze": True}
    with patch.object(
        jobs_service, "preanalyze_job", side_effect=side_effect
    ), patch.object(jobs_service.time, "sleep") as sleep:
        jobs_service._preanalyze_imported_job(
            batch, {"user_id": "t"}, {"job_id": "job-1", "title": "Engineer"}
        )
    return batch, sleep


def test_transient_failure_retries_then_succeeds():
    calls = []

    def side_effect(user, job_id):
        calls.append(job_id)
        if len(calls) < 3:
            raise LLMResponseError("slow node", LlmFailureCode.TIMEOUT)
        return {"jd_profile": {"must_have_skills": ["Python"]}}

    batch, sleep = _run(side_effect)
    assert len(calls) == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]
    assert batch.get("analyzed") == 1
    assert "analyze_errors" not in batch


def test_transient_failure_exhausts_three_retries():
    calls = []

    def side_effect(user, job_id):
        calls.append(job_id)
        raise LLMResponseError("rate limited", LlmFailureCode.RATE_LIMIT)

    batch, sleep = _run(side_effect)
    assert len(calls) == 4  # initial attempt + 3 retries
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0, 4.0]
    assert batch.get("analyzed") is None
    error = batch["analyze_errors"][0]
    assert "Engineer" in error and "重试 3 次后仍失败" in error


def test_definitive_failure_is_not_retried():
    calls = []

    def side_effect(user, job_id):
        calls.append(job_id)
        raise LLMResponseError("insufficient balance", LlmFailureCode.QUOTA)

    batch, sleep = _run(side_effect)
    assert len(calls) == 1
    assert sleep.call_count == 0
    assert "Engineer" in batch["analyze_errors"][0]


def test_parse_failure_is_not_retried():
    calls = []

    def side_effect(user, job_id):
        calls.append(job_id)
        raise LLMResponseError("not json", LlmFailureCode.PARSE)

    batch, sleep = _run(side_effect)
    assert len(calls) == 1
    assert sleep.call_count == 0


def test_unavailable_stops_the_sweep_without_retry():
    calls = []

    def side_effect(user, job_id):
        calls.append(job_id)
        raise PreanalyzeUnavailable("模型服务不可用", 503, "configure a node")

    batch, sleep = _run(side_effect)
    assert len(calls) == 1
    assert sleep.call_count == 0
    assert batch["preanalyze"] is False
    assert "预分析已停止" in batch["analyze_errors"][0]


def _run_batch(side_effect, jobs=None):
    jobs = jobs or {"job-1": {"job_id": "job-1", "title": "Engineer"}}
    batch = {
        "user_id": "t",
        "job_ids": list(jobs),
        "analyzed": 0,
        "skipped": 0,
        "errors": [],
        "done": False,
    }
    with patch.object(
        jobs_service, "preanalyze_job", side_effect=side_effect
    ), patch.object(
        jobs_service.time, "sleep"
    ) as sleep, patch.object(
        jobs_service, "set_llm_tenant", return_value=None
    ), patch.object(
        jobs_service, "reset_llm_tenant"
    ), patch.object(
        jobs_service, "job_needs_preanalyze", return_value=True
    ), patch.object(
        jobs_service.context, "_preanalyze_batches", {"b1": batch}
    ), patch.object(
        jobs_service.context, "_jobs"
    ) as store:
        store.get_job.side_effect = lambda user_id, job_id: jobs[job_id]
        jobs_service._run_preanalyze_batch("b1")
    return batch, sleep


def test_batch_retries_transient_failure_then_counts():
    calls = []

    def side_effect(user, job_id):
        calls.append(job_id)
        if len(calls) < 3:
            raise LLMResponseError("slow node", LlmFailureCode.TIMEOUT)
        return {"jd_profile": {"must_have_skills": ["Python"]}}

    batch, sleep = _run_batch(side_effect)
    assert len(calls) == 3
    assert [call.args[0] for call in sleep.call_args_list] == [1.0, 2.0]
    assert batch["analyzed"] == 1
    assert batch["errors"] == []


def test_batch_records_retry_suffix_on_exhaustion():
    def side_effect(user, job_id):
        raise LLMResponseError("rate limited", LlmFailureCode.RATE_LIMIT)

    batch, sleep = _run_batch(side_effect)
    assert len(sleep.call_args_list) == 3
    error = batch["errors"][0]
    assert "Engineer" in error and "重试 3 次后仍失败" in error
    assert batch["analyzed"] == 0


def test_batch_stops_on_unavailable_without_retry():
    def side_effect(user, job_id):
        raise PreanalyzeUnavailable("模型服务不可用", 503, "no node")

    batch, sleep = _run_batch(side_effect)
    assert sleep.call_count == 0
    assert batch["stopped"] is True
    assert "预分析已停止" in batch["errors"][0]


def test_batch_records_gap_stage_error_but_keeps_row_analyzed():
    """A degraded gap stage is not a clean success: the profile landed, the
    gap did not, and the reason has to reach the batch report."""

    def side_effect(user, job_id):
        return {
            "jd_profile": {"must_have_skills": ["Python"]},
            "gap_report": None,
            "error": "缺口分析未完成（rate_limit），JD 画像已生成，可单独重试缺口分析",
        }

    batch, sleep = _run_batch(side_effect)
    assert sleep.call_count == 0
    assert batch["analyzed"] == 1
    assert len(batch["errors"]) == 1
    assert "缺口分析未完成" in batch["errors"][0]
    assert "Engineer" in batch["errors"][0]
