"""ADR-0065: embedding providers - batching, overflow handling, error codes."""

from __future__ import annotations

import json

import httpx
import pytest

from resualign.engine.embeddings import (
    EmbeddingError,
    HashingEmbedder,
    OllamaEmbedder,
    OpenAICompatEmbedder,
    build_embedder,
    probe_embedder,
)


def _factory(handler):
    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return factory


def _ollama_ok(vectors):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        rows = vectors if callable(vectors) else [vectors for _ in payload["input"]]
        return httpx.Response(200, json={"embeddings": rows})

    return handler


def test_hashing_is_deterministic_normalized_and_nonzero():
    embedder = HashingEmbedder()
    first = embedder.embed_many(["java backend high concurrency"])
    second = embedder.embed_many(["java backend high concurrency"])
    assert first == second
    assert embedder.dim == 256
    assert abs(sum(value * value for value in first[0]) - 1.0) < 1e-9
    assert embedder.storage_model.startswith("hashing:")


def test_hashing_empty_text_raises_empty_code():
    with pytest.raises(EmbeddingError) as err:
        HashingEmbedder().embed_many(["   "])
    assert err.value.code == "empty"


def test_build_embedder_defaults_to_local_ollama(monkeypatch):
    for name in (
        "RESUALIGN_EMBED_PROVIDER",
        "RESUALIGN_EMBED_MODEL",
        "RESUALIGN_EMBED_URL",
        "RESUALIGN_EMBED_BATCH",
    ):
        monkeypatch.delenv(name, raising=False)
    embedder = build_embedder()
    assert embedder.name == "ollama"
    assert embedder.model == "bge-m3"
    assert embedder.storage_model == "ollama:bge-m3"
    assert embedder.batch == 16


def test_build_embedder_env_overrides(monkeypatch):
    monkeypatch.setenv("RESUALIGN_EMBED_PROVIDER", "hashing")
    assert build_embedder().name == "hashing"

    monkeypatch.setenv("RESUALIGN_EMBED_PROVIDER", "openai")
    monkeypatch.setenv("RESUALIGN_EMBED_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("RESUALIGN_EMBED_API_KEY", "x")
    monkeypatch.setenv("RESUALIGN_EMBED_MODEL", "bge-m3")
    monkeypatch.setenv("RESUALIGN_EMBED_BATCH", "4")
    embedder = build_embedder()
    assert embedder.name == "openai"
    assert embedder.base_url == "http://127.0.0.1:9999/v1"
    assert embedder.batch == 4


def test_openai_provider_requires_url(monkeypatch):
    monkeypatch.setenv("RESUALIGN_EMBED_PROVIDER", "openai")
    monkeypatch.delenv("RESUALIGN_EMBED_URL", raising=False)
    with pytest.raises(EmbeddingError) as err:
        build_embedder()
    assert err.value.code == "unavailable"


def test_ollama_batches_and_reports_dim():
    embedder = OllamaEmbedder(batch=2, client_factory=_factory(_ollama_ok([1.0, 0.0])))
    vectors = embedder.embed_many(["a", "b", "c"])
    assert len(vectors) == 3
    assert embedder.dim == 2
    assert embedder.requests == 2
    assert all(abs(sum(v * v for v in vector) - 1.0) < 1e-9 for vector in vectors)


def test_ollama_context_overflow_splits_then_pools():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        texts = payload["input"]
        if len(texts) > 1 or len(texts[0]) > 20:
            return httpx.Response(
                400, text='{"error":"the input length exceeds the context length"}'
            )
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0]]})

    embedder = OllamaEmbedder(batch=4, client_factory=_factory(handler))
    vectors = embedder.embed_many(["x" * 2400, "short"])
    assert len(vectors) == 2
    assert embedder.split >= 1  # >600 chars is halved before any truncation
    assert embedder.truncated >= 1  # the remaining pieces still overflowed


def test_ollama_dim_drift_raises_dim_mismatch():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.read())
        rows = [[1.0, 2.0] if index == 0 else [1.0, 2.0, 3.0]
                for index, _text in enumerate(payload["input"])]
        return httpx.Response(200, json={"embeddings": rows})

    embedder = OllamaEmbedder(batch=2, client_factory=_factory(handler))
    with pytest.raises(EmbeddingError) as err:
        embedder.embed_many(["a", "b"])
    assert err.value.code == "dim_mismatch"


def test_ollama_timeout_maps_to_timeout_code():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    embedder = OllamaEmbedder(batch=1, client_factory=_factory(handler))
    with pytest.raises(EmbeddingError) as err:
        embedder.embed_many(["a"])
    assert err.value.code == "timeout"


def test_openai_compat_sends_bearer_and_parses_data():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization", "")
        payload = json.loads(request.read())
        return httpx.Response(
            200,
            json={"data": [{"embedding": [3.0, 4.0]} for _ in payload["input"]]},
        )

    embedder = OpenAICompatEmbedder(
        model="emb", base_url="http://x/v1", api_key="k", client_factory=_factory(handler)
    )
    vector = embedder.embed_many(["hello"])[0]
    assert seen["url"] == "http://x/v1/embeddings"
    assert seen["auth"] == "Bearer k"
    assert abs(vector[0] - 0.6) < 1e-9 and abs(vector[1] - 0.8) < 1e-9


def test_openai_compat_http_error_maps_to_http_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad model")

    embedder = OpenAICompatEmbedder(
        model="emb", base_url="http://x/v1", client_factory=_factory(handler)
    )
    with pytest.raises(EmbeddingError) as err:
        embedder.embed_many(["hello"])
    assert err.value.code == "http"


def test_probe_embedder_reports_ok_for_hashing(monkeypatch):
    monkeypatch.setenv("RESUALIGN_EMBED_PROVIDER", "hashing")
    result = probe_embedder()
    assert result["ok"] is True
    assert result["provider"] == "hashing"
    assert result["dim"] == 256
