import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, ClassVar, Optional, Type

import httpx
from pydantic import BaseModel, ValidationError

from .observability import CallStats, log_event

STRUCTURED_MAX_EXTRA_RETRIES = 2
_logger = logging.getLogger(__name__)
# In-memory aggregation of LLM call outcomes for /api/ops/metrics. Kept at
# module level because OpenAIClient instances are short-lived (one per job).
_LLM_CALL_STATS = CallStats(window_size=200)
_DAILY_USAGE_RECORDER: Callable[[], None] | None = None
def register_daily_usage_recorder(
    recorder: Callable[[], None] | None,
) -> None:
    """Register a persistent per-call usage recorder (wired by the API)."""
    global _DAILY_USAGE_RECORDER
    _DAILY_USAGE_RECORDER = recorder
def llm_metrics_snapshot() -> dict[str, Any]:
    """Return aggregated LLM call metrics for /api/ops/metrics."""
    return _LLM_CALL_STATS.snapshot()
def _observe_llm_call(
    *,
    stage: str,
    provider: str,
    model: str,
    duration_ms: float,
    attempts: int,
    status: str,
    mode: Optional[str] = None,
) -> None:
    """Record one LLM call in memory and emit a structured ``llm.call`` event."""
    _LLM_CALL_STATS.record(duration_ms, status)
    if _DAILY_USAGE_RECORDER is not None:
        try:
            _DAILY_USAGE_RECORDER()
        except Exception:  # noqa: BLE001 - accounting must not break LLM calls
            _logger.warning("Daily LLM usage recorder failed", exc_info=True)
    extra: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "stage": stage,
        "attempts": attempts,
        "status": status,
    }
    if mode is not None:
        extra["mode"] = mode
    log_event(
        _logger,
        "llm.call",
        duration_ms=duration_ms,
        extra=extra,
    )
def _parse_json_object(content: str) -> dict[str, Any]:
    """Parse a provider JSON object without using raw_decode."""
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            value = json.loads(text[start : end + 1])
        else:
            raise
    if not isinstance(value, dict):
        raise LLMResponseError("Structured response is not a JSON object")
    return value
class LLMResponseError(Exception):
    """Raised when the LLM fails to return a parseable response."""
    pass
class LLMClient(ABC):
    """Abstract LLM client for dependency injection in engine.py."""
    max_retries: ClassVar[int] = STRUCTURED_MAX_EXTRA_RETRIES

    @abstractmethod
    def chat_json(self, system: str, user: str, model: Optional[str] = None) -> dict:
        """Send a chat request and return parsed JSON."""
        ...
    def chat_structured(
        self,
        system: str,
        user: str,
        schema_model: Type[BaseModel],
        model: Optional[str] = None,
    ) -> dict:
        """Return a dict validated against a Pydantic response schema.
        Providers that do not expose the provider-specific method in a
        subclass fall back to JSON mode plus bounded schema-validation retries.
        """
        last_error: Optional[Exception] = None
        for _ in range(self.max_retries + 1):
            try:
                result = self.chat_json(system, user, model=model)
                return schema_model.model_validate(result).model_dump()
            except ValidationError as exc:
                last_error = exc
                time.sleep(1)
        raise LLMResponseError(
            "Structured response failed schema validation after "
            f"{self.max_retries + 1} attempts: {last_error}"
        )
class OpenAIClient(LLMClient):
    """Concrete LLM client compatible with OpenAI / DeepSeek / Ollama APIs."""
    strict_provenance = True
    # Defaults that can be overridden per instance or per subclass
    DEFAULT_MAX_TOKENS: ClassVar[int] = 16384
    DEFAULT_MAX_RETRIES: ClassVar[int] = 2
    # Per-request read timeout. Tailoring is a high-throughput structured
    # task on standard instruction models (e.g. deepseek-chat). Sprint 5
    # tuned this down from 60s to 40s so a stuck provider bounds worst-case
    # hangs at 3 attempts x 40s = 120s instead of the old 3 x 60s = 180s.
    # Connect uses a short 10s window so unreachable hosts fail fast
    # rather than blocking the pool.
    DEFAULT_TIMEOUT: ClassVar[float] = 120.0
    DEFAULT_CONNECT_TIMEOUT: ClassVar[float] = 30.0
    DEFAULT_TEMPERATURE: ClassVar[float] = 0.1
    MAX_OUTPUT_TOKENS: ClassVar[int] = 65536
    def __init__(
        self,
        config,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
    ):
        self.api_key = config.api_key
        self.model = config.model
        self.base_url = (
            config.base_url
            or _DEFAULT_PROVIDER_URLS.get(config.provider, "https://api.openai.com/v1")
        )
        provider = str(getattr(config, "provider", "")).lower()
        self.supports_structured_outputs = (
            provider in {"openai", "azure"}
            or "api.openai.com" in self.base_url
        )
        self.provider = provider or "unknown"
        self.max_retries = (
            self.DEFAULT_MAX_RETRIES
            if max_retries is None
            else int(max_retries)
        )
        # DeepSeek reasoning models spend the output budget on
        # ``reasoning_content`` before emitting the final JSON, which can
        # cause 200 responses with empty ``content`` and finish_reason=length
        self.request_direct_output = provider == "deepseek" or (
            "deepseek.com" in self.base_url
        )
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                timeout if timeout is not None else self.DEFAULT_TIMEOUT,
                connect=self.DEFAULT_CONNECT_TIMEOUT,
            ),
            headers={"Content-Type": "application/json"},
        )
    def _provider_extras(self) -> dict[str, Any]:
        """Return provider-specific request fields for direct JSON output."""
        if self.request_direct_output:
            return {"thinking": {"type": "disabled"}}
        return {}
    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()
    def __enter__(self) -> "OpenAIClient":
        return self
    def __exit__(self, *args: object) -> None:
        self.close()
    def chat_json(self, system: str, user: str, model: Optional[str] = None) -> dict:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.DEFAULT_TEMPERATURE,
            **self._provider_extras(),
        }
        max_tokens = self.DEFAULT_MAX_TOKENS
        _t0 = time.monotonic()
        attempts = 0
        status = "failed"
        try:
            for attempt in range(self.max_retries + 1):
                attempts += 1
                try:
                    payload = {**body, "max_tokens": max_tokens}
                    if attempt == 0:
                        payload["response_format"] = {"type": "json_object"}
                    r = self._client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    r.raise_for_status()
                    response = r.json()
                    message = response["choices"][0]["message"]
                    content = message.get("content") or ""
                    finish_reason = response["choices"][0].get("finish_reason")
                    start = content.find("{")
                    if start < 0:
                        if attempt == self.max_retries:
                            raise LLMResponseError("No JSON object found in response")
                        if finish_reason == "length" and max_tokens < self.MAX_OUTPUT_TOKENS:
                            max_tokens = min(max_tokens * 2, self.MAX_OUTPUT_TOKENS)
                        time.sleep(1)
                        continue
                    try:
                        result = _parse_json_object(content)
                    except Exception:
                        if attempt == self.max_retries:
                            raise
                        if finish_reason == "length" and max_tokens < self.MAX_OUTPUT_TOKENS:
                            max_tokens = min(max_tokens * 2, self.MAX_OUTPUT_TOKENS)
                        time.sleep(1)
                        continue
                    status = "ok"
                    return result
                except LLMResponseError:
                    raise
                except Exception as e:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            f"LLM call failed after {self.max_retries + 1} attempts: {e}"
                        ) from e
                    time.sleep(1)
        finally:
            _observe_llm_call(
                stage="chat_json",
                provider=self.provider,
                model=model or self.model,
                duration_ms=(time.monotonic() - _t0) * 1000,
                attempts=attempts,
                status=status,
            )
    def chat_structured(
        self,
        system: str,
        user: str,
        schema_model: Type[BaseModel],
        model: Optional[str] = None,
    ) -> dict:
        if self.supports_structured_outputs:
            return self._chat_structured_provider(
                system, user, schema_model, model=model
            )
        return self._chat_structured_json_mode(
            system, user, schema_model, model=model
        )
    def _chat_structured_provider(
        self,
        system: str,
        user: str,
        schema_model: Type[BaseModel],
        model: Optional[str] = None,
    ) -> dict:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        schema = schema_model.model_json_schema()
        body = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.DEFAULT_TEMPERATURE,
            **self._provider_extras(),
            "max_tokens": self.DEFAULT_MAX_TOKENS,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_model.__name__,
                    "schema": schema,
                    "strict": True,
                },
            },
        }
        _t0 = time.monotonic()
        attempts = 0
        status = "failed"
        try:
            for attempt in range(self.max_retries + 1):
                attempts += 1
                try:
                    r = self._client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=body,
                    )
                    r.raise_for_status()
                    response = r.json()
                    message = response["choices"][0]["message"]
                    content = message.get("content") or ""
                    result = schema_model.model_validate(
                        _parse_json_object(content)
                    ).model_dump()
                    status = "ok"
                    return result
                except httpx.HTTPStatusError as exc:
                    if exc.response is not None and exc.response.status_code == 400:
                        return self._chat_structured_json_mode(
                            system, user, schema_model, model=model
                        )
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            "Structured LLM call failed after "
                            f"{self.max_retries + 1} attempts: {exc}"
                        ) from exc
                    time.sleep(1)
                except (ValidationError, json.JSONDecodeError, LLMResponseError) as exc:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            "Structured response failed validation after "
                            f"{self.max_retries + 1} attempts: {exc}"
                        ) from exc
                    time.sleep(1)
                except Exception as exc:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            "Structured LLM call failed after "
                            f"{self.max_retries + 1} attempts: {exc}"
                        ) from exc
                    time.sleep(1)
        finally:
            _observe_llm_call(
                stage="chat_structured",
                provider=self.provider,
                model=model or self.model,
                duration_ms=(time.monotonic() - _t0) * 1000,
                attempts=attempts,
                status=status,
                mode="json_schema",
            )
    def _chat_structured_json_mode(
        self,
        system: str,
        user: str,
        schema_model: Type[BaseModel],
        model: Optional[str] = None,
    ) -> dict:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.DEFAULT_TEMPERATURE,
            **self._provider_extras(),
            "response_format": {"type": "json_object"},
        }
        max_tokens = self.DEFAULT_MAX_TOKENS
        last_error: Optional[Exception] = None
        _t0 = time.monotonic()
        attempts = 0
        status = "failed"
        try:
            for attempt in range(self.max_retries + 1):
                attempts += 1
                try:
                    payload = {**body, "max_tokens": max_tokens}
                    r = self._client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                    r.raise_for_status()
                    response = r.json()
                    message = response["choices"][0]["message"]
                    content = message.get("content") or ""
                    finish_reason = response["choices"][0].get("finish_reason")
                    if (
                        not content
                        and finish_reason == "length"
                        and max_tokens < self.MAX_OUTPUT_TOKENS
                    ):
                        max_tokens = min(
                            max_tokens * 2, self.MAX_OUTPUT_TOKENS
                        )
                        if attempt < self.max_retries:
                            time.sleep(1)
                            continue
                        raise LLMResponseError(
                            "Structured response was empty after "
                            f"{self.max_retries + 1} attempts"
                        )
                    result = schema_model.model_validate(
                        _parse_json_object(content)
                    ).model_dump()
                    status = "ok"
                    return result
                except (ValidationError, json.JSONDecodeError, LLMResponseError) as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise LLMResponseError(
                            "Structured response failed schema validation after "
                            f"{self.max_retries + 1} attempts: {last_error}"
                        ) from exc
                    time.sleep(1)
                except Exception as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise LLMResponseError(
                            "Structured LLM call failed after "
                            f"{self.max_retries + 1} attempts: {last_error}"
                        ) from exc
                    time.sleep(1)
        finally:
            _observe_llm_call(
                stage="chat_structured",
                provider=self.provider,
                model=model or self.model,
                duration_ms=(time.monotonic() - _t0) * 1000,
                attempts=attempts,
                status=status,
                mode="json_object",
            )
DIAG_PROMPT = (
    "You are a resume auditor. Return JSON with score (0-100), issues (list of strings), "
    "and skills (list of strings). Output ONLY JSON.\\n"
    "## Output Constraints\\n"
    "- Max tokens: 500\\n"
    "- Temperature: 0.0\\n"
    "- If uncertain: return empty list instead of guessing\\n"
    "- Output ONLY valid JSON, no markdown fences\\n"
)
DIAG_PROMPT_VERSION = "v2"
_DEFAULT_PROVIDER_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}
def _structured_or_json(
    client: LLMClient,
    system: str,
    user: str,
    schema_model: Type[BaseModel],
    model: Optional[str] = None,
) -> dict:
    """Use chat_structured when available; otherwise preserve chat_json callers."""
    structured = getattr(client, "chat_structured", None)
    if callable(structured):
        return structured(system, user, schema_model, model=model)
    return client.chat_json(system, user, model=model)
def diagnose_resume(
    client: LLMClient,
    resume_text: str,
    cache=None,
    tenant: str = "default",
    model: Optional[str] = None,
) -> dict:
    """Run diagnosis through an optional content-hash cache."""
    from .schema_registry import AnalysisSchema
    resolved_model = model or getattr(client, "model", "default")
    if cache is not None:
        cached = cache.get(
            tenant,
            resolved_model,
            DIAG_PROMPT_VERSION,
            resume_text,
        )
        if cached is not None:
            return cached
    result = _structured_or_json(
        client,
        DIAG_PROMPT,
        resume_text,
        AnalysisSchema,
        model=resolved_model,
    )
    if cache is not None:
        cache.put(
            tenant,
            resolved_model,
            DIAG_PROMPT_VERSION,
            resume_text,
            result,
        )
    return result
# ---------------------------------------------------------------------------
# LLM client abstractions
# ---------------------------------------------------------------------------
