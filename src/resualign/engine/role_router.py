"""Role-based LLM client routing with tiered timeouts and fallback.

``RoleRouter`` resolves an LLM role (diagnose, profiler, gap_analyzer, editor,
evaluator) to a provider node via ``LLMNodeStore.resolve_node_for_role``,
creates an ``OpenAIClient`` with the role-appropriate timeout, and provides
a single-call-fallback wrapper for the pipeline.

Tiered timeouts (env overrides via ``RESUALIGN_ROLE_TIMEOUT_<ROLE>``):

- profiler: 75s (was 30s; #116 甲案 after muse p95=43.9s) / gap_analyzer: 60s
- diagnose: 45s
- editor: 90s (heavier generation)
- evaluator: 60s
- connect timeout: 30s (shared via OpenAIClient.DEFAULT_CONNECT_TIMEOUT)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ..contracts.errors import LlmFailureCode
from .llm import LLMResponseError, OpenAIClient, StreamConnectionError
from .llm_nodes import LLMNodeStore

logger = logging.getLogger(__name__)

# Per-role timeout defaults (seconds). Environment variables override:
# ``RESUALIGN_ROLE_TIMEOUT_DIAGNOSE``, ``RESUALIGN_ROLE_TIMEOUT_PROFILER``, etc.
# #116（2026-09-16，用户裁决「甲」解锁 AIE 决策域调值）：app.log 6036 事件实测
# muse-glimmer-30b p95=43.9s/max=124.3s、qwen2.5:7b p95=61.7s，而 ADR-0018 合并
# 画像+缺口调用走 profiler——原 30s 线低于该模型 p95，结构性必超时（#110 的
# 60.3s/71.7s 硬失败、#115 的零产出归因主因）。profiler 30→75（覆盖 71.7s 观测），
# gap_analyzer 30→60；其余角色维持 AIE 表。最坏单发墙钟 45+75+90=210s，远低于
# watchdog RESUALIGN_JOB_MAX_RUNTIME_S=1800。
_ROLE_TIMEOUT_DEFAULTS: dict[str, float] = {
    "diagnose": 45.0,
    "profiler": 75.0,
    "gap_analyzer": 60.0,
    "editor": 90.0,
    "evaluator": 60.0,
}
# R4 P0-2（03-AIE §③）：per-role max_tokens 钳制表 —— 值 = 04b-PE 契约输出上限
# + 30-50% 余量（单位 tokens）。角色路径的输出在传输侧有硬上界，30B 慢模型的
# 生成时延可估算（诊断 ~140 / profiler ~320 / gap ~400 / editor 2600 / eval ~120）。
# 注意：本表只引入新的 max_tokens 参数，不改动 _ROLE_TIMEOUT_DEFAULTS 任何数值
# （护栏数字为 AIE 决策域）。
_ROLE_MAX_TOKENS: dict[str, int] = {
    "diagnose": 512,
    "profiler": 1024,
    "gap_analyzer": 1024,
    "editor": 3072,
    "evaluator": 384,
}
# length 翻倍时的绝对上限（不得逼近 65536；诊断 1024 / profiler·gap 2048 /
# editor 6144 / eval 768）。
_ROLE_TOKEN_CAP: dict[str, int] = {
    "diagnose": 1024,
    "profiler": 2048,
    "gap_analyzer": 2048,
    "editor": 6144,
    "evaluator": 768,
}
# R4 P0-4（03-AIE §③）：短输入/低 token 输出角色允许 transport 超时后条件性
# 1 次重试（瞬时抖动恢复收益高）；长生成角色（editor/tailor）恒 False。
_RETRY_ON_TRANSPORT_ROLES = frozenset(
    {"classifier", "intake", "profiler", "gap_analyzer", "polish"}
)


def _role_max_tokens(role: str) -> int | None:
    """Return the role's clamped starting max_tokens, or None (no clamp)."""
    return _ROLE_MAX_TOKENS.get(role)


def _role_token_cap(role: str) -> int | None:
    """Return the role's length-doubling absolute cap, or None (fallback)."""
    return _ROLE_TOKEN_CAP.get(role)


def _role_deadline(role: str) -> float:
    """Wall-clock deadline for one role attempt == the role timeout (P0-3)."""
    return _role_timeout(role)
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


def role_timeouts() -> dict[str, float]:
    """Return every role's effective timeout, env overrides applied.

    Read-only introspection for the settings status endpoint so the UI shows
    the numbers this process actually enforces instead of a hardcoded guess.
    """
    return {role: _role_timeout(role) for role in _ROLE_TIMEOUT_DEFAULTS}


def resolve_config_for_role(
    node_store: LLMNodeStore,
    tenant_id: str,
    role: str,
) -> dict[str, Any] | None:
    """Resolve a role to a node config dict, or None.

    Uses ``resolve_node_for_role`` which returns the bound node, usable
    active node, or None (ticket #103: auto-disabled nodes are skipped for
    the call chain while their bindings and admin views stay intact).
    """
    return _config_from_node(node_store.resolve_node_for_role(tenant_id, role))


def _config_from_node(node: dict | None) -> dict[str, Any] | None:
    """Project a resolved node dict onto the config shape (or None)."""
    if node is None:
        return None
    return {
        "provider": node.get("provider", ""),
        "model": node.get("model", ""),
        "api_key": node.get("api_key", ""),
        "base_url": node.get("base_url", ""),
        "disable_thinking": bool(node.get("disable_thinking", False)),
    }


def usable_active_node(node_store: Any, tenant_id: str) -> dict | None:
    """The tenant's active node that the call chain may serve with.

    Ticket #103: breaker-aware selection shared by role_router fallbacks,
    the engine role-mode decision, the pre-flight probe and the config
    resolution callback. Duck-typed for node-store fakes in tests: stores
    without breaker support keep ``get_active_node`` semantics.
    """
    usable = getattr(node_store, "get_usable_node", None)
    if callable(usable):
        return usable(tenant_id)
    active = getattr(node_store, "get_active_node", None)
    return active(tenant_id) if callable(active) else None


def _report_call_outcome(
    node_store: Any,
    tenant_id: str,
    node: dict | None,
    *,
    success: bool,
    code: str | None = None,
) -> None:
    """Feed one real call result into the node breaker (ticket #103).

    Telemetry must never break the call: any store without breaker support
    (or a failing write) is swallowed with a warning, exactly like the
    routers' probe best-effort.
    """
    node_id = (node or {}).get("node_id")
    if not node_id:
        return
    try:
        if success:
            cb = getattr(node_store, "record_call_success", None)
            if callable(cb):
                cb(tenant_id, node_id)
        else:
            cb = getattr(node_store, "record_call_failure", None)
            if callable(cb):
                cb(tenant_id, node_id, code or "other")
    except Exception:  # noqa: BLE001 - breaker must never fail the call
        logger.exception("LLM breaker telemetry failed for node %s", node_id)


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
    from ..models import ResuAlignConfig

    config = ResuAlignConfig(**resolved)
    return OpenAIClient(
        config,
        timeout=timeout if timeout is not None else _role_timeout(role),
        max_tokens=_role_max_tokens(role),
        token_cap=_role_token_cap(role),
        deadline=_role_deadline(role),
        retry_transport=role in _RETRY_ON_TRANSPORT_ROLES,
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
    primary_node = node_store.resolve_node_for_role(tenant_id, role)
    resolved = _config_from_node(primary_node)
    if resolved is not None:
        from ..models import ResuAlignConfig
        primary_config = ResuAlignConfig(**resolved)
        meta["node_name"] = resolved.get("model", "")
        meta["model"] = resolved.get("model", "")
        client = OpenAIClient(
            primary_config,
            timeout=_role_timeout(role),
            max_tokens=_role_max_tokens(role),
            token_cap=_role_token_cap(role),
            deadline=_role_deadline(role),
            retry_transport=role in _RETRY_ON_TRANSPORT_ROLES,
        )
        try:
            result = fn(client, **fn_kwargs)
            _report_call_outcome(node_store, tenant_id, primary_node, success=True)
            return result, meta
        except LLMResponseError as exc:
            _report_call_outcome(
                node_store, tenant_id, primary_node,
                success=False, code=getattr(exc, "code", "other"),
            )
            logger.warning(
                "Role %s primary node failed: %s; falling back to default",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        except Exception as exc:
            _report_call_outcome(
                node_store, tenant_id, primary_node, success=False, code="other"
            )
            logger.warning(
                "Role %s primary node unexpected error: %s; falling back to default",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        finally:
            client.close()

    # ---- Fallback to default node ----
    fallback_node: dict | None = None
    if default_config is not None:
        fallback_config = default_config
    else:
        # Ticket #103: breaker-filtered selection (never re-aim at a node
        # the sweep just gave up on).
        fallback_node = usable_active_node(node_store, tenant_id)
        if fallback_node is None:
            meta["error"] = "No default node available for fallback"
            raise LLMResponseError(
                meta["error"], code=LlmFailureCode.HTTP
            )
        from ..models import ResuAlignConfig
        fallback_config = ResuAlignConfig(
            provider=fallback_node.get("provider", ""),
            model=fallback_node.get("model", ""),
            api_key=fallback_node.get("api_key", ""),
            base_url=fallback_node.get("base_url", ""),
            disable_thinking=bool(fallback_node.get("disable_thinking", False)),
        )
        meta["fallback_node_name"] = fallback_node.get("name", "")

    client = OpenAIClient(
        fallback_config,
        timeout=_role_timeout(role),
        max_tokens=_role_max_tokens(role),
        token_cap=_role_token_cap(role),
        deadline=_role_deadline(role),
        retry_transport=role in _RETRY_ON_TRANSPORT_ROLES,
    )
    try:
        result = fn(client, **fn_kwargs)
        _report_call_outcome(node_store, tenant_id, fallback_node, success=True)
        return result, meta
    except Exception as exc:
        _report_call_outcome(
            node_store, tenant_id, fallback_node,
            success=False, code=getattr(exc, "code", "other"),
        )
        meta["error"] = str(exc)[:200]
        raise
    finally:
        client.close()


def call_with_role_streaming(
    role: str,
    stream_or_fallback_fn: Any,
    node_store: LLMNodeStore,
    tenant_id: str,
    *,
    fn_kwargs: dict[str, Any] | None = None,
    idle_timeout: float = 15.0,
) -> tuple[Any, dict[str, Any]]:
    """Call a streaming function with role-appropriate LLM client + fallback.

    Resolves the role node, builds an ``OpenAIClient``, and calls
    ``stream_or_fallback_fn`` (which should accept ``client`` as its first
    argument plus any ``fn_kwargs``). On ``StreamConnectionError`` or
    ``LLMResponseError`` it falls back to the default node once.

    Returns ``(result, meta)`` where ``meta`` mirrors ``call_with_role``:
    ``role``, ``node_name``, ``model``, ``fallback_used``,
    ``fallback_node_name``, and ``error``.
    """
    fn_kwargs = dict(fn_kwargs or {})
    fn_kwargs.setdefault("idle_timeout", idle_timeout)
    meta: dict[str, Any] = {
        "role": role,
        "node_name": "",
        "model": "",
        "fallback_used": False,
        "fallback_node_name": None,
        "error": None,
    }

    # ---- Primary attempt with role node ----
    primary_node = node_store.resolve_node_for_role(tenant_id, role)
    resolved = _config_from_node(primary_node)
    if resolved is not None:
        from ..models import ResuAlignConfig
        primary_config = ResuAlignConfig(**resolved)
        meta["node_name"] = resolved.get("model", "")
        meta["model"] = resolved.get("model", "")
        client = OpenAIClient(primary_config, timeout=_role_timeout(role))
        try:
            result = stream_or_fallback_fn(client, **fn_kwargs)
            _report_call_outcome(node_store, tenant_id, primary_node, success=True)
            return result, meta
        except (StreamConnectionError, LLMResponseError) as exc:
            # A stalled stream is a transport-class failure; stream errors
            # without a structured code count as "other" (breaker-set
            # semantics, ticket #103).
            _report_call_outcome(
                node_store, tenant_id, primary_node,
                success=False, code=getattr(exc, "code", "other"),
            )
            logger.warning(
                "Role %s primary stream failed: %s; falling back to default",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        finally:
            client.close()

    # ---- Fallback to default node ----
    fallback_node = usable_active_node(node_store, tenant_id)
    if fallback_node is None:
        meta["error"] = "No default node available for fallback"
        raise LLMResponseError(
            meta["error"], code=LlmFailureCode.HTTP
        )
    from ..models import ResuAlignConfig
    fallback_config = ResuAlignConfig(
        provider=fallback_node.get("provider", ""),
        model=fallback_node.get("model", ""),
        api_key=fallback_node.get("api_key", ""),
        base_url=fallback_node.get("base_url", ""),
        disable_thinking=bool(fallback_node.get("disable_thinking", False)),
    )
    meta["fallback_node_name"] = fallback_node.get("name", "")

    client = OpenAIClient(fallback_config, timeout=_role_timeout(role))
    try:
        result = stream_or_fallback_fn(client, **fn_kwargs)
        _report_call_outcome(node_store, tenant_id, fallback_node, success=True)
        return result, meta
    except Exception as exc:
        _report_call_outcome(
            node_store, tenant_id, fallback_node,
            success=False, code=getattr(exc, "code", "other"),
        )
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
    Accepts any store exposing ``resolve_node_for_role`` (node-store fakes
    in tests included); locality is decided by ``LLMNodeStore._is_local_node``.
    """
    for role in roles:
        node = node_store.resolve_node_for_role(tenant_id, role)
        if LLMNodeStore._is_local_node(node):
            return False
    return True
