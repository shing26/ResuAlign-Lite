
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ...config import (
    clear_runtime_llm,
    register_stored_llm_provider,
    set_runtime_llm,
)
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

    The active ``llm_nodes`` entry wins over the legacy single-node ``llm``
    settings field; the legacy field remains the fallback while the tenant
    has no nodes. The callback is re-invoked per ``build_config()`` call, so
    activating a different node hot-reloads the pipeline config.
    """
    store = getattr(api_module, "_settings_store", None)
    if store is None or not getattr(api_module, "_PERSONAL_MODE", False):
        return {}
    try:
        nodes = getattr(api_module, "_llm_nodes", None)
        if nodes is not None:
            node = nodes.get_active_node("local")
            if node is not None:
                return {
                    "provider": node.get("provider"),
                    "model": node.get("model"),
                    "api_key": node.get("api_key"),
                    "base_url": node.get("base_url"),
                }
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



@router.get('/api/settings/role-bindings')
def get_role_bindings(user: dict[str, Any] = Depends(get_current_user)):
    """Return the current role-to-node bindings, available roles, and nodes."""
    nodes = getattr(api_module, "_llm_nodes", None)
    if nodes is None:
        return {"roles": [], "nodes": [], "bindings": {}}
    bindings = nodes.get_role_bindings(user["user_id"])
    node_list = [
        {
            "node_id": n["node_id"],
            "name": n["name"],
            "provider": n["provider"],
            "model": n["model"],
        }
        for n in nodes.list_nodes(user["user_id"])
    ]
    return {
        "roles": list(nodes.list_roles()),
        "nodes": node_list,
        "bindings": bindings,
    }


@router.put('/api/settings/role-bindings')
def update_role_bindings(
    body: dict[str, str | None],
    user: dict[str, Any] = Depends(get_current_user),
):
    """Update role bindings. Accepts a dict of {role: node_id_or_null}."""
    nodes = getattr(api_module, "_llm_nodes", None)
    if nodes is None:
        raise HTTPException(status_code=503, detail="LLM node store not available")
    for role, node_id in body.items():
        if node_id is None:
            nodes.delete_role_binding(user["user_id"], role)
        else:
            ok = nodes.set_role_binding(user["user_id"], role, str(node_id))
            if not ok:
                raise HTTPException(
                    status_code=422,
                    detail=f"Node {node_id} not found for role {role}",
                )
    return {"status": "ok", "bindings": nodes.get_role_bindings(user["user_id"])}


@router.post('/api/settings/role-bindings/presets')
def apply_role_preset(
    body: dict[str, str],
    user: dict[str, Any] = Depends(get_current_user),
):
    """Apply a one-click preset: unified, hybrid, or local."""
    nodes = getattr(api_module, "_llm_nodes", None)
    if nodes is None:
        raise HTTPException(status_code=503, detail="LLM node store not available")
    preset = (body.get("preset") or "").strip().lower()
    all_nodes = nodes.list_nodes(user["user_id"])
    if not all_nodes:
        return {"status": "ok", "message": "No nodes configured", "bindings": {}}

    # Find ollama / cloud nodes
    ollama_nodes = [n for n in all_nodes if n["provider"] == "ollama"]
    cloud_nodes = [n for n in all_nodes if n["provider"] != "ollama"]

    if preset == "unified":
        nodes.clear_role_bindings(user["user_id"])
    elif preset == "hybrid":
        # Extractives -> ollama; generative -> cloud
        if not ollama_nodes or not cloud_nodes:
            message = "Hybrid preset requires both an Ollama and a cloud node"
            return {"status": "skipped", "message": message, "bindings": nodes.get_role_bindings(user["user_id"])}
        ollama_node = ollama_nodes[0]
        cloud_node = cloud_nodes[0]
        nodes.set_role_binding(user["user_id"], "diagnose", ollama_node["node_id"])
        nodes.set_role_binding(user["user_id"], "profiler", ollama_node["node_id"])
        nodes.set_role_binding(user["user_id"], "gap_analyzer", ollama_node["node_id"])
        nodes.set_role_binding(user["user_id"], "editor", cloud_node["node_id"])
        nodes.set_role_binding(user["user_id"], "evaluator", cloud_node["node_id"])
    elif preset == "local":
        if not ollama_nodes:
            message = "Local preset requires an Ollama node"
            return {"status": "skipped", "message": message, "bindings": nodes.get_role_bindings(user["user_id"])}
        ollama_node = ollama_nodes[0]
        for role in nodes.list_roles():
            nodes.set_role_binding(user["user_id"], role, ollama_node["node_id"])
    else:
        raise HTTPException(status_code=422, detail=f"Unknown preset: {preset}")

    return {"status": "ok", "bindings": nodes.get_role_bindings(user["user_id"])}
@router.get('/api/settings')
def get_settings(user: dict[str, Any]=Depends(get_current_user)):
    """Return the current user's editable workbench settings."""
    settings = api_module._settings_store.get_settings(user['user_id'])
    if not settings.get('local_ingest_token'):
        api_module._settings_store.get_or_create_local_ingest_token(
            user['user_id']
        )
        settings = api_module._settings_store.get_settings(user['user_id'])
    return _public_settings(settings)


@router.post('/api/settings/local-ingest-token/reset')
def reset_local_ingest_token(
    user: dict[str, Any] = Depends(get_current_user),
):
    """Generate a fresh local-ingest token, invalidating the old one."""
    token = api_module._settings_store.reset_local_ingest_token(
        user['user_id']
    )
    return {'local_ingest_token': token}

@router.put('/api/settings')
def update_settings(req: SettingsUpdateRequest, user: dict[str, Any]=Depends(get_current_user)):
    """Persist validated settings updates for the current user."""
    _validate_vocabulary_update(req)
    payload = req.model_dump()
    nullable_keys = (
        "llm_provider",
        "llm_model",
        "daily_llm_cap",
        "llm_cost_per_1k_in",
        "llm_cost_per_1k_out",
    )
    updates = {
        key: value
        for key, value in payload.items()
        if value is not None or key in nullable_keys
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
    daily = api_module.llm_daily_status(user["user_id"])
    return {
        "api_key_configured": config.is_llm_configured,
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
        "daily": daily,
    }


def probe_llm_connection(
    *,
    provider: str,
    api_key: str | None,
    model: str,
    base_url: str | None,
    timeout: float = _TEST_CONNECT_TIMEOUT,
) -> dict[str, Any]:
    """Probe an LLM provider with a minimal one-token chat request.

    Shared by ``/api/settings/test-connection`` (current effective config)
    and ``/api/llm/nodes/{id}/test`` (a specific node). Returns
    ``{ok, status, latency_ms, message}`` with a readable failure reason
    (auth, model missing, timeout, network).
    """
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
            403: "权限不足：该 Key 无权访问所选模型",
            404: "模型或端点不存在：请检查模型名称与 Base URL",
            429: "请求过于频繁：已触发限流，请稍后再试",
        }
        message = readable.get(
            status, f"服务返回错误（HTTP {status}）：{_http_error_detail(exc)}"
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


@router.post('/api/settings/test-connection')
def test_llm_connection(
    req: SettingsTestConnectionRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Probe the current effective LLM config with a minimal chat request.

    Resolution matches the real pipeline: submitted form values > persisted
    store > .env / env vars. Returns ``{ok, status, latency_ms, message}``
    with a readable failure reason (auth, model missing, timeout, network).
    """
    config = api_module.build_config(
        provider=req.provider,
        api_key=req.api_key,
        model=req.model,
        base_url=req.base_url,
    )
    return probe_llm_connection(
        provider=config.provider,
        api_key=config.api_key,
        model=config.model,
        base_url=config.base_url,
    )


@router.post('/api/settings/reset')
def reset_settings(user: dict[str, Any] = Depends(get_current_user)):
    """Restore the built-in vocabulary and default settings."""
    api_module._settings_store.update_settings(user["user_id"], default_settings())
    # The local-ingest token is a security credential, not a preference:
    # restoring defaults keeps the current token so the userscript keeps
    # working until the user explicitly resets it.
    api_module._settings_store.get_or_create_local_ingest_token(
        user["user_id"]
    )
    clear_runtime_llm()
    return _public_settings(api_module._settings_store.get_settings(user["user_id"]))
