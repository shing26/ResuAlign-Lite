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

from fastapi import APIRouter, Depends, HTTPException

import resualign.api as api_module

from ...config import EnvSettings
from ..deps import get_current_user
from ..schemas import LLMNodeCreateRequest, LLMNodeUpdateRequest
from .settings import mask_api_key, probe_llm_connection

router = APIRouter()

# Node probe timeout: a light connectivity check should never block the
# request for long even when a provider hangs (matches test-connection).
_NODE_TEST_TIMEOUT = 10.0


def _nodes_store() -> Any:
    store = getattr(api_module, "_llm_nodes", None)
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
    provider = (env.llm_provider or "deepseek").strip().lower()
    api_key = getattr(env, f"{provider}_api_key", "") or ""
    model = getattr(env, f"{provider}_model", "") or ""
    base_url = getattr(env, f"{provider}_base_url", "") or ""
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
        base_url=base_url or None,
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


@router.post("/api/llm/nodes", status_code=201)
def create_llm_node(
    req: LLMNodeCreateRequest, user: dict[str, Any] = Depends(get_current_user)
):
    """Register a new LLM node. The first node becomes the active one."""
    try:
        node = _nodes_store().create_node(
            user["user_id"],
            name=req.name,
            provider=req.provider,
            base_url=req.base_url,
            api_key=req.api_key,
            model=req.model,
        )
    except api_module.UserStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _public_node(node)


@router.put("/api/llm/nodes/{node_id}")
def update_llm_node(
    node_id: str,
    req: LLMNodeUpdateRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Partially update a node; any editable field may be changed."""
    try:
        node = _nodes_store().update_node(
            user["user_id"], node_id, req.model_dump(exclude_unset=True)
        )
    except api_module.UserStoreError as exc:
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
