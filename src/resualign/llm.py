import json
import logging
import re
import threading
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
def _strip_json_wrapping(text: str) -> str:
    """Strip BOM, markdown code fences, and surrounding whitespace."""
    text = (text or "").strip()
    if not text:
        return ""
    if text.startswith("\ufeff"):
        text = text[1:].lstrip()
    # Small/vendor models sometimes wrap JSON in a ```json fence with prose.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text).strip()
    return text


def _extract_balanced_json(text: str) -> str:
    """Return the first balanced ``{...}`` object, ignoring braces inside strings.

    When the object is truncated (never balanced), returns from the first ``{``
    to the end so a later best-effort repair can close the brackets.
    """
    start = text.find("{")
    if start < 0:
        raise LLMResponseError("No JSON object found in LLM response")
    depth = 0
    in_str = False
    esc = False
    balanced_end = -1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    balanced_end = i + 1
        i += 1
    if balanced_end > start:
        return text[start:balanced_end]
    return text[start:]


def _repair_json(candidate: str) -> str | None:
    """Best-effort repair of truncated JSON: close braces and drop trailing commas."""
    candidate = (candidate or "").strip()
    if not candidate:
        return None
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    stack: list[str] = []
    in_str = False
    esc = False
    matching = {"}": "{", "]": "["}
    closers = {"{": "}", "[": "]"}
    for ch in candidate:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack and stack[-1] == matching[ch]:
            stack.pop()
    if stack:
        candidate += "".join(closers[o] for o in reversed(stack))
    return candidate


def _parse_json_object(content: str) -> dict[str, Any]:
    """Parse a provider JSON object with tolerance for real-world model noise.

    Tries, in order: strict parse, balanced ``{...}`` extraction, then a
    best-effort repair of truncation (unclosed braces, trailing commas). Only
    when all three fail does it raise ``LLMResponseError``.
    """
    text = _strip_json_wrapping(content)
    if not text:
        raise LLMResponseError("Empty LLM response")

    candidates: list[str] = [text]
    try:
        candidates.append(_extract_balanced_json(text))
    except LLMResponseError:
        pass
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
        repaired = _repair_json(candidate)
        if repaired is not None and repaired != candidate:
            try:
                value = json.loads(repaired)
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                pass
    raise LLMResponseError(
        f"Unable to parse LLM JSON response: {text[:120]!r}"
    )


def _schema_feedback_prompt(user: str, exc: BaseException) -> str:
    """Append pydantic validation errors for a single corrective retry.

    Instead of blindly retrying an identical prompt on schema validation
    failure, feed the validation errors back once so the model can repair
    the structure (Bug-01 one-shot corrective retry).
    """
    return (
        f"{user}\n"
        "\n"
        "## Schema validation failed\n"
        "Your previous JSON did not match the required output structure. "
        "Reproduce the same content with the structure fixed, and output "
        "ONLY valid JSON matching the schema.\n"
        f"Validation errors: {exc}"
    )


# R4 P0-1（03-AIE §②/§③-P0-1）：结构化失败分类。LLMResponseError 携带
# 稳定 code 枚举，_job_failure_detail 按 code 分支，杜绝 message substring 漂移
# 导致的误归因（166.2s 现场失败文案曾落入「检查 API Key 与网络」else 分支）。
_KNOWN_CODES = {
    "timeout",
    "empty",
    "parse",
    "schema",
    "quota",
    "rate_limit",
    "auth",
    "http",
    "other",
}


class LLMResponseError(Exception):
    """Raised when the LLM fails to return a parseable response.

    ``code`` is a stable failure category (see ``_KNOWN_CODES``); callers that
    surface user-facing copy branch on it instead of parsing the message text.
    """

    def __init__(self, message: str, code: str = "other"):
        super().__init__(message)
        self.code = code if code in _KNOWN_CODES else "other"


class StreamConnectionError(Exception):
    """Raised when an SSE stream stalls without producing a new token."""

    pass


def _raise_network_timeout(kind: str, attempt: int, exc: BaseException) -> None:
    """Map a transport-level network failure to the API's LLM error."""
    raise LLMResponseError(
        f"{kind} call failed after {attempt + 1} attempt(s) "
        f"(network timeout): {exc}",
        code="timeout",
    ) from exc


def _http_error_code(exc: BaseException) -> str:
    """Classify an HTTP status code into a stable LLMResponseError code.

    P0-1 G2：402 欠费 / 401·403 鉴权 / 429 限流不再落入「检查 API Key」else 分支。
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 402:
        return "quota"
    if status in (401, 403):
        return "auth"
    if status == 429 or "rate limit" in str(exc).lower():
        return "rate_limit"
    return "http"


class _WallClockDeadlineExceeded(httpx.ReadTimeout):
    """Raised when a single POST exceeds its wall-clock deadline.

    Subclasses ``httpx.ReadTimeout`` so existing ``TransportError`` handlers
    keep working; ``deadline_exceeded`` marks P0-3 deadlines, which must
    NEVER be transport-retried (retrying a genuinely slow generation only
    multiplies the wait, and the client was closed on deadline).
    """

    def __init__(self, deadline_s: float):
        super().__init__(f"wall-clock deadline exceeded ({deadline_s:.1f}s)")
        self.deadline_exceeded = True
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
        for attempt in range(self.max_retries + 1):
            user_prompt = (
                _schema_feedback_prompt(user, last_error)
                if attempt > 0 and last_error is not None
                else user
            )
            try:
                result = self.chat_json(system, user_prompt, model=model)
                return schema_model.model_validate(result).model_dump()
            except ValidationError as exc:
                last_error = exc
                time.sleep(1)
        raise LLMResponseError(
            "Structured response failed schema validation after "
            f"{self.max_retries + 1} attempts: {last_error}",
            code="schema",
        )
class OpenAIClient(LLMClient):
    """Concrete LLM client compatible with OpenAI / DeepSeek / Ollama APIs."""
    strict_provenance = True
    # Defaults that can be overridden per instance or per subclass
    DEFAULT_MAX_TOKENS: ClassVar[int] = 16384
    DEFAULT_MAX_RETRIES: ClassVar[int] = 1
    # Per-request read timeout. A stuck provider is bounded by the
    # role-appropriate timeout (role_router) times two attempts.
    # Transport errors (timeouts / connection loss) are NOT retried: a
    # timeout on a large prompt rarely succeeds on retry, and retrying only
    # multiplies the wait. The retry budget is kept for resumable failures
    # (HTTP 5xx, schema validation, finish_reason=length). Connect uses a
    # short window so unreachable hosts fail fast rather than blocking.
    DEFAULT_TIMEOUT: ClassVar[float] = 120.0
    DEFAULT_CONNECT_TIMEOUT: ClassVar[float] = 30.0
    DEFAULT_TEMPERATURE: ClassVar[float] = 0.1
    MAX_OUTPUT_TOKENS: ClassVar[int] = 65536
    def __init__(
        self,
        config,
        timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        max_tokens: Optional[int] = None,
        token_cap: Optional[int] = None,
        deadline: Optional[float] = None,
        retry_transport: Optional[bool] = None,
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
        # R4 P0-2：per-role max_tokens 钳制。实例级起始上限；length 翻倍只允许
        # 1 次且受 ``_token_cap`` 约束（默认保留 65536 兜底，角色路径由 role_router
        # 传入收缩后的 cap——诊断 1024 / profiler·gap 2048 / editor 6144 / eval 768）。
        self.max_tokens = (
            self.DEFAULT_MAX_TOKENS
            if max_tokens is None
            else int(max_tokens)
        )
        self._token_cap = (
            self.MAX_OUTPUT_TOKENS
            if token_cap is None
            else int(token_cap)
        )
        # R4 P0-3：墙钟 deadline（秒）。None = 不启用（保持旧直连语义）；
        # 角色路径由 role_router 显式传入（= 角色超时），单次 POST 超时即中断。
        self._deadline_s = float(deadline) if deadline is not None else None
        # R4 P0-4：短角色条件性 transport 重试（classifier/intake/profiler/gap/polish）。
        # 长生成角色（editor/tailor）恒 False：超时重试只会再等一个世纪。
        self._retry_transport = bool(retry_transport) if retry_transport is not None else False
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
    def _post_with_deadline(
        self, url: str, headers: dict, json_body: dict, deadline_s: float
    ) -> httpx.Response:
        """Single-shot POST bounded by a wall-clock deadline.

        Runs the blocking post on a worker thread; on deadline the client is
        closed (aborts the in-flight request) and a transport timeout is
        raised. Each attempt uses this client only, so closing is safe (the
        caller falls back with a fresh client). R4 P0-3（03-AIE §③）——
        空闲读超时拦不住慢生成，墙钟语义让「30s 真成 30s」。
        """
        result: dict[str, Any] = {}

        def _run() -> None:
            try:
                result["r"] = self._client.post(url, headers=headers, json=json_body)
            except Exception as exc:  # noqa: BLE001 - surfaced below
                result["exc"] = exc

        t = threading.Thread(target=_run, name="resualign-llm-post", daemon=True)
        t.start()
        t.join(timeout=deadline_s)
        if t.is_alive():
            self.close()  # 中断在途请求
            raise _WallClockDeadlineExceeded(deadline_s)
        if "exc" in result:
            raise result["exc"]
        return result["r"]
    def _should_retry_transport(self) -> bool:
        """Whether a transport error may be retried once (short roles only)."""
        return self._retry_transport
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
        max_tokens = self.max_tokens
        _t0 = time.monotonic()
        attempts = 0
        status = "failed"
        try:
            def _post(payload: dict) -> httpx.Response:
                if self._deadline_s is not None:
                    return self._post_with_deadline(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers,
                        payload,
                        self._deadline_s,
                    )
                return self._client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            for attempt in range(self.max_retries + 1):
                attempts += 1
                try:
                    payload = {**body, "max_tokens": max_tokens}
                    # R4 P0-5（03-AIE）：纠错/翻倍重试也带 json_object，避免模型
                    # 退化成 markdown fence 文本（旧实现只在 attempt==0 带）。
                    payload["response_format"] = {"type": "json_object"}
                    r = _post(payload)
                    r.raise_for_status()
                    response = r.json()
                    message = response["choices"][0]["message"]
                    content = message.get("content") or ""
                    finish_reason = response["choices"][0].get("finish_reason")
                    start = content.find("{")
                    if start < 0:
                        if attempt == self.max_retries:
                            raise LLMResponseError(
                                "No JSON object found in response", code="empty"
                            )
                        if (
                            finish_reason == "length"
                            and attempt < self.max_retries
                            and max_tokens < self._token_cap
                        ):
                            max_tokens = min(max_tokens * 2, self._token_cap)
                        time.sleep(1)
                        continue
                    try:
                        result = _parse_json_object(content)
                    except LLMResponseError:
                        if attempt == self.max_retries:
                            # 已携带 code（parse），直接透传。
                            raise
                        time.sleep(1)
                        continue
                    except Exception:
                        if attempt == self.max_retries:
                            raise LLMResponseError(
                                "LLM call failed to parse JSON response "
                                f"after {self.max_retries + 1} attempts",
                                code="parse",
                            ) from None
                        if (
                            finish_reason == "length"
                            and attempt < self.max_retries
                            and max_tokens < self._token_cap
                        ):
                            max_tokens = min(max_tokens * 2, self._token_cap)
                        time.sleep(1)
                        continue
                    status = "ok"
                    return result
                except LLMResponseError:
                    raise
                except httpx.TransportError as e:
                    # R4 P0-4：短角色条件性 1 次重试（瞬时抖动恢复收益高）；
                    # 墙钟 deadline 触发绝不重试（慢生成重试 = 再等一个世纪）。
                    if (
                        self._should_retry_transport()
                        and attempt < self.max_retries
                        and not getattr(e, "deadline_exceeded", False)
                    ):
                        time.sleep(1)  # 网络抖动缓冲
                        continue
                    _raise_network_timeout("LLM", attempt, e)
                except Exception as e:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            f"LLM call failed after {self.max_retries + 1} attempts: {e}",
                            code=_http_error_code(e),
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

    def stream_chat_json(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        idle_timeout: float = 15.0,
        max_tokens: int = 16384,
    ) -> dict:
        """Stream a chat completion over SSE and return the parsed JSON.

        Accumulates ``choices[*].delta.content`` deltas into a single JSON
        string (via ``_stream_deltas``, which yields each token) and returns
        the parsed dict. Raises ``StreamConnectionError`` when no new token
        arrives within ``idle_timeout`` seconds or when the transport stalls /
        disconnects (read/connect timeout, TCP drop).
        """
        _t0 = time.monotonic()
        status = "failed"
        try:
            deltas = list(
                self._stream_deltas(
                    system,
                    user,
                    model=model,
                    idle_timeout=idle_timeout,
                    max_tokens=max_tokens,
                )
            )
            result = _parse_json_object("".join(deltas))
            status = "ok"
            return result
        except StreamConnectionError:
            raise
        except httpx.HTTPError as exc:
            # Provider transport failures (read/connect timeout, silent TCP
            # drop) degrade into the breaker error so role-level fallback can
            # retry on the default node instead of surfacing a raw httpx error.
            raise StreamConnectionError(
                f"Stream transport failure: {exc.__class__.__name__}: {exc}"
            ) from exc
        finally:
            _observe_llm_call(
                stage="stream_chat_json",
                provider=self.provider,
                model=model or self.model,
                duration_ms=(time.monotonic() - _t0) * 1000,
                attempts=1,
                status=status,
            )

    def _stream_deltas(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        idle_timeout: float = 15.0,
        max_tokens: int = 16384,
    ):
        """Yield each streamed content delta, enforcing the idle breaker.

        Applies an ``httpx.Timeout`` scoped to the stream so a fully silent
        provider (no bytes at all) raises a transport timeout after
        ``idle_timeout`` instead of blocking forever, and converts that into
        ``StreamConnectionError``. Individual SSE ``data:`` deltas are yielded
        as they arrive.
        """
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
            "max_tokens": max_tokens,
            "stream": True,
            **self._provider_extras(),
        }
        timeout = httpx.Timeout(
            idle_timeout,
            connect=idle_timeout,
            write=idle_timeout,
            pool=idle_timeout,
        )
        with self._client.stream(
            "POST",
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=body,
            timeout=timeout,
        ) as r:
            r.raise_for_status()
            last_token_at = time.monotonic()
            for line in r.iter_lines():
                line = (line or "").strip()
                if not line.startswith("data:"):
                    if time.monotonic() - last_token_at >= idle_timeout:
                        raise StreamConnectionError(
                            f"No new token received for {idle_timeout}s "
                            "during SSE stream"
                        )
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = chunk["choices"][0]["delta"]
                except (KeyError, IndexError, TypeError):
                    if time.monotonic() - last_token_at >= idle_timeout:
                        raise StreamConnectionError(
                            f"No new token received for {idle_timeout}s "
                            "during SSE stream"
                        ) from None
                    continue
                content = delta.get("content")
                if content:
                    last_token_at = time.monotonic()
                    yield content
                    continue
                if time.monotonic() - last_token_at >= idle_timeout:
                    # Content-less SSE deltas (heartbeats / keep-alive frames
                    # without a token) must not reset the breaker; if the
                    # provider stalls without emitting a token, fall through.
                    raise StreamConnectionError(
                        f"No new token received for {idle_timeout}s "
                        "during SSE stream"
                    ) from None
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
            "max_tokens": self.max_tokens,
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
            def _post() -> httpx.Response:
                if self._deadline_s is not None:
                    return self._post_with_deadline(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers,
                        body,
                        self._deadline_s,
                    )
                return self._client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=body,
                )

            for attempt in range(self.max_retries + 1):
                attempts += 1
                try:
                    r = _post()
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
                            f"{self.max_retries + 1} attempts: {exc}",
                            code=_http_error_code(exc),
                        ) from exc
                    time.sleep(1)
                except ValidationError as exc:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            "Structured response failed schema validation after "
                            f"{self.max_retries + 1} attempts: {exc}",
                            code="schema",
                        ) from exc
                    # One corrective retry (Bug-01): feed validation
                    # errors back so the model can repair the structure.
                    body["messages"][1]["content"] = _schema_feedback_prompt(
                        user, exc
                    )
                    time.sleep(1)
                except (json.JSONDecodeError, LLMResponseError) as exc:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            "Structured response failed validation after "
                            f"{self.max_retries + 1} attempts: {exc}",
                            code=getattr(exc, "code", "parse"),
                        ) from exc
                    time.sleep(1)
                except httpx.TransportError as exc:
                    # R4 P0-4：短角色条件性 1 次重试；deadline 触发绝不重试。
                    if (
                        self._should_retry_transport()
                        and attempt < self.max_retries
                        and not getattr(exc, "deadline_exceeded", False)
                    ):
                        time.sleep(1)
                        continue
                    _raise_network_timeout("Structured LLM", attempt, exc)
                except Exception as exc:
                    if attempt == self.max_retries:
                        raise LLMResponseError(
                            "Structured LLM call failed after "
                            f"{self.max_retries + 1} attempts: {exc}",
                            code=_http_error_code(exc),
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
        max_tokens = self.max_tokens
        last_error: Optional[Exception] = None
        _t0 = time.monotonic()
        attempts = 0
        status = "failed"
        try:
            def _post(payload: dict) -> httpx.Response:
                if self._deadline_s is not None:
                    return self._post_with_deadline(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers,
                        payload,
                        self._deadline_s,
                    )
                return self._client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            for attempt in range(self.max_retries + 1):
                attempts += 1
                try:
                    payload = {**body, "max_tokens": max_tokens}
                    r = _post(payload)
                    r.raise_for_status()
                    response = r.json()
                    message = response["choices"][0]["message"]
                    content = message.get("content") or ""
                    finish_reason = response["choices"][0].get("finish_reason")
                    if (
                        not content
                        and finish_reason == "length"
                        and max_tokens < self._token_cap
                    ):
                        max_tokens = min(
                            max_tokens * 2, self._token_cap
                        )
                        if attempt < self.max_retries:
                            time.sleep(1)
                            continue
                        raise LLMResponseError(
                            "Structured response was empty after "
                            f"{self.max_retries + 1} attempts",
                            code="empty",
                        )
                    result = schema_model.model_validate(
                        _parse_json_object(content)
                    ).model_dump()
                    status = "ok"
                    return result
                except ValidationError as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise LLMResponseError(
                            "Structured response failed schema validation after "
                            f"{self.max_retries + 1} attempts: {last_error}",
                            code="schema",
                        ) from exc
                    # One corrective retry (Bug-01): feed validation
                    # errors back so the model can repair the structure.
                    body["messages"][1]["content"] = _schema_feedback_prompt(
                        user, exc
                    )
                    time.sleep(1)
                except (json.JSONDecodeError, LLMResponseError) as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise LLMResponseError(
                            "Structured response failed schema validation after "
                            f"{self.max_retries + 1} attempts: {last_error}",
                            code=getattr(exc, "code", "parse"),
                        ) from exc
                    time.sleep(1)
                except httpx.TransportError as exc:
                    # R4 P0-4：短角色条件性 1 次重试；deadline 触发绝不重试。
                    if (
                        self._should_retry_transport()
                        and attempt < self.max_retries
                        and not getattr(exc, "deadline_exceeded", False)
                    ):
                        time.sleep(1)
                        continue
                    _raise_network_timeout("Structured LLM", attempt, exc)
                except Exception as exc:
                    last_error = exc
                    if attempt >= self.max_retries:
                        raise LLMResponseError(
                            "Structured LLM call failed after "
                            f"{self.max_retries + 1} attempts: {last_error}",
                            code=_http_error_code(exc),
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
DIAG_PROMPT = """PROMPT_VERSION: diagnose/v3

你是简历审计员。针对主简历文本输出结构化诊断：评估整体质量分、列出问题与技能清单。

## Output Contract（只能输出一个 JSON 对象，3 个字段，不得增减字段）
键名固定为：score / issues / skills

- score：0-100 的整数。评分锚点：80+ = 优秀（可直接投递）；60-79 = 建议优化；<60 = 需重点优化。拿不准时给 60，不要给极端值。
- issues：3-8 条最值得改的问题，每条 ≤ 40 个汉字；直接、具体、可操作；禁止空泛套话；没有问题给 []。
- skills：5-15 个技能/领域标签，每项 ≤ 12 字；技术名词保留原文英文拼写（如 Python、Kubernetes、Kafka）；每个标签必须能在简历原文中找到依据，不得发明。

## 语言
- 值用简历同语言（中文简历 → 中文输出）；键名固定英文；技术名词保留英文原文。

## 提交前自查
- score ∈ [0,100]；issues/skills 数量与单项长度在上限内；每个标签都能在原文找到依据；
- 只输出一个 JSON 对象，无 markdown fence，无任何解释文字。"""
# PROMPT_VERSION bump: diagnose/v2 -> v3（2026-08-25，对照 04b-PE §2.1）
# 本次升级说明：
# - 变更点 1：新增评分锚点（80+/60-79/<60），消除「0 分匹配」与确定性兜底混淆
# - 变更点 2：issues/skills 数量与单项长度封顶（3-8 条 / 5-15 项，≤40 / ≤12）
# - 变更点 3：删除假指令 Max tokens/Temperature（拼接缺陷消失），控制权归调用层
# - 缓存影响：版本常量随文本变更 bump，缓存键自动失效（cache.py 以 prompt_version 为键）；
#   若只改文本不 bump，新旧提示词结果互串缓存（B3 类事故）。
DIAG_PROMPT_VERSION = "v3"
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
