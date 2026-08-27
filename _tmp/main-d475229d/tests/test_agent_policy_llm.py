"""LLM JD intake policy tests (ADR-0029)."""

from __future__ import annotations

import pytest

from resualign.agent.orchestrator import ACTION_KEEP_PENDING, ACTION_RESOLVE
from resualign.agent.policy_llm import LLMJdIntakePolicy
from resualign.llm import LLMResponseError
from resualign.schema_registry import JdIntakeDecisionSchema

_BLOCKER = {
    "blocker_id": "b-1",
    "url": "https://example.com/jobs/1",
    "category": "network_error",
    "reason": "timeout",
}


class _FakeClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat_json(self, system, user, model=None):
        self.calls.append((system, user, model))
        return self.result

    def chat_structured(self, system, user, schema_model, model=None):
        self.calls.append((system, user, schema_model, model))
        return self.result


def test_llm_policy_returns_resolve_with_pasted_text():
    client = _FakeClient(
        {"action": "resolve", "reason": "transient network failure"}
    )
    policy = LLMJdIntakePolicy(client=client)

    assert (
        policy.decide(_BLOCKER, resolve_text="负责后端开发。")
        == ACTION_RESOLVE
    )
    system, user, schema_model, model = client.calls[0]
    assert schema_model is JdIntakeDecisionSchema
    assert "has_pasted_jd_text" in user


def test_llm_policy_keeps_human_only_blocker_pending():
    client = _FakeClient(
        {"action": "keep_pending", "reason": "needs login"}
    )
    policy = LLMJdIntakePolicy(client=client)
    blocker = {**_BLOCKER, "category": "login_required"}

    assert (
        policy.decide(blocker, resolve_text="text") == ACTION_KEEP_PENDING
    )


def test_llm_policy_keeps_pending_without_pasted_text():
    client = _FakeClient({"action": "resolve", "reason": "text exists"})
    policy = LLMJdIntakePolicy(client=client)

    assert policy.decide(_BLOCKER) == ACTION_KEEP_PENDING


def test_llm_policy_rejects_invalid_action():
    client = _FakeClient({"action": "launch", "reason": "oops"})
    policy = LLMJdIntakePolicy(client=client)

    with pytest.raises(LLMResponseError, match="invalid action"):
        policy.decide(_BLOCKER, resolve_text="text")


def test_llm_policy_without_client_requires_api_key(monkeypatch):
    from resualign.agent import policy_llm
    from resualign.models import ResuAlignConfig

    monkeypatch.setattr(
        policy_llm,
        "build_config",
        lambda: ResuAlignConfig(provider="deepseek", api_key=""),
    )
    policy = LLMJdIntakePolicy()

    with pytest.raises(LLMResponseError, match="LLM not configured"):
        policy.decide(_BLOCKER)
