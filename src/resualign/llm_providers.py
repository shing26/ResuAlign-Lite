"""Known OpenAI-compatible LLM providers and Base URL detection.

The application talks to OpenAI-compatible ``/chat/completions`` and
``/models`` endpoints. Provider names are still useful for labels, default
URLs, and a few request quirks, but a custom OpenAI-compatible endpoint must
remain usable without adding a new provider adapter.
"""

from __future__ import annotations

from urllib.parse import urlparse

PROVIDER_DEFAULT_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "volcengine": "https://ark.cn-beijing.volces.com/api/v3",
    "groq": "https://api.groq.com/openai/v1",
    "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "xai": "https://api.x.ai/v1",
    "custom": "",
}

PROVIDER_LABELS: dict[str, str] = {
    "auto": "自动识别",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
    "nvidia": "NVIDIA NIM",
    "siliconflow": "硅基流动",
    "moonshot": "Moonshot",
    "zhipu": "智谱 AI",
    "dashscope": "阿里云百炼",
    "volcengine": "火山方舟",
    "groq": "Groq",
    "mistral": "Mistral",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "xai": "xAI",
    "custom": "OpenAI 兼容接口",
}

ALLOWED_PROVIDERS: tuple[str, ...] = tuple(PROVIDER_DEFAULT_URLS)

_HOST_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ollama", ("localhost:11434", "127.0.0.1:11434", "0.0.0.0:11434", "[::1]:11434")),
    ("nvidia", ("integrate.api.nvidia.com",)),
    ("siliconflow", ("api.siliconflow.cn", "api.siliconflow.com")),
    ("moonshot", ("api.moonshot.cn", "api.moonshot.ai")),
    ("zhipu", ("open.bigmodel.cn", "api.z.ai")),
    ("dashscope", ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com")),
    ("volcengine", ("ark.cn-beijing.volces.com",)),
    ("groq", ("api.groq.com",)),
    ("mistral", ("api.mistral.ai",)),
    ("together", ("api.together.xyz", "api.together.ai")),
    ("fireworks", ("api.fireworks.ai",)),
    ("xai", ("api.x.ai",)),
    ("openrouter", ("openrouter.ai",)),
    ("deepseek", ("api.deepseek.com",)),
    ("openai", ("api.openai.com",)),
)


def normalize_base_url(base_url: str | None) -> str:
    """Trim a Base URL and remove trailing slashes."""
    return str(base_url or "").strip().rstrip("/")


def detect_provider(base_url: str | None) -> str | None:
    """Detect a known provider from a Base URL.

    Unknown OpenAI-compatible URLs return ``None`` so callers can keep the
    explicit provider choice or use the generic ``custom`` provider.
    """
    value = normalize_base_url(base_url)
    if not value:
        return None
    parsed = urlparse(value if "://" in value else f"//{value}")
    target = f"{parsed.netloc.lower()}{parsed.path.lower()}"
    for provider, markers in _HOST_MARKERS:
        if any(marker in target for marker in markers):
            return provider
    return None


def resolve_provider(provider: str | None, base_url: str | None) -> str:
    """Resolve ``auto`` / blank providers against a Base URL.

    Explicit known providers are preserved. Unknown explicit values fall back
    to ``custom`` rather than being accepted unchecked by the node store.
    """
    value = str(provider or "").strip().lower()
    if value in {"", "auto"}:
        return detect_provider(base_url) or "custom"
    if value == "custom":
        return "custom"
    if value in ALLOWED_PROVIDERS:
        return value
    return "custom"


def default_base_url(provider: str | None) -> str:
    """Return the provider default Base URL, or an empty string for custom."""
    return PROVIDER_DEFAULT_URLS.get(str(provider or "").strip().lower(), "")


__all__ = [
    "ALLOWED_PROVIDERS",
    "PROVIDER_DEFAULT_URLS",
    "PROVIDER_LABELS",
    "default_base_url",
    "detect_provider",
    "normalize_base_url",
    "resolve_provider",
]
