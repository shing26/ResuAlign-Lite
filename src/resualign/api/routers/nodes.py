"""Multi-node LLM configuration: CRUD, activation, and connectivity probes.

Sprint 5: tenants can register several LLM provider nodes and activate one
at a time; ``build_config()`` hot-reloads the active node without a restart
(see ``settings._stored_llm_snapshot``). A tenant with no nodes is seeded
once from .env / env vars on the first ``GET /api/llm/nodes``; after that
the SQLite ``llm_nodes`` table is authoritative.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ...app.context import context
from ...config import EnvSettings
from ...engine.llm_providers import (
    default_base_url,
    normalize_base_url,
    resolve_provider,
)
from ..deps import get_current_user
from ..schemas import (
    LLMModelsRequest,
    LLMNodeCreateRequest,
    LLMNodeUpdateRequest,
)
from ..services.llm_probe import (
    http_error_detail,
    mask_api_key,
    probe_llm_connection,
)

router = APIRouter()

# Node probe timeout: a light connectivity check should never block the
# request for long even when a provider hangs (matches test-connection).
_NODE_TEST_TIMEOUT = 10.0


def _nodes_store() -> Any:
    store = getattr(context, "_llm_nodes", None)
    if store is None:
        raise HTTPException(status_code=503, detail="LLM node store unavailable")
    return store


def _get_node_or_404(tenant_id: str, node_id: str) -> dict[str, Any]:
    node = _nodes_store().get_node(tenant_id, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="LLM 节点不存在")
    return node


def _public_node(node: dict[str, Any]) -> dict[str, Any]:
    """Never echo a stored API key back to the client; mask it instead."""
    public = dict(node)
    if public.get("api_key"):
        public["api_key"] = mask_api_key(public["api_key"])
    return public


def _seed_default_node(tenant_id: str) -> None:
    """Create the tenant's first node from .env / env vars when none exist.

    The environment is a seed-only source: once the node exists in SQLite
    the ``llm_nodes`` table is authoritative, and later .env changes no
    longer affect the node list. When the environment carries no usable
    credentials the tenant simply stays empty (``build_config`` then falls
    through to its normal .env resolution).
    """
    store = _nodes_store()
    if store.count_nodes(tenant_id) > 0:
        return
    env = EnvSettings()
    raw_provider = (env.llm_provider or "deepseek").strip().lower()
    api_key = getattr(env, f"{raw_provider}_api_key", "") or ""
    model = getattr(env, f"{raw_provider}_model", "") or ""
    base_url = getattr(env, f"{raw_provider}_base_url", "") or ""
    provider = resolve_provider(raw_provider, base_url)
    if provider != "ollama" and not api_key:
        return
    if not model:
        if provider == "deepseek":
            model = "deepseek-chat"
        else:
            return
    store.create_node(
        tenant_id,
        name=".env 默认",
        provider=provider,
        base_url=normalize_base_url(base_url) or default_base_url(provider) or None,
        api_key=api_key or None,
        model=model,
        is_active=True,
    )


@router.get("/api/llm/nodes")
def list_llm_nodes(user: dict[str, Any] = Depends(get_current_user)):
    """List the tenant's LLM nodes (api_key masked).

    Seeds a default node from .env / env vars on the very first access when
    the tenant has no nodes yet.
    """
    tenant_id = user["user_id"]
    _seed_default_node(tenant_id)
    return [_public_node(node) for node in _nodes_store().list_nodes(tenant_id)]


def _extract_model_ids(payload: Any) -> list[str]:
    rows: list[Any] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            rows = payload["data"]
        elif isinstance(payload.get("models"), list):
            rows = payload["models"]
    elif isinstance(payload, list):
        rows = payload
    seen: set[str] = set()
    models: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            value = row.get("id") or row.get("name") or row.get("model")
        else:
            value = row
        model_id = str(value or "").strip()
        key = model_id.lower()
        if not model_id or key in seen:
            continue
        seen.add(key)
        models.append(model_id)
    return sorted(models, key=str.lower)


@router.post("/api/llm/models")
def list_llm_models(
    req: LLMModelsRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Discover models from an OpenAI-compatible endpoint.

    ``provider=auto`` is resolved from Base URL. A saved node's key is reused
    when the edit form leaves the password field blank.
    """
    node = (
        _get_node_or_404(user["user_id"], req.node_id)
        if req.node_id
        else {}
    )
    base_url = normalize_base_url(req.base_url or node.get("base_url"))
    provider = resolve_provider(
        req.provider or node.get("provider"),
        base_url,
    )
    base_url = base_url or default_base_url(provider)
    api_key = str(req.api_key or node.get("api_key") or "").strip()
    if not base_url:
        raise HTTPException(
            status_code=422,
            detail="请填写 Base URL，或选择带默认地址的服务商",
        )
    if not api_key and provider != "ollama":
        raise HTTPException(status_code=422, detail="请填写 API Key")

    root = base_url.rstrip("/")
    if provider == "ollama":
        root = root[:-3] if root.endswith("/v1") else root
        url = f"{root}/api/tags"
    else:
        url = f"{root}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = httpx.get(
            url,
            headers=headers,
            timeout=_NODE_TEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401:
            detail = "认证失败：API Key 无效或已过期"
        elif status == 403:
            detail = "权限不足：该 Key 无权读取模型列表"
        elif status == 404:
            detail = "模型列表端点不存在：请检查 Base URL"
        else:
            detail = (
                f"服务返回错误（HTTP {status}）："
                f"{http_error_detail(exc)}"
            )
        raise HTTPException(status_code=502, detail=detail) from exc
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"连接失败：{exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="模型列表响应不是有效 JSON",
        ) from exc
    models = _extract_model_ids(payload)
    if not models:
        raise HTTPException(status_code=502, detail="服务未返回可用模型")
    return {"provider": provider, "models": models}


@router.post("/api/llm/nodes", status_code=201)
def create_llm_node(
    req: LLMNodeCreateRequest, user: dict[str, Any] = Depends(get_current_user)
):
    """Register a new LLM node. The first node becomes the active one."""
    provider = resolve_provider(req.provider, req.base_url)
    base_url = normalize_base_url(req.base_url) or default_base_url(provider) or None
    try:
        node = _nodes_store().create_node(
            user["user_id"],
            name=req.name,
            provider=provider,
            base_url=base_url,
            api_key=req.api_key,
            model=req.model,
            disable_thinking=req.disable_thinking,
        )
    except context.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _public_node(node)


@router.put("/api/llm/nodes/{node_id}")
def update_llm_node(
    node_id: str,
    req: LLMNodeUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Partially update a node; any editable field may be changed."""
    updates = req.model_dump(exclude_unset=True)
    if "provider" in updates or "base_url" in updates:
        current = _get_node_or_404(user["user_id"], node_id)
        base_source = (
            updates.get("base_url")
            if "base_url" in updates
            else current.get("base_url")
        )
        provider = resolve_provider(
            updates.get("provider", current.get("provider")),
            base_source,
        )
        updates["provider"] = provider
        updates["base_url"] = (
            normalize_base_url(base_source)
            or default_base_url(provider)
            or None
        )
    try:
        node = _nodes_store().update_node(
            user["user_id"], node_id, updates
        )
    except context.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if node is None:
        raise HTTPException(status_code=404, detail="LLM 节点不存在")
    return _public_node(node)


@router.delete("/api/llm/nodes/{node_id}")
def delete_llm_node(
    node_id: str, user: dict[str, Any] = Depends(get_current_user)
):
    """Delete a node.

    Deleting the active node promotes the oldest remaining node to active
    (when any node remains).
    """
    if not _nodes_store().delete_node(user["user_id"], node_id):
        raise HTTPException(status_code=404, detail="LLM 节点不存在")
    return {"ok": True, "node_id": node_id}


@router.post("/api/llm/nodes/{node_id}/activate")
def activate_llm_node(
    node_id: str, user: dict[str, Any] = Depends(get_current_user)
):
    """Activate a node; all other nodes of the tenant become inactive."""
    node = _nodes_store().activate_node(user["user_id"], node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="LLM 节点不存在")
    return _public_node(node)


def _probe_and_record(
    tenant_id: str, node: dict[str, Any]
) -> dict[str, Any]:
    """Probe one node and persist the outcome for the health badge."""
    result = probe_llm_connection(
        provider=node["provider"],
        api_key=node.get("api_key"),
        model=node["model"],
        base_url=node.get("base_url"),
        timeout=_NODE_TEST_TIMEOUT,
    )
    try:
        _nodes_store().record_node_health(
            tenant_id,
            node["node_id"],
            str(result.get("status") or ("ok" if result.get("ok") else "unknown")),
            result.get("latency_ms"),
        )
    except Exception:  # pragma: no cover - telemetry must never fail the test
        logging.getLogger(__name__).exception(
            "Failed to persist node health for %s", node.get("node_id")
        )
    return result


@router.post("/api/llm/nodes/{node_id}/test")
def test_llm_node(
    node_id: str, user: dict[str, Any] = Depends(get_current_user)
):
    """Probe the node's provider with a minimal one-token chat request.

    Returns ``{ok, status, latency_ms, message}`` with a readable failure
    reason (auth, model missing, timeout, network). The outcome is persisted
    so the settings page badge and the workbench failure banner can show
    staleness-aware health without re-probing.
    """
    node = _get_node_or_404(user["user_id"], node_id)
    return _probe_and_record(user["user_id"], node)


@router.post("/api/llm/nodes/test-all")
def test_all_llm_nodes(user: dict[str, Any] = Depends(get_current_user)):
    """Probe every node of the tenant, worst-case ~10s per node serially.

    Node counts are single digits in practice, so serial probing keeps the
    probe semantics identical to the single-node test (no concurrent
    one-token requests to a struggling provider).
    """
    tenant_id = user["user_id"]
    results = []
    for node in _nodes_store().list_nodes(tenant_id):
        result = _probe_and_record(tenant_id, node)
        results.append(
            {
                "node_id": node["node_id"],
                "name": node["name"],
                "is_active": bool(node.get("is_active")),
                **result,
            }
        )
    return {"results": results}
