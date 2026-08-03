"""Shared configuration layer for ResuAlign.

Provides EnvSettings and build_config so that CLI, API, and benchmarks
all resolve LLM credentials from the same source-of-truth stack.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import ResuAlignConfig


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


def build_config(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
) -> ResuAlignConfig:
    """Build a ResuAlignConfig from env/dotenv with optional overrides.

    CLI passes explicit overrides; the API layer calls with no arguments.
    Priority: explicit kwarg > .env file > environment variable.
    """
    env = EnvSettings()
    resolved_provider = provider or env.llm_provider or "deepseek"

    key_var = f"{resolved_provider.upper()}_API_KEY"
    model_var = f"{resolved_provider.upper()}_MODEL"
    base_url_var = f"{resolved_provider.upper()}_BASE_URL"

    resolved_api_key = api_key or getattr(env, key_var.lower(), "")
    resolved_model = model or getattr(env, model_var.lower(), "deepseek-chat")
    resolved_base_url = base_url or getattr(env, base_url_var.lower(), "")

    return ResuAlignConfig(
        provider=resolved_provider,
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
    )
