"""Shared configuration layer for ResuAlign.

Provides EnvSettings and build_config so that CLI, API, and benchmarks
all resolve LLM credentials from the same source-of-truth stack.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import ResuAlignConfig


RUNTIME_LLM_OVERRIDE: dict[str, str | None] = {
    "provider": None,
    "model": None,
}


def set_runtime_llm(
    provider: str | None = None,
    model: str | None = None,
) -> None:
    """Hot-switch the provider/model used by API-side pipelines.

    The override lives in process memory only and is deliberately limited to
    provider/model names; API keys always stay in .env or environment vars.
    """
    RUNTIME_LLM_OVERRIDE["provider"] = (
        str(provider).strip() if provider is not None else None
    )
    RUNTIME_LLM_OVERRIDE["model"] = (
        str(model).strip() if model is not None else None
    )


def clear_runtime_llm() -> None:
    """Drop the in-memory override and fall back to .env / env vars."""
    RUNTIME_LLM_OVERRIDE["provider"] = None
    RUNTIME_LLM_OVERRIDE["model"] = None


class EnvSettings(BaseSettings):
    """Reads provider / api_key / model / base_url from .env or env vars.

    Field naming convention: ``{provider_lowercase}_{field}`` so that
    ``deepseek_api_key``, ``openrouter_model``, etc. all live in one flat
    settings class regardless of which provider is active.
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = ""
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    ollama_model: str = ""

    # App-level runtime settings (also accepted from .env / environment).
    resualign_personal_mode: str = "1"
    resualign_job_db: str = ""
    resualign_crawl_min_interval: float = 1.0
    resualign_crawl_ua_pool: str = ""
    resualign_crawl_proxy: str = ""
    resualign_crawl_playwright: str = "0"


def build_config(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> ResuAlignConfig:
    """Build a ResuAlignConfig from env/dotenv with optional overrides.

    CLI passes explicit overrides; the API layer calls with no arguments.
    Priority: explicit kwarg > runtime override > .env file > env variable.
    """
    env = EnvSettings()
    resolved_provider = (
        provider
        or RUNTIME_LLM_OVERRIDE.get("provider")
        or env.llm_provider
        or "deepseek"
    )

    key_var = f"{resolved_provider.upper()}_API_KEY"
    model_var = f"{resolved_provider.upper()}_MODEL"
    base_url_var = f"{resolved_provider.upper()}_BASE_URL"

    resolved_api_key = api_key or getattr(env, key_var.lower(), "")
    resolved_model = (
        model
        or RUNTIME_LLM_OVERRIDE.get("model")
        or getattr(env, model_var.lower(), "")
        or "deepseek-chat"
    )
    resolved_base_url = base_url or getattr(env, base_url_var.lower(), "")

    return ResuAlignConfig(
        provider=resolved_provider,
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
    )
