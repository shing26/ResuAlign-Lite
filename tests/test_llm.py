import json

import pytest

from resualign.llm import LLMResponseError, OpenAIClient
from resualign.models import ResuAlignConfig


@pytest.fixture
def config():
    return ResuAlignConfig(api_key="sk-test", model="m1")


@pytest.fixture
def client(config):
    return OpenAIClient(config)


def test_chat_json_success(httpx_mock, client):
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 85, "skills": ["Python"]}'}}
            ]
        }
    )
    result = client.chat_json("system", "user text")
    assert result["score"] == 85
    assert "Python" in result["skills"]


def test_chat_json_trailing_text(httpx_mock, client):
    """raw_decode handles trailing text after valid JSON."""
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"diffs": [{"type": "modify"}]} Extra here.'
                    }
                }
            ]
        }
    )
    result = client.chat_json("system", "user")
    assert "diffs" in result
    assert result["diffs"][0]["type"] == "modify"


def test_chat_json_retry_then_fail(httpx_mock, config):
    client = OpenAIClient(config)
    client.max_retries = 1

    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=500)

    with pytest.raises(LLMResponseError):
        client.chat_json("system", "user")


def test_chat_json_no_json(httpx_mock, client):
    for _ in range(client.max_retries + 1):
        httpx_mock.add_response(
            json={
                "choices": [
                    {"message": {"content": "Sorry, no JSON here."}}
                ]
            }
        )
    with pytest.raises(LLMResponseError):
        client.chat_json("system", "user")


def test_chat_json_retries_with_bigger_budget_on_reasoning_length(httpx_mock, client):
    """DeepSeek reasoning can consume max_tokens; retry should raise it."""
    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {"content": "", "reasoning_content": "thinking..."},
                    "finish_reason": "length",
                }
            ]
        }
    )
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 90, "skills": ["Java"]}'}}
            ]
        }
    )
    result = client.chat_json("system", "user")
    assert result["score"] == 90

    bodies = [json.loads(r.read()) for r in httpx_mock.get_requests()]
    assert bodies[0]["max_tokens"] == 16384
    assert bodies[1]["max_tokens"] == 32768


def test_deepseek_chat_json_requests_direct_output(httpx_mock, client):
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 88, "skills": ["Java"]}'}}
            ]
        }
    )
    client.chat_json("system", "user")
    body = json.loads(httpx_mock.get_requests()[0].read())
    assert body["thinking"] == {"type": "disabled"}


def test_openai_client_omits_thinking(httpx_mock):
    openai_client = OpenAIClient(
        ResuAlignConfig(provider="openai", api_key="sk-test", model="m1")
    )
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 88, "skills": ["Java"]}'}}
            ]
        }
    )
    openai_client.chat_json("system", "user")
    body = json.loads(httpx_mock.get_requests()[0].read())
    assert "thinking" not in body


def test_structured_json_mode_expands_budget_on_reasoning_length(httpx_mock, client):
    from resualign.schema_registry import AnalysisSchema

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
        json={
            "choices": [
                {"message": {"content": '{"score": 90, "skills": ["Go"]}'}}
            ]
        }
    )
    result = client.chat_structured("system", "user", AnalysisSchema)
    assert result["score"] == 90
    bodies = [json.loads(r.read()) for r in httpx_mock.get_requests()]
    assert bodies[0]["max_tokens"] == 16384
    assert bodies[1]["max_tokens"] == 32768
    assert bodies[0]["thinking"] == {"type": "disabled"}
def test_structured_json_mode_corrects_schema_with_feedback(httpx_mock, client):
    """Bug-01: schema validation failure retries once with error feedback."""
    from resualign.schema_registry import AnalysisSchema

    httpx_mock.add_response(
        json={
            "choices": [
                {
                    "message": {
                        "content": '{"score": "high", "skills": "Python"}'
                    }
                }
            ]
        }
    )
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 90, "skills": ["Go"]}'}}
            ]
        }
    )
    result = client.chat_structured("system", "user", AnalysisSchema)
    assert result["score"] == 90
    bodies = [json.loads(r.read()) for r in httpx_mock.get_requests()]
    assert len(bodies) == 2
    assert "Schema validation failed" in bodies[1]["messages"][1]["content"]
    assert "user" in bodies[1]["messages"][1]["content"]
