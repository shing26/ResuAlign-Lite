"""LLM connectivity probing shared by settings and node administration."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ...llm import _DEFAULT_PROVIDER_URLS

_TEST_CONNECT_TIMEOUT = 10.0


def mask_api_key(api_key: str | None) -> str | None:
    """Mask a key for display: ``sk-abc1234`` -> ``sk-a••••1234``."""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "••••"
    return f"{api_key[:4]}••••{api_key[-4:]}"


def http_error_detail(exc: httpx.HTTPStatusError) -> str:
    """Extract the provider's readable error message when one is present."""
    try:
        data = exc.response.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if data.get("detail"):
            return str(data["detail"])
    return str(exc)


def probe_llm_connection(
    *,
    provider: str,
    api_key: str | None,
    model: str,
    base_url: str | None,
    timeout: float = _TEST_CONNECT_TIMEOUT,
) -> dict[str, Any]:
    """Probe a provider with a minimal one-token chat request."""
    if not api_key and provider != "ollama":
        return {
            "ok": False,
            "status": "missing_key",
            "latency_ms": None,
            "message": (
                "尚未配置 API Key：请先在表单中填写并保存，或通过 .env 配置。"
            ),
        }
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    base = (
        base_url
        or _DEFAULT_PROVIDER_URLS.get(provider, "https://api.openai.com/v1")
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    start = time.monotonic()
    try:
        response = httpx.post(
            f"{base.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        readable = {
            400: "请求被拒绝：请检查模型名称与参数",
            401: "认证失败：API Key 无效或已过期",
            402: (
                "余额不足：请给该节点充值，或到「系统设置 → 模型节点」"
                "切换可用节点后重试"
            ),
            403: "权限不足：该 Key 无权访问所选模型，可到「系统设置 → 模型节点」更换",
            404: "模型或端点不存在：请检查模型名称与 Base URL",
            429: "请求过于频繁：已触发限流，请稍后再试",
        }
        message = readable.get(
            status,
            f"服务返回错误（HTTP {status}）：{http_error_detail(exc)}",
        )
        return {
            "ok": False,
            "status": f"http_{status}",
            "latency_ms": (time.monotonic() - start) * 1000,
            "message": message,
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "status": "timeout",
            "latency_ms": (time.monotonic() - start) * 1000,
            "message": (
                f"连接超时（{int(timeout)} 秒）："
                "请检查网络、Base URL 或服务可用性"
            ),
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "status": "network_error",
            "latency_ms": (time.monotonic() - start) * 1000,
            "message": f"网络错误：{exc}",
        }
    return {
        "ok": True,
        "status": "ok",
        "latency_ms": (time.monotonic() - start) * 1000,
        "message": f"连接成功：{provider} · {model}",
    }
