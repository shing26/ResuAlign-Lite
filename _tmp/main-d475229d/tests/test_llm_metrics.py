"""LLM call metrics: structured llm.call log events plus in-memory stats."""

import json
import logging

import pytest
from pydantic import BaseModel

import resualign.llm as llm_module
from resualign.llm import LLMResponseError, OpenAIClient
from resualign.models import ResuAlignConfig


class _ScoreModel(BaseModel):
    score: int


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def captured():
    logger = logging.getLogger("resualign.llm")
    saved_handlers = list(logger.handlers)
    saved_propagate = logger.propagate
    saved_level = logger.level
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _CaptureHandler()
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    logger.handlers[:] = saved_handlers
    logger.propagate = saved_propagate
    logger.setLevel(saved_level)


@pytest.fixture
def config():
    return ResuAlignConfig(provider="deepseek", api_key="sk-test", model="m1")


@pytest.fixture(autouse=True)
def baseline_snapshot():
    return llm_module.llm_metrics_snapshot()


def _records(handler):
    return [json.loads(record.getMessage()) for record in handler.records]


def test_chat_json_records_ok_call(httpx_mock, config, captured, baseline_snapshot):
    client = OpenAIClient(config)
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"score": 85}'}}]}
    )
    result = client.chat_json("system", "user")
    assert result["score"] == 85

    events = _records(captured)
    assert len(events) == 1
    assert events[0]["event"] == "llm.call"
    assert events[0]["duration_ms"] >= 0
    assert events[0]["extra"] == {
        "provider": "deepseek",
        "model": "m1",
        "stage": "chat_json",
        "attempts": 1,
        "status": "ok",
    }

    after = llm_module.llm_metrics_snapshot()
    assert after["total"] == baseline_snapshot["total"] + 1
    assert after["successes"] == baseline_snapshot["successes"] + 1
    assert after["duration"]["count"] == baseline_snapshot["duration"]["count"] + 1


def test_chat_json_records_failed_call_with_attempts(
    httpx_mock, config, captured, baseline_snapshot
):
    client = OpenAIClient(config)
    client.max_retries = 1
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(status_code=500)

    with pytest.raises(LLMResponseError):
        client.chat_json("system", "user")

    events = _records(captured)
    assert len(events) == 1
    assert events[0]["event"] == "llm.call"
    assert events[0]["extra"]["status"] == "failed"
    assert events[0]["extra"]["attempts"] == 2

    after = llm_module.llm_metrics_snapshot()
    assert after["failures"] == baseline_snapshot["failures"] + 1
    assert after["success_rate"] is not None


def test_chat_structured_json_mode_records_call(
    httpx_mock, config, captured, baseline_snapshot
):
    client = OpenAIClient(config)  # deepseek -> json-mode structured path
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"score": 7}'}}]}
    )
    result = client.chat_structured("system", "user", _ScoreModel)
    assert result == {"score": 7}

    events = _records(captured)
    assert len(events) == 1
    assert events[0]["extra"]["stage"] == "chat_structured"
    assert events[0]["extra"]["mode"] == "json_object"
    assert events[0]["extra"]["status"] == "ok"
    assert events[0]["extra"]["attempts"] == 1


def test_chat_structured_provider_mode_records_call(httpx_mock, captured):
    config = ResuAlignConfig(provider="openai", api_key="sk-test", model="gpt-4o")
    client = OpenAIClient(config)
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"score": 9}'}}]}
    )
    result = client.chat_structured("system", "user", _ScoreModel)
    assert result == {"score": 9}

    events = _records(captured)
    assert len(events) == 1
    assert events[0]["extra"]["provider"] == "openai"
    assert events[0]["extra"]["stage"] == "chat_structured"
    assert events[0]["extra"]["mode"] == "json_schema"
    assert events[0]["extra"]["status"] == "ok"
