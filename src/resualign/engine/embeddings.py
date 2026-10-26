"""Embedding providers for resume x job ranking (ADR-0065).

Local-first: Ollama bge-m3 is the default; an OpenAI-compatible /embeddings
endpoint is available only when the user explicitly configures one, and the
hashing embedder exists for offline tests/CI (never as quality evidence).
Zero new dependencies: httpx is already a production dependency.

Failure policy (ADR-0065 decision 5): every failure surfaces as EmbeddingError
with a machine code; callers degrade to the keyword/match_score path instead of
failing the request. The gate stays fail-closed; ranking does not.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any, Protocol, Sequence

import httpx

HASH_DIM = 256
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "bge-m3"
DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
DEFAULT_BATCH = 16
DEFAULT_TIMEOUT = 60.0

_ASCII = re.compile(r"[a-z0-9+#.\-]+")
_CJK = re.compile(r"[\u4e00-\u9fff]+")


class EmbeddingError(Exception):
    """Embedding failure with a stable machine code for logs and degradation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.code + ": " + self.message


class Embedder(Protocol):
    name: str
    model: str
    dim: int
    is_real: bool

    @property
    def storage_model(self) -> str: ...

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


def _l2(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm <= 0.0:
        raise EmbeddingError("empty", "zero-length embedding")
    return [float(value) / norm for value in vector]


def _tokens(text: str) -> list[str]:
    flat = " ".join((text or "").lower().split())
    tokens = _ASCII.findall(flat)
    for run in _CJK.findall(flat):
        tokens.extend(run[i : i + 2] for i in range(max(1, len(run) - 1)))
    return tokens


class HashingEmbedder:
    """Deterministic char-ngram hashing; offline tests and CI only."""

    name = "hashing"
    is_real = False

    def __init__(self, dim: int = HASH_DIM) -> None:
        self.model = "ngram-" + str(dim)
        self.dim = dim

    @property
    def storage_model(self) -> str:
        return "hashing:" + self.model

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        counts = [0.0] * self.dim
        for token in _tokens(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            counts[int.from_bytes(digest, "big") % self.dim] += 1.0
        return _l2(counts)


class HttpEmbedder:
    """Shared batching/error mapping for HTTP embedding endpoints."""

    name = "http"
    is_real = True
    max_chars = 6000

    def __init__(
        self,
        model: str,
        batch: int = DEFAULT_BATCH,
        timeout: float = DEFAULT_TIMEOUT,
        client_factory: Any = None,
    ) -> None:
        self.model = model
        self.batch = max(1, batch)
        self.timeout = timeout
        self.dim = 0
        self.truncated = 0
        self.split = 0
        self.requests = 0
        self._client_factory = client_factory or (lambda: httpx.Client(timeout=timeout))

    @property
    def storage_model(self) -> str:
        return self.name + ":" + self.model

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch):
            vectors.extend(self._embed_chunk(list(texts[start : start + self.batch])))
        return vectors

    def _embed_chunk(self, chunk: list[str]) -> list[list[float]]:
        if not chunk:
            return []
        clean = [text if text.strip() else "" for text in chunk]
        if any(not text for text in clean):
            raise EmbeddingError("empty", "empty text cannot be embedded")
        try:
            return self._post(clean)
        except _ContextOverflow:
            if self.name != "ollama":
                raise EmbeddingError("http", "input exceeds context length")
            if len(chunk) == 1:
                return [self._embed_single(clean[0])]
            middle = len(chunk) // 2
            return self._embed_chunk(chunk[:middle]) + self._embed_chunk(
                chunk[middle:]
            )

    def _embed_single(self, text: str, depth: int = 0) -> list[float]:
        """Halve-then-pool until the piece fits; then truncate; then give up."""
        try:
            return self._post([text])[0]
        except _ContextOverflow:
            if len(text) > 600 and depth < 6:
                self.split += 1
                middle = len(text) // 2
                left = self._embed_single(text[:middle], depth + 1)
                right = self._embed_single(text[middle:], depth + 1)
                weight = middle / max(1, len(text))
                pooled = [
                    left[i] * weight + right[i] * (1.0 - weight)
                    for i in range(len(left))
                ]
                return _l2(pooled)
            if len(text) > 10 and depth < 10:
                self.truncated += 1
                return self._embed_single(text[: len(text) // 2], depth + 1)
            raise

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.requests += 1
        try:
            with self._client_factory() as client:
                response = client.post(self._endpoint(), json=payload)
        except httpx.TimeoutException as exc:
            raise EmbeddingError("timeout", "embedding request timed out") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError("http", "embedding request failed") from exc
        if response.status_code >= 400:
            detail = response.text[:300]
            if "context length" in detail:
                raise _ContextOverflow(detail)
            raise EmbeddingError(
                "http", "status " + str(response.status_code) + ": " + detail
            )
        try:
            return response.json()
        except ValueError as exc:
            raise EmbeddingError("http", "invalid JSON from embedding endpoint") from exc

    def _endpoint(self) -> str:
        raise NotImplementedError

    def _post(self, chunk: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def _collect(self, vectors: list[list[float]], expected: int) -> list[list[float]]:
        if len(vectors) != expected:
            raise EmbeddingError(
                "http",
                "endpoint returned " + str(len(vectors)) + " vectors for "
                + str(expected) + " inputs",
            )
        out: list[list[float]] = []
        for vector in vectors:
            if not self.dim:
                self.dim = len(vector)
            elif len(vector) != self.dim:
                raise EmbeddingError(
                    "dim_mismatch",
                    "embedding dim drift: " + str(len(vector)) + " vs " + str(self.dim),
                )
            out.append(_l2(vector))
        return out


class _ContextOverflow(Exception):
    """Endpoint refused the batch/text because it exceeds the model context."""


class OllamaEmbedder(HttpEmbedder):
    name = "ollama"

    def __init__(
        self,
        model: str = DEFAULT_OLLAMA_MODEL,
        url: str = DEFAULT_OLLAMA_URL,
        batch: int = DEFAULT_BATCH,
        timeout: float = DEFAULT_TIMEOUT,
        client_factory: Any = None,
    ) -> None:
        super().__init__(model=model, batch=batch, timeout=timeout, client_factory=client_factory)
        self.url = url.rstrip("/")

    def _endpoint(self) -> str:
        return self.url + "/api/embed"

    def _post(self, chunk: list[str]) -> list[list[float]]:
        body = self._request({"model": self.model, "input": chunk})
        vectors = body.get("embeddings")
        if vectors is None and body.get("embedding"):
            vectors = [body["embedding"]]
        return self._collect([list(map(float, vector)) for vector in (vectors or [])], len(chunk))


class OpenAICompatEmbedder(HttpEmbedder):
    """Any OpenAI-compatible POST /embeddings endpoint the user configured."""

    name = "openai"

    def __init__(
        self,
        model: str = DEFAULT_OPENAI_MODEL,
        base_url: str = "",
        api_key: str = "",
        batch: int = DEFAULT_BATCH,
        timeout: float = DEFAULT_TIMEOUT,
        client_factory: Any = None,
    ) -> None:
        super().__init__(model=model, batch=batch, timeout=timeout, client_factory=client_factory)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _endpoint(self) -> str:
        if self.base_url.endswith("/embeddings"):
            return self.base_url
        return self.base_url + "/embeddings"

    def _post(self, chunk: list[str]) -> list[list[float]]:
        headers = {"Authorization": "Bearer " + self.api_key} if self.api_key else {}
        body = self._request_with_headers(
            {"model": self.model, "input": chunk}, headers
        )
        data = body.get("data") or []
        vectors = [list(map(float, item.get("embedding", []))) for item in data]
        return self._collect(vectors, len(chunk))

    def _request_with_headers(
        self, payload: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        self.requests += 1
        try:
            with self._client_factory() as client:
                response = client.post(self._endpoint(), json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise EmbeddingError("timeout", "embedding request timed out") from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError("http", "embedding request failed") from exc
        if response.status_code >= 400:
            raise EmbeddingError(
                "http", "status " + str(response.status_code) + ": " + response.text[:300]
            )
        try:
            return response.json()
        except ValueError as exc:
            raise EmbeddingError("http", "invalid JSON from embedding endpoint") from exc


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def build_embedder() -> Embedder:
    """Resolve the configured embedder; raises EmbeddingError when unusable."""
    provider = (_env("RESUALIGN_EMBED_PROVIDER", "auto") or "auto").lower()
    batch = int(_env("RESUALIGN_EMBED_BATCH", str(DEFAULT_BATCH)) or DEFAULT_BATCH)
    timeout = float(_env("RESUALIGN_EMBED_TIMEOUT", str(DEFAULT_TIMEOUT)) or DEFAULT_TIMEOUT)
    if provider == "hashing":
        return HashingEmbedder()
    if provider == "openai":
        base_url = _env("RESUALIGN_EMBED_URL")
        if not base_url:
            raise EmbeddingError("unavailable", "RESUALIGN_EMBED_URL is required for openai")
        return OpenAICompatEmbedder(
            model=_env("RESUALIGN_EMBED_MODEL", DEFAULT_OPENAI_MODEL),
            base_url=base_url,
            api_key=_env("RESUALIGN_EMBED_API_KEY"),
            batch=batch,
            timeout=timeout,
        )
    # auto / ollama
    return OllamaEmbedder(
        model=_env("RESUALIGN_EMBED_MODEL", DEFAULT_OLLAMA_MODEL),
        url=_env("RESUALIGN_EMBED_URL", DEFAULT_OLLAMA_URL),
        batch=batch,
        timeout=timeout,
    )


def probe_embedder(timeout: float = 5.0) -> dict[str, Any]:
    """One cheap round-trip so callers can report a degraded reason."""
    try:
        embedder = build_embedder()
        embedder.embed_many(["probe"])
        return {"ok": True, "provider": embedder.name, "model": embedder.model,
                "dim": embedder.dim, "error": None}
    except EmbeddingError as exc:
        return {"ok": False, "provider": None, "model": None, "dim": 0,
                "error": str(exc)}
    except Exception as exc:  # network/DNS/etc: degrade, never 5xx the caller
        return {"ok": False, "provider": None, "model": None, "dim": 0,
                "error": type(exc).__name__ + ": " + str(exc)[:200]}
