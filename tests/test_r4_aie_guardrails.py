"""R4 AIE call-layer guardrails (03-AIE §③ commit 2).

FakeLLM/httpx-mock dry runs — no real LLM calls:
- P0-1: LLMResponseError structured ``code`` mapping + code-first failure copy
- P0-2: per-role max_tokens clamping and length-doubling cap
- P0-3: wall-clock deadline interrupts a slow single POST
- P0-4: conditional transport retry (short roles only; deadline never retried)
- P0-5: chat_json keeps json_object on corrective retry; engine gap degradation
- P0-6: consecutive-failure circuit breaker (recent_fail_streak + task entry)
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException

import resualign.api as api_module
from resualign.api.services.jobs import _job_failure_detail
from resualign.jobs import JobRegistry
from resualign.llm import LLMResponseError, OpenAIClient
from resualign.models import JDProfile, ResuAlignConfig

from .conftest import MockLLMClient, _diag, _jd_profile_only, _tailor


def _cfg(**overrides) -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key="sk-test",
        model="m1",
        **overrides,
    )


# ---------------------------------------------------------------------------
# P0-1: structured failure codes
# ---------------------------------------------------------------------------


def test_chat_json_http_402_maps_to_quota(httpx_mock):
    client = OpenAIClient(_cfg())
    client.max_retries = 1
    httpx_mock.add_response(status_code=402)
    httpx_mock.add_response(status_code=402)
    with _freeze_sleep(), pytest.raises(LLMResponseError) as exc_info:
        client.chat_json("s", "u")
    assert exc_info.value.code == "quota"


def test_chat_json_http_401_maps_to_auth(httpx_mock):
    client = OpenAIClient(_cfg())
    client.max_retries = 1
    httpx_mock.add_response(status_code=401)
    httpx_mock.add_response(status_code=401)
    with _freeze_sleep(), pytest.raises(LLMResponseError) as exc_info:
        client.chat_json("s", "u")
    assert exc_info.value.code == "auth"


def test_chat_json_http_429_maps_to_rate_limit(httpx_mock):
    client = OpenAIClient(_cfg())
    client.max_retries = 1
    httpx_mock.add_response(status_code=429)
    httpx_mock.add_response(status_code=429)
    with _freeze_sleep(), pytest.raises(LLMResponseError) as exc_info:
        client.chat_json("s", "u")
    assert exc_info.value.code == "rate_limit"


def test_chat_json_transport_timeout_maps_to_timeout_code(httpx_mock):
    client = OpenAIClient(_cfg())
    httpx_mock.add_exception(httpx.ReadTimeout("read timed out"))
    with _freeze_sleep(), pytest.raises(LLMResponseError) as exc_info:
        client.chat_json("s", "u")
    assert exc_info.value.code == "timeout"


def test_chat_structured_schema_failure_maps_to_schema_code(httpx_mock):
    from resualign.schema_registry import AnalysisSchema

    client = OpenAIClient(_cfg())
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": "high", "skills": "x"}'}}
            ]
        }
    )
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": "high", "skills": "x"}'}}
            ]
        }
    )
    with _freeze_sleep(), pytest.raises(LLMResponseError) as exc_info:
        client.chat_structured("s", "u", AnalysisSchema)
    assert exc_info.value.code == "schema"


def test_job_failure_detail_branches_by_code():
    assert "模型响应超时" in _job_failure_detail(
        "jd_analysis", LLMResponseError("mystery text", code="timeout")
    )
    assert "欠费" in _job_failure_detail(
        "jd_analysis", LLMResponseError("mystery text", code="quota")
    )
    assert "API Key" in _job_failure_detail(
        "jd_analysis", LLMResponseError("mystery text", code="auth")
    )
    assert "为空" in _job_failure_detail(
        "jd_analysis", LLMResponseError("mystery text", code="empty")
    )
    assert "格式异常" in _job_failure_detail(
        "jd_analysis", LLMResponseError("mystery text", code="schema")
    )
    assert "模型服务暂时不可用" in _job_failure_detail(
        "jd_analysis", LLMResponseError("mystery text", code="http")
    )
    # code="other"（无 code 构造）回退文本分类：401 文本仍识别为 auth。
    assert "API Key" in _job_failure_detail(
        "jd_analysis",
        LLMResponseError("Client error '401 Unauthorized' for url ..."),
    )


# ---------------------------------------------------------------------------
# P0-2: per-role max_tokens + doubling cap
# ---------------------------------------------------------------------------


def test_role_router_clamps_max_tokens_and_deadline():
    from resualign import role_router

    recorded: list[dict] = []

    class FakeClient:
        def __init__(
            self,
            config,
            timeout=None,
            max_retries=None,
            max_tokens=None,
            token_cap=None,
            deadline=None,
            retry_transport=None,
        ):
            recorded.append(
                {
                    "timeout": timeout,
                    "max_tokens": max_tokens,
                    "token_cap": token_cap,
                    "deadline": deadline,
                    "retry_transport": retry_transport,
                }
            )

    class _Node:
        def resolve_node_for_role(self, tenant_id, role):
            return {
                "provider": "deepseek",
                "model": "m",
                "api_key": "k",
                "base_url": "",
            }

    original = role_router.OpenAIClient
    role_router.OpenAIClient = FakeClient
    try:
        role_router.create_client_for_role(_Node(), "t", "profiler")
        role_router.create_client_for_role(_Node(), "t", "editor")
        role_router.create_client_for_role(_Node(), "t", "evaluator")
    finally:
        role_router.OpenAIClient = original

    profiler, editor, evaluator = recorded
    assert profiler["max_tokens"] == 1024
    assert profiler["token_cap"] == 2048
    assert profiler["deadline"] == 30.0
    assert profiler["retry_transport"] is True
    assert profiler["timeout"] == 30.0  # 数值保持 AIE 表不变
    assert editor["max_tokens"] == 3072
    assert editor["retry_transport"] is False  # 长生成角色不重试 transport
    assert evaluator["max_tokens"] == 384
    # 护栏数值未被本轮改动（AIE 决策域回归断言）
    assert role_router._ROLE_TIMEOUT_DEFAULTS == {
        "diagnose": 45.0,
        "profiler": 30.0,
        "gap_analyzer": 30.0,
        "editor": 90.0,
        "evaluator": 60.0,
    }


def test_chat_json_length_doubling_respects_token_cap(httpx_mock):
    client = OpenAIClient(_cfg(), max_tokens=200, token_cap=400)
    client.max_retries = 1
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "thinking...",
                    },
                    "finish_reason": "length",
                }
            ]
        }
    )
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"ok": true}'}}]}
    )
    with _freeze_sleep():
        result = client.chat_json("s", "u")
    assert result == {"ok": True}
    bodies = [json.loads(r.read()) for r in httpx_mock.get_requests()]
    assert bodies[0]["max_tokens"] == 200
    assert bodies[1]["max_tokens"] == 400  # min(200*2, cap=400)


# ---------------------------------------------------------------------------
# P0-3: wall-clock deadline
# ---------------------------------------------------------------------------


def _freeze_sleep():
    return patch("resualign.llm.time.sleep")


def test_wall_clock_deadline_interrupts_slow_post():
    def slow_handler(request):
        time.sleep(0.4)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}
        )

    client = OpenAIClient(_cfg(), deadline=0.15)
    client._client = httpx.Client(
        transport=httpx.MockTransport(slow_handler),
        timeout=httpx.Timeout(5.0),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.monotonic()
    with pytest.raises(LLMResponseError) as exc_info:
        client.chat_json("s", "u")
    elapsed = time.monotonic() - t0
    assert exc_info.value.code == "timeout"
    assert "wall-clock deadline exceeded" in str(exc_info.value)
    assert elapsed < 0.35  # 墙钟确实在 deadline 处切断，而非等慢响应跑完


# ---------------------------------------------------------------------------
# P0-4: conditional transport retry
# ---------------------------------------------------------------------------


def test_short_role_transport_retries_once_then_succeeds(httpx_mock):
    client = OpenAIClient(_cfg(), retry_transport=True)
    httpx_mock.add_exception(httpx.ReadTimeout("first jitter"))
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"ok": true}'}}]}
    )
    with _freeze_sleep():
        result = client.chat_json("s", "u")
    assert result == {"ok": True}
    assert len(httpx_mock.get_requests()) == 2


def test_transport_retry_counter_not_infinite(httpx_mock):
    client = OpenAIClient(_cfg(), retry_transport=True)
    httpx_mock.add_exception(httpx.ReadTimeout("a"))
    httpx_mock.add_exception(httpx.ReadTimeout("b"))
    with _freeze_sleep(), pytest.raises(LLMResponseError) as exc_info:
        client.chat_json("s", "u")
    assert exc_info.value.code == "timeout"
    assert len(httpx_mock.get_requests()) == 2  # max_retries=1 → 至多 2 次


# ---------------------------------------------------------------------------
# P0-5: json_object preserved on corrective retry + engine gap degradation
# ---------------------------------------------------------------------------


def test_chat_json_keeps_json_object_format_on_retry(httpx_mock):
    client = OpenAIClient(_cfg())
    client.max_retries = 1
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": "no json here"}}]}
    )
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"ok": true}'}}]}
    )
    with _freeze_sleep():
        result = client.chat_json("s", "u")
    assert result == {"ok": True}
    bodies = [json.loads(r.read()) for r in httpx_mock.get_requests()]
    assert len(bodies) == 2
    assert all(b.get("response_format") == {"type": "json_object"} for b in bodies)


class _FakeNodeStore:
    def get_active_node(self, tenant_id):
        return {"name": "fake-node"}


def _profile_obj() -> "JDProfile":
    return JDProfile(
        must_have_skills=["Java"],
        nice_to_have_skills=["Redis"],
        soft_skills=[],
        business_scenarios=["Backend"],
        min_years_experience=None,
        education_requirements=[],
    )


def _tailor_resume_obj():
    from resualign.models import DiffItem, TailoredResume

    return TailoredResume(
        sections={"experience": "Built services using Java"},
        diffs=[
            DiffItem(
                diff_id="d1",
                section="",
                type="modify",
                original="Python dev",
                proposed="Built services using Java",
                reason="match",
                confidence="high",
                provenance="Python dev",
                provenance_quote="Python dev",
                source_span=(0, 9),
                provenance_state="verified",
            )
        ],
        invalid_diffs=[],
    )


def test_engine_gap_degrades_on_schema_failure_in_role_path(monkeypatch):
    from resualign.engine import run
    from resualign.models import ResuAlignConfig

    def fake_call_with_role(role, fn, node_store, tenant_id, *, fn_kwargs=None,
                            default_config=None):
        if role == "diagnose":
            return _diag(), {"role": "diagnose"}
        if role == "profiler":
            return _profile_obj(), {"role": "profiler"}
        if role == "gap_analyzer":
            raise LLMResponseError(
                "Structured response failed schema validation after 2 attempts: x",
                code="schema",
            )
        if role == "editor":
            return _tailor_resume_obj(), {"role": "editor"}
        raise AssertionError(f"unexpected role {role}")

    monkeypatch.setattr("resualign.engine.call_with_role", fake_call_with_role)
    report = run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        "Java backend",
        node_store=_FakeNodeStore(),
        tenant_id="t",
    )
    assert report.gap_report is not None
    assert report.gap_degraded is True  # 降级标记
    assert report.tailored_resume is not None  # 任务继续而非整体 fail


def test_engine_gap_non_structural_failure_still_raises(monkeypatch):
    from resualign.engine import run
    from resualign.models import ResuAlignConfig

    def fake_call_with_role(role, fn, node_store, tenant_id, *, fn_kwargs=None,
                            default_config=None):
        if role == "diagnose":
            return _diag(), {"role": "diagnose"}
        if role == "profiler":
            return _profile_obj(), {"role": "profiler"}
        if role == "gap_analyzer":
            raise LLMResponseError("LLM call failed after 2 attempts (network timeout): t",
                                   code="timeout")
        raise AssertionError(f"unexpected role {role}")

    monkeypatch.setattr("resualign.engine.call_with_role", fake_call_with_role)
    with pytest.raises(LLMResponseError):
        run(
            ResuAlignConfig(model="m"),
            "Python dev resume",
            "Java backend",
            node_store=_FakeNodeStore(),
            tenant_id="t",
        )


def test_engine_gap_degrades_in_plain_client_path():
    """非 role 分支（无节点）同样降级（engine.run 非 use_roles 路径）。"""
    from resualign.engine import run
    from resualign.models import ResuAlignConfig

    class GapSchemaFailClient(MockLLMClient):
        def chat_structured(self, system, user, schema_model, model=None):
            if getattr(schema_model, "__name__", "") == "GapReport":
                raise LLMResponseError("schema failed", code="schema")
            return super().chat_structured(system, user, schema_model, model=model)

    mock = GapSchemaFailClient([_diag(), _jd_profile_only(), _tailor()])
    report = run(
        ResuAlignConfig(model="m"),
        "Python dev resume",
        "Java backend",
        llm_client=mock,
    )
    assert report.gap_degraded is True
    assert report.tailored_resume is not None


# ---------------------------------------------------------------------------
# P0-6: consecutive-failure circuit breaker
# ---------------------------------------------------------------------------


def test_recent_fail_streak_counts_consecutive_failures(tmp_path):
    reg = JobRegistry(db_path=tmp_path / "streak.db")
    for _ in range(3):
        job = reg.create({"library_job_id": "lib-1"}, config=None, tenant_id="t1")
        reg.fail(job.job_id, "boom")
    assert reg.recent_fail_streak("t1", "lib-1") == 3

    # 一次成功重置熔断计数
    ok = reg.create({"library_job_id": "lib-1"}, config=None, tenant_id="t1")
    reg.succeed(ok.job_id, {"ok": True})
    assert reg.recent_fail_streak("t1", "lib-1") == 0
    assert reg.recent_fail_streak("t1", "lib-other") == 0
    assert reg.recent_fail_streak("t1", "") == 0


def test_enforce_llm_task_entry_blocks_after_three_failures(tmp_path, monkeypatch):
    from resualign.api.services.cost_guard import enforce_llm_task_entry
    from resualign.llm_usage import LLMUsageStore
    from resualign.settings_store import SettingsStore

    reg = JobRegistry(db_path=tmp_path / "entry.db")
    monkeypatch.setattr(api_module, "_registry", reg)
    monkeypatch.setattr(
        api_module, "_settings_store", SettingsStore(db_path=tmp_path / "s.db")
    )
    monkeypatch.setattr(
        api_module, "_llm_usage", LLMUsageStore(db_path=tmp_path / "u.db")
    )

    enforce_llm_task_entry("t1")  # 无 job_ref_key：仅 cap 检查，不拦截
    for _ in range(3):
        job = reg.create({"library_job_id": "lib-2"}, config=None, tenant_id="t1")
        reg.fail(job.job_id, "boom")

    with pytest.raises(HTTPException) as exc_info:
        enforce_llm_task_entry("t1", job_ref_key="lib-2")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail["code"] == "repeated_failures"
