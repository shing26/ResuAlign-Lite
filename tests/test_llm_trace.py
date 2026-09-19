"""Archive layer: raw LLM request/response traces (hardening 2026-09-19).

The archive is a deliberate exception to "logs only carry metadata": when a
run is disputed ("the model ignored my JD"), the only way to replay it is to
have the exact request and response bodies. These tests pin the contract:
off by default, redacted on write, never fatal, and rotated like ``app.log``.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from resualign.archive import llm_trace
from resualign.archive.llm_trace import record_llm_trace, trace_enabled
from resualign.llm import LLMResponseError, OpenAIClient, _observe_llm_call
from resualign.models import ResuAlignConfig

from .conftest import fake_api_key


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    """Point the archive at a per-test directory and close its handler after."""
    monkeypatch.setenv("RESUALIGN_LOG_DIR", str(tmp_path))
    yield tmp_path
    handler = llm_trace._handler
    if handler is not None:
        llm_trace._logger.removeHandler(handler)
        handler.close()
    llm_trace._handler = None
    llm_trace._handler_dir = None


def _read_traces(directory: Path) -> list[dict]:
    path = directory / llm_trace.TRACE_FILENAME
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text("utf-8").splitlines()
        if line.strip()
    ]


def test_trace_is_off_by_default(trace_dir, monkeypatch):
    monkeypatch.delenv(llm_trace.TRACE_ENV, raising=False)
    assert trace_enabled() is False

    record_llm_trace({"stage": "chat_json", "request": {"a": 1}})
    _observe_llm_call(
        stage="chat_json",
        provider="openai",
        model="m1",
        duration_ms=1.0,
        attempts=1,
        status="ok",
        trace_request={"a": 1},
        trace_response={"b": 2},
    )

    assert _read_traces(trace_dir) == []
    assert not (trace_dir / llm_trace.TRACE_FILENAME).exists()


def test_trace_records_full_exchange_when_enabled(trace_dir, monkeypatch):
    monkeypatch.setenv(llm_trace.TRACE_ENV, "1")
    assert trace_enabled() is True

    _observe_llm_call(
        stage="chat_structured",
        provider="deepseek",
        model="m1",
        duration_ms=12.34,
        attempts=2,
        status="ok",
        mode="json_schema",
        usage={"prompt_tokens": 10, "completion_tokens": 20},
        trace_request={
            "model": "m1",
            "messages": [{"role": "user", "content": "hello jd"}],
        },
        trace_response={"choices": [{"message": {"content": "{}"}}]},
    )

    rows = _read_traces(trace_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["stage"] == "chat_structured"
    assert row["mode"] == "json_schema"
    assert row["attempts"] == 2
    assert row["request"]["messages"][0]["content"] == "hello jd"
    assert row["response"] == {"choices": [{"message": {"content": "{}"}}]}
    assert row["ts"]


def test_trace_redacts_secrets_and_truncates_errors(trace_dir, monkeypatch):
    monkeypatch.setenv(llm_trace.TRACE_ENV, "true")
    secret = "sk" + "-" + "trace" + "0123456789"

    record_llm_trace(
        {
            "stage": "chat_json",
            "request": {"note": f"key={secret}"},
            "response": {"error": "e" * 900},
        }
    )

    rows = _read_traces(trace_dir)
    assert len(rows) == 1
    dumped = json.dumps(rows[0], ensure_ascii=False)
    assert secret not in dumped
    assert "sk-***" in dumped
    assert rows[0]["response"]["error"].endswith("[truncated]")
    assert len(rows[0]["response"]["error"]) < 900


def test_trace_has_no_record_when_both_bodies_missing(trace_dir, monkeypatch):
    """A call with nothing to archive must not create an empty file."""
    monkeypatch.setenv(llm_trace.TRACE_ENV, "1")
    _observe_llm_call(
        stage="chat_json",
        provider="openai",
        model="m1",
        duration_ms=1.0,
        attempts=1,
        status="ok",
    )
    assert _read_traces(trace_dir) == []


def test_trace_handler_mirrors_app_log_rotation(trace_dir, monkeypatch):
    monkeypatch.setenv(llm_trace.TRACE_ENV, "1")
    record_llm_trace({"stage": "chat_json"})

    handler = llm_trace._get_handler()
    assert handler.maxBytes == 10 * 1024 * 1024
    assert handler.backupCount == 5
    assert Path(handler.baseFilename) == trace_dir / llm_trace.TRACE_FILENAME
    assert handler.formatter._fmt == "%(message)s"  # noqa: SLF001


def test_chat_json_traces_request_and_response(trace_dir, monkeypatch, httpx_mock):
    monkeypatch.setenv(llm_trace.TRACE_ENV, "1")
    httpx_mock.add_response(
        json={
            "choices": [
                {"message": {"content": '{"score": 85}'}}
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }
    )
    client = OpenAIClient(
        ResuAlignConfig(api_key=fake_api_key("trace"), model="m1")
    )
    client.chat_json("system prompt", "user jd text")

    rows = _read_traces(trace_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["stage"] == "chat_json"
    assert row["request"]["messages"][0]["content"] == "system prompt"
    assert row["request"]["messages"][1]["content"] == "user jd text"
    # The response is archived as the provider's raw JSON text, not a
    # re-serialised dict, so a disputed run can be replayed byte-for-byte.
    response_body = json.loads(row["response"])
    assert response_body["usage"]["prompt_tokens"] == 3
    assert "score" in response_body["choices"][0]["message"]["content"]
    # Request bodies never carry the Authorization header, so no key can leak
    # through this path even before redaction runs.
    assert "Authorization" not in json.dumps(row["request"])


def test_chat_json_skips_trace_when_disabled(trace_dir, monkeypatch, httpx_mock):
    monkeypatch.delenv(llm_trace.TRACE_ENV, raising=False)
    httpx_mock.add_response(
        json={"choices": [{"message": {"content": '{"score": 1}'}}]}
    )
    client = OpenAIClient(
        ResuAlignConfig(api_key=fake_api_key("trace"), model="m1")
    )
    client.chat_json("system", "user")

    assert _read_traces(trace_dir) == []
    assert client._trace_request_body is None
    assert client._trace_response_text is None


def test_trace_keeps_request_when_transport_fails(
    trace_dir, monkeypatch, httpx_mock
):
    """A timeout is exactly the dispute worth replaying.

    No response ever arrives on this path, so the request must be captured
    *before* the POST — otherwise the archive records nothing for the very
    failures operators ask about.
    """
    monkeypatch.setenv(llm_trace.TRACE_ENV, "1")
    httpx_mock.add_exception(httpx.ConnectTimeout("connect timeout"))
    client = OpenAIClient(
        ResuAlignConfig(api_key=fake_api_key("trace"), model="m1")
    )
    client.max_retries = 0

    with pytest.raises(LLMResponseError) as excinfo:
        client.chat_json("system prompt", "user jd text")
    assert excinfo.value.code == "timeout"

    rows = _read_traces(trace_dir)
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "failed"
    assert row["request"]["messages"][0]["content"] == "system prompt"
    assert row["request"]["messages"][1]["content"] == "user jd text"
    assert row["response"] is None
