
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ...config import clear_runtime_llm, register_stored_llm_provider, set_runtime_llm
from ...job_library import JOB_STATUSES
from ...llm import _DEFAULT_PROVIDER_URLS
from ...settings_store import default_settings
from ..deps import get_current_user
from ..schemas import SettingsTestConnectionRequest, SettingsUpdateRequest

router = APIRouter()

# Probe timeout: keep "test connection" snappy even when a provider hangs.
_TEST_CONNECT_TIMEOUT = 10.0


def _stored_llm_snapshot() -> dict[str, Any]:
    """Return persisted LLM settings for the personal (local) tenant.

    ResuAlign defaults to personal mode, where the whole process shares one
    tenant and ``build_config()`` runs without a request-scoped user. In
    multi-tenant mode the process-global pipeline config cannot be attributed
    to one tenant, so the stored layer is skipped (provider/model hot-swap
    via ``set_runtime_llm`` still works there).
    """
    store = getattr(api_module, "_settings_store", None)
    if store is None or not getattr(api_module, "_PERSONAL_MODE", False):
        return {}
    try:
        llm = store.get_settings("local").get("llm") or {}
    except Exception:
        return {}
    return llm


# Wire the persisted settings store into build_config() as the layer between
# the runtime override and .env. Registration happens at import time; the
# callback reads api_module attributes lazily so tests that swap the store
# keep working.
register_stored_llm_provider(_stored_llm_snapshot)


def mask_api_key(api_key: str | None) -> str | None:
    """Mask a key for display: ``sk-abc1234`` -> ``sk-a••••1234``."""
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "••••"
    return f"{api_key[:4]}••••{api_key[-4:]}"


def _public_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Never echo a stored API key back to the client; mask it instead."""
    public = dict(settings)
    llm = dict(settings.get("llm") or {})
    if llm.get("api_key"):
        llm["api_key"] = mask_api_key(llm["api_key"])
    public["llm"] = llm
    return public


def _http_error_detail(exc: httpx.HTTPStatusError) -> str:
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


def _validate_vocabulary_update(req: SettingsUpdateRequest) -> None:
    """Reject corrupted classification vocabulary updates with a 422.

    ``statuses`` is a controlled whitelist (must be a subset of the built-in
    five values); ``job_functions``/``seniorities`` must stay non-empty
    lists. The store re-validates the merged result as a second line of
    defense.
    """
    vocabulary = req.classification_vocabulary
    if vocabulary is None:
        return
    statuses = vocabulary.get("statuses")
    if statuses is not None:
        if not isinstance(statuses, list) or not statuses:
            raise HTTPException(
                status_code=422,
                detail="classification_vocabulary.statuses 必须是非空列表",
            )
        invalid = [
            str(value)
            for value in statuses
            if str(value or "").strip() not in JOB_STATUSES
        ]
        if invalid:
            raise HTTPException(
                status_code=422,
                detail=(
                    "classification_vocabulary.statuses 包含非法值："
                    + ", ".join(invalid)
                    + f"（仅允许：{'、'.join(JOB_STATUSES)}）"
                ),
            )
    for key in ("job_functions", "seniorities"):
        values = vocabulary.get(key)
        if values is not None and (
            not isinstance(values, list) or not values
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    f"classification_vocabulary.{key} 必须是非空列表"
                ),
            )


@router.get('/api/settings')
def get_settings(user: dict[str, Any]=Depends(get_current_user)):
    """Return the current user's editable workbench settings."""
    return _public_settings(
        api_module._settings_store.get_settings(user['user_id'])
    )

@router.put('/api/settings')
def update_settings(req: SettingsUpdateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Persist validated settings updates for the current user."""
    _validate_vocabulary_update(req)
    payload = req.model_dump()
    updates = {
        key: value
        for key, value in payload.items()
        if value is not None or key in ("llm_provider", "llm_model")
    }
    if req.llm is not None:
        # Keep only explicitly-set fields so omitted keys leave the stored
        # value untouched, while explicit nulls clear them.
        updates["llm"] = req.llm.model_dump(exclude_unset=True)
    try:
        saved = api_module._settings_store.update_settings(
            user['user_id'], updates
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if "llm_provider" in updates or "llm_model" in updates or "llm" in updates:
        set_runtime_llm(
            provider=saved.get("llm_provider"),
            model=saved.get("llm_model"),
        )
    return _public_settings(saved)


@router.get('/api/settings/status')
def settings_status(user: dict[str, Any] = Depends(get_current_user)):
    """Return runtime status so the settings page is not just raw forms."""
    config = api_module.build_config()
    return {
        "api_key_configured": bool(config.api_key),
        "provider": config.provider,
        "model": config.model,
        "personal_mode": api_module._PERSONAL_MODE,
        "resume_count": len(
            api_module._resumes.list_master_resumes(user["user_id"])
        ),
        "job_count": len(
            api_module._jobs.list_jobs(user["user_id"], limit=500)
        ),
        "application_count": len(
            api_module._applications.list_applications(user["user_id"])
        ),
    }


@router.post('/api/settings/test-connection')
def test_llm_connection(
    req: SettingsTestConnectionRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Probe the LLM provider with a minimal one-token chat request.

    Resolution matches the real pipeline: submitted form values > persisted
    store > .env / env vars. Returns ``{ok, message}`` with a readable
    failure reason (auth, model missing, timeout, network).
    """
    config = api_module.build_config(
        provider=req.provider,
        api_key=req.api_key,
        model=req.model,
        base_url=req.base_url,
    )
    if not config.api_key and config.provider != "ollama":
        return {
            "ok": False,
            "message": (
                "尚未配置 API Key：请先在表单中填写并保存，或通过 .env 配置。"
            ),
        }
    headers: dict[str, str] = {}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    base_url = (
        config.base_url
        or _DEFAULT_PROVIDER_URLS.get(config.provider, "https://api.openai.com/v1")
    )
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json=payload,
            timeout=_TEST_CONNECT_TIMEOUT,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        readable = {
            400: "请求被拒绝：请检查模型名称与参数",
            401: "认证失败：API Key 无效或已过期",
            403: "权限不足：该 Key 无权访问所选模型",
            404: "模型或端点不存在：请检查模型名称与 Base URL",
            429: "请求过于频繁：已触发限流，请稍后再试",
        }
        message = readable.get(
            status, f"服务返回错误（HTTP {status}）：{_http_error_detail(exc)}"
        )
        return {"ok": False, "message": message}
    except httpx.TimeoutException:
        return {
            "ok": False,
            "message": (
                f"连接超时（{int(_TEST_CONNECT_TIMEOUT)} 秒）："
                "请检查网络、Base URL 或服务可用性"
            ),
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "message": f"网络错误：{exc}"}
    return {"ok": True, "message": f"连接成功：{config.provider} · {config.model}"}


@router.post('/api/settings/reset')
def reset_settings(user: dict[str, Any] = Depends(get_current_user)):
    """Restore the built-in weights, vocabulary, and salary reference."""
    api_module._settings_store.update_settings(user["user_id"], default_settings())
    clear_runtime_llm()
    return _public_settings(api_module._settings_store.get_settings(user["user_id"]))
