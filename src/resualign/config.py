"""Shared configuration layer for ResuAlign.

Provides EnvSettings and build_config so that CLI, API, and benchmarks
all resolve LLM credentials from the same source-of-truth stack.
"""

from __future__ import annotations

from typing import Any, Callable

from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import ResuAlignConfig

RUNTIME_LLM_OVERRIDE: dict[str, str | None] = {
    "provider": None,
    "model": None,
}

# Optional callback that returns persisted LLM settings (provider/model/
# api_key/base_url) from the user settings store. Registered by the API
# settings router; CLI and benchmark processes never register one, so they
# keep resolving purely from kwargs/.env/env vars.
_STORED_LLM_PROVIDER: Callable[[], dict[str, Any]] | None = None


def register_stored_llm_provider(provider: Callable[[], dict[str, Any]] | None) -> None:
    """Register a callable returning persisted LLM settings.

    The callable is invoked per ``build_config()`` call (not cached), so
    store swaps and settings updates are picked up immediately. Results are
    only used for fields that resolve to non-empty values.
    """
    global _STORED_LLM_PROVIDER
    _STORED_LLM_PROVIDER = provider


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
    resualign_data_dir: str = ""
    resualign_upload_dir: str = ""
    # String type on purpose: invalid values are clamped by the worker
    # concurrency resolver instead of failing EnvSettings validation.
    resualign_worker_concurrency: str = "1"

    # Reminder delivery (non-secret fields may be mirrored in settings store;
    # webhook URL/secret and SMTP password always stay environment-only).
    resualign_reminder_interval_seconds: str = ""
    resualign_reminder_webhook_url: str = ""
    resualign_reminder_webhook_provider: str = "generic"
    resualign_reminder_webhook_secret: str = ""
    resualign_smtp_host: str = ""
    resualign_smtp_port: int = 587
    resualign_smtp_user: str = ""
    resualign_smtp_password: str = ""
    resualign_smtp_from: str = ""
    resualign_reminder_email_to: str = ""


def _stored_values(stored: dict[str, Any] | None) -> dict[str, Any]:
    """Resolve the persisted-settings layer for build_config.

    ``stored`` (explicit kwarg) wins over the registered provider, which is
    only consulted when the API layer is present. Only non-empty values
    count: an empty/absent field falls through to .env / env vars, which
    keeps existing environment-based configuration working.
    """
    candidate: dict[str, Any] = {}
    if stored is not None:
        candidate = stored
    elif _STORED_LLM_PROVIDER is not None:
        try:
            candidate = _STORED_LLM_PROVIDER()
        except Exception:
            candidate = {}
    if not isinstance(candidate, dict):
        return {}
    return {
        key: value
        for key, value in candidate.items()
        if value is not None and value != ""
    }


def build_config(
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    stored: dict[str, Any] | None = None,
) -> ResuAlignConfig:
    """Build a ResuAlignConfig from env/dotenv with optional overrides.

    CLI passes explicit overrides; the API layer calls with no arguments.
    Priority: explicit kwarg > runtime override > persisted settings store
    > .env file > env variable. Persisted values apply per-field and only
    when non-empty, so a user who never saved API settings keeps the
    .env / env-var configuration intact.
    """
    env = EnvSettings()
    persisted = _stored_values(stored)
    persisted_provider = persisted.get("provider", "")
    resolved_provider = (
        provider
        or RUNTIME_LLM_OVERRIDE.get("provider")
        or persisted_provider
        or env.llm_provider
        or "deepseek"
    )

    # Persisted values are provider-scoped (same rule as env vars): they
    # only apply when no stored provider is set or it matches the resolved
    # provider, so a saved key is never sent to a different provider.
    persisted_applies = not persisted_provider or persisted_provider == resolved_provider

    key_var = f"{resolved_provider.upper()}_API_KEY"
    model_var = f"{resolved_provider.upper()}_MODEL"
    base_url_var = f"{resolved_provider.upper()}_BASE_URL"

    resolved_api_key = (
        api_key
        or (persisted.get("api_key") if persisted_applies else "")
        or getattr(env, key_var.lower(), "")
    )
    resolved_model = (
        model
        or RUNTIME_LLM_OVERRIDE.get("model")
        or (persisted.get("model") if persisted_applies else "")
        or getattr(env, model_var.lower(), "")
        or "deepseek-chat"
    )
    resolved_base_url = (
        base_url
        or (persisted.get("base_url") if persisted_applies else "")
        or getattr(env, base_url_var.lower(), "")
    )

    return ResuAlignConfig(
        provider=resolved_provider,
        api_key=resolved_api_key,
        model=resolved_model,
        base_url=resolved_base_url,
    )
