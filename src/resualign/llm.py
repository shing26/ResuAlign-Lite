import json
import time
from abc import ABC, abstractmethod
from typing import Optional, ClassVar

import httpx


class LLMResponseError(Exception):
    """Raised when the LLM fails to return a parseable response."""
    pass


class LLMClient(ABC):
    """Abstract LLM client for dependency injection in engine.py."""

    @abstractmethod
    def chat_json(self, system: str, user: str, model: Optional[str] = None) -> dict:
        """Send a chat request and return parsed JSON."""
        ...


class OpenAIClient(LLMClient):
    """Concrete LLM client compatible with OpenAI / DeepSeek / Ollama APIs."""

    # Defaults that can be overridden per instance or per subclass
    DEFAULT_MAX_TOKENS: ClassVar[int] = 16384
    DEFAULT_MAX_RETRIES: ClassVar[int] = 2
    DEFAULT_TIMEOUT: ClassVar[float] = 180.0
    DEFAULT_TEMPERATURE: ClassVar[float] = 0.1

    def __init__(self, config, timeout: Optional[float] = None):
        self.api_key = config.api_key
        self.model = config.model
        self.base_url = (
            config.base_url
            or _DEFAULT_PROVIDER_URLS.get(config.provider, "https://api.openai.com/v1")
        )
        self.max_retries = self.DEFAULT_MAX_RETRIES
        self._client = httpx.Client(
            timeout=timeout if timeout is not None else self.DEFAULT_TIMEOUT,
            headers={"Content-Type": "application/json"},
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> "OpenAIClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def chat_json(self, system: str, user: str, model: Optional[str] = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.DEFAULT_TEMPERATURE,
        }

        max_tokens = self.DEFAULT_MAX_TOKENS
        for attempt in range(self.max_retries + 1):
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
                    if finish_reason == "length" and max_tokens < 65536:
                        max_tokens = min(max_tokens * 2, 65536)
                    time.sleep(1)
                    continue
                decoder = json.JSONDecoder()
                try:
                    obj, _ = decoder.raw_decode(content, start)
                    return obj
                except Exception:
                    if attempt == self.max_retries:
                        raise
                    if finish_reason == "length" and max_tokens < 65536:
                        max_tokens = min(max_tokens * 2, 65536)
                    time.sleep(1)
                    continue

            except LLMResponseError:
                raise
            except Exception as e:
                if attempt == self.max_retries:
                    raise LLMResponseError(
                        f"LLM call failed after {self.max_retries + 1} attempts: {e}"
                    ) from e
                time.sleep(1)


DIAG_PROMPT = (
    "You are a resume auditor. Return JSON with score (0-100), issues (list of strings), "
    "and skills (list of strings). Output ONLY JSON."
)
_DEFAULT_PROVIDER_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}

# ---------------------------------------------------------------------------
# LLM client abstractions
# ---------------------------------------------------------------------------
