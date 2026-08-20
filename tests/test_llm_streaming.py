"""Phase 3: SSE streaming + 15s zero-token circuit breaker."""

from __future__ import annotations

import json
import time

import httpx
import pytest

from resualign.llm import OpenAIClient, StreamConnectionError
from resualign.llm_nodes import LLMNodeStore
from resualign.models import ResuAlignConfig
from resualign.role_router import call_with_role_streaming


class _ChunkStream(httpx.SyncByteStream):
    """A byte stream that yields chunks lazily so timing can be simulated."""

    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def __iter__(self):
        for chunk in self._chunks:
            yield chunk

    def close(self):
        pass


def _delta_line(content: str | None) -> bytes:
    """Build a single SSE ``data:`` line carrying a delta content chunk."""
    payload = {"choices": [{"delta": {"content": content}}]}
    return f"data: {json.dumps(payload)}\n\n".encode()


def _stream_client(handler: httpx.MockTransport) -> OpenAIClient:
    config = ResuAlignConfig(
        provider="openai",
        api_key="sk-test",
        model="m1",
        base_url="https://api.openai.com/v1",
    )
    client = OpenAIClient(config)
    client._client = httpx.Client(transport=handler)
    return client


def test_stream_chat_json_accumulates_chunks():
    """Deltas accumulate into one JSON document and return the parsed dict."""
    captured: list[bytes] = []

    def handler(request):
        captured.append(request.read())
        body = (
            _delta_line('{"score": 8')
            + _delta_line('5, "skills": ["Py')
            + _delta_line('thon"]}')
            + b"data: [DONE]\n\n"
        )
        return httpx.Response(200, stream=_ChunkStream([body]))

    client = _stream_client(httpx.MockTransport(handler))
    result = client.stream_chat_json("system", "user")
    assert result == {"score": 85, "skills": ["Python"]}
    assert json.loads(captured[0])["stream"] is True


def test_stream_chat_json_raises_on_idle_timeout():
    """No new token within idle_timeout raises StreamConnectionError."""
    idle_timeout = 0.05

    def chunks():
        yield _delta_line('{"score": 8')
        time.sleep(0.2)
        yield _delta_line(None)

    def handler(request):
        return httpx.Response(200, stream=_ChunkStream(chunks()))

    client = _stream_client(httpx.MockTransport(handler))
    with pytest.raises(StreamConnectionError):
        client.stream_chat_json("system", "user", idle_timeout=idle_timeout)


def test_stream_transport_error_becomes_stream_connection_error():
    """Provider transport failures degrade to StreamConnectionError."""

    def handler(request):
        raise httpx.ConnectTimeout("provider unreachable", request=request)

    client = _stream_client(httpx.MockTransport(handler))
    with pytest.raises(StreamConnectionError, match="transport"):
        client.stream_chat_json("system", "user")


def test_no_token_heartbeats_trigger_breaker():
    """Heartbeat deltas without tokens still trip the idle breaker."""
    idle_timeout = 0.05

    def chunks():
        yield _delta_line(None)
        time.sleep(0.2)
        yield _delta_line(None)

    def handler(request):
        return httpx.Response(200, stream=_ChunkStream(chunks()))

    client = _stream_client(httpx.MockTransport(handler))
    with pytest.raises(StreamConnectionError):
        client.stream_chat_json("system", "user", idle_timeout=idle_timeout)


def test_call_with_role_streaming_falls_back_to_default(tmp_path):
    """A StreamConnectionError on the primary node falls back to default."""
    store = LLMNodeStore(db_path=str(tmp_path / "nodes.db"))
    tenant = "t1"
    store.create_node(
        tenant,
        name="Default",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-default",
        model="default-model",
        is_active=True,
    )
    primary = store.create_node(
        tenant,
        name="Primary",
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key="sk-primary",
        model="primary-model",
    )
    store.set_role_binding(tenant, "editor", primary["node_id"])

    def flaky(client, **kwargs):
        if client.model == "primary-model":
            raise StreamConnectionError("stalled stream")
        return {"from": client.model}

    result, meta = call_with_role_streaming(
        "editor", flaky, store, tenant, idle_timeout=0.05
    )
    assert result == {"from": "default-model"}
    assert meta["role"] == "editor"
    assert meta["model"] == "primary-model"
    assert meta["fallback_used"] is True
    assert meta["fallback_node_name"] == "Default"
    assert "stalled stream" in meta["error"]
