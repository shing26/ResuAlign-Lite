"""Role-based LLM client routing with tiered timeouts and fallback.

``RoleRouter`` resolves an LLM role (diagnose, profiler, gap_analyzer, editor,
evaluator) to a provider node via ``LLMNodeStore.resolve_node_for_role``,
creates an ``OpenAIClient`` with the role-appropriate timeout, and provides
a single-call-fallback wrapper for the pipeline.

Tiered timeouts (env overrides via ``RESUALIGN_ROLE_TIMEOUT_<ROLE>``):

- profiler / gap_analyzer: 30s
- diagnose: 45s
- editor: 90s (heavier generation)
- evaluator: 60s
- connect timeout: 30s (shared via OpenAIClient.DEFAULT_CONNECT_TIMEOUT)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .llm import LLMClient, LLMResponseError, OpenAIClient
from .llm_nodes import LLMNodeStore

logger = logging.getLogger(__name__)

# Per-role timeout defaults (seconds). Environment variables override:
# ``RESUALIGN_ROLE_TIMEOUT_DIAGNOSE``, ``RESUALIGN_ROLE_TIMEOUT_PROFILER``, etc.
_ROLE_TIMEOUT_DEFAULTS: dict[str, float] = {
    "diagnose": 45.0,
    "profiler": 30.0,
    "gap_analyzer": 30.0,
    "editor": 90.0,
    "evaluator": 60.0,
}
def _role_timeout(role: str) -> float:
    """Return the effective timeout for a role (env override > default)."""
    key = f"RESUALIGN_ROLE_TIMEOUT_{role.upper()}"
    env_val = os.environ.get(key)
    if env_val:
        try:
            return float(env_val)
        except (ValueError, TypeError):
            pass
    return _ROLE_TIMEOUT_DEFAULTS.get(role, 30.0)


def resolve_config_for_role(
    node_store: LLMNodeStore,
    tenant_id: str,
    role: str,
) -> dict[str, Any] | None:
    """Resolve a role to a node config dict, or None.

    Uses ``resolve_node_for_role`` which returns the bound node, active node,
    or None if no node exists at all.
    """
    node = node_store.resolve_node_for_role(tenant_id, role)
    if node is None:
        return None
    return {
        "provider": node.get("provider", ""),
        "model": node.get("model", ""),
        "api_key": node.get("api_key", ""),
        "base_url": node.get("base_url", ""),
    }


def create_client_for_role(
    node_store: LLMNodeStore,
    tenant_id: str,
    role: str,
    timeout: float | None = None,
) -> OpenAIClient | None:
    """Create an ``OpenAIClient`` for the resolved role node.

    Returns ``None`` when no node is configured at all.
    """
    resolved = resolve_config_for_role(node_store, tenant_id, role)
    if resolved is None:
        return None
    from .models import ResuAlignConfig

    config = ResuAlignConfig(**resolved)
    return OpenAIClient(
        config,
        timeout=timeout if timeout is not None else _role_timeout(role),
    )


def call_with_role(
    role: str,
    fn: Any,
    node_store: LLMNodeStore,
    tenant_id: str,
    *,
    fn_kwargs: dict[str, Any] | None = None,
    default_config: Any = None,
) -> tuple[Any, dict[str, Any]]:
    """Call a pipeline function with the role-appropriate LLM client.

    The function receives ``client`` as the first positional argument plus
    any ``fn_kwargs``.  On ``LLMResponseError`` (after the client's internal
    retries), it falls back to the default node once.

    Returns ``(result, meta)`` where ``meta`` carries:
    - ``role``: the role name
    - ``node_name``: the resolved node name
    - ``model``: the resolved model
    - ``fallback_used``: whether fallback was exercised
    - ``fallback_node_name``: the fallback node name (if fallback happened)
    - ``error``: error message (if both attempts failed)
    """
    fn_kwargs = dict(fn_kwargs or {})
    meta: dict[str, Any] = {
        "role": role,
        "node_name": "",
        "model": "",
        "fallback_used": False,
        "fallback_node_name": None,
        "error": None,
    }

    # ---- Primary attempt with role node ----
    resolved = resolve_config_for_role(node_store, tenant_id, role)
    if resolved is not None:
        from .models import ResuAlignConfig
        primary_config = ResuAlignConfig(**resolved)
        meta["node_name"] = resolved.get("model", "")
        meta["model"] = resolved.get("model", "")
        client = OpenAIClient(primary_config, timeout=_role_timeout(role))
        try:
            result = fn(client, **fn_kwargs)
            return result, meta
        except LLMResponseError as exc:
            logger.warning(
                "Role %s primary node failed: %s; falling back to default",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        except Exception as exc:
            logger.warning(
                "Role %s primary node unexpected error: %s; falling back to default",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        finally:
            client.close()

    # ---- Fallback to default node ----
    if default_config is not None:
        fallback_config = default_config
    else:
        fallback_node = node_store.get_active_node(tenant_id)
        if fallback_node is None:
            meta["error"] = "No default node available for fallback"
            raise LLMResponseError(meta["error"])
        from .models import ResuAlignConfig
        fallback_config = ResuAlignConfig(
            provider=fallback_node.get("provider", ""),
            model=fallback_node.get("model", ""),
            api_key=fallback_node.get("api_key", ""),
            base_url=fallback_node.get("base_url", ""),
        )
        meta["fallback_node_name"] = fallback_node.get("name", "")

    client = OpenAIClient(fallback_config, timeout=_role_timeout(role))
    try:
        result = fn(client, **fn_kwargs)
        return result, meta
    except Exception as exc:
        meta["error"] = str(exc)[:200]
        raise
    finally:
        client.close()


def is_parallel_safe(
    node_store: LLMNodeStore,
    tenant_id: str,
    *roles: str,
) -> bool:
    """Return True when all given roles resolve to non-local nodes.

    Parallel execution is only safe (and beneficial) when every independent
    role uses a cloud API. Local Ollama nodes are serialized regardless.
    """
    for role in roles:
        node = node_store.resolve_node_for_role(tenant_id, role)
        if node_store._is_local_node(node):
            return False
    return True
