import json

import pytest

from resualign.llm import LLMClient, LLMResponseError, OpenAIClient
from resualign.models import ResuAlignConfig
from resualign.schema_registry import (
    Analysis,
    DiffItem,
    EvalScore,
    TailoredResume,
)


def test_schema_registry_exposes_json_schema():
    assert "score" in Analysis.model_json_schema()["properties"]
    assert "type" in DiffItem.model_json_schema()["properties"]
    assert "diffs" in TailoredResume.model_json_schema()["properties"]
    assert "gap_coverage" in EvalScore.model_json_schema()["properties"]


def test_chat_structured_uses_json_schema_for_openai(httpx_mock):
    config = ResuAlignConfig(
        api_key="sk-test",
        model="m1",
        provider="openai",
    )
    client = OpenAIClient(config)
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"score": 80, "issues": [], "skills": ["Python"]}
                        )
                    }
                }
            ]
        }
    )
    result = client.chat_structured("system", "user", Analysis)
    assert result == {"score": 80, "issues": [], "skills": ["Python"]}
    body = json.loads(httpx_mock.get_requests()[0].read())
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == (
        Analysis.model_json_schema()
    )


def test_chat_structured_json_mode_retries_schema_validation(
    httpx_mock, monkeypatch
):
    monkeypatch.setattr("resualign.llm.time.sleep", lambda _: None)
    config = ResuAlignConfig(api_key="sk-test", model="m1")
    client = OpenAIClient(config)
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"score": "not-an-int", "issues": [], "skills": []}'
                        )
                    }
                }
            ]
        }
    )
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"score": 80, "issues": [], "skills": ["Python"]}'
                        )
                    }
                }
            ]
        }
    )
    result = client.chat_structured("system", "user", Analysis)
    assert result["score"] == 80
    assert len(httpx_mock.get_requests()) == 2


class _RetryFallbackClient(LLMClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def chat_json(self, system, user, model=None):
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            return response
        return {}


def test_chat_structured_base_client_retries_then_fails(monkeypatch):
    monkeypatch.setattr("resualign.llm.time.sleep", lambda _: None)
    client = _RetryFallbackClient(
        [
            {"score": "bad", "issues": [], "skills": []},
            {"score": "bad", "issues": [], "skills": []},
            {"score": "bad", "issues": [], "skills": []},
        ]
    )
    with pytest.raises(LLMResponseError, match="schema validation"):
        client.chat_structured("system", "user", Analysis)
    assert client.call_count == 3
