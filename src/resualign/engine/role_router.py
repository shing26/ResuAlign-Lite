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
import time
from typing import Any

from ..contracts.errors import LlmFailureCode
from .llm import LLMResponseError, OpenAIClient, StreamConnectionError
from .llm_nodes import LLMNodeStore

logger = logging.getLogger(__name__)

# Module 8: process-local cooldown. After a node fails with timeout
# (connection error, stalled stream), skip it for 60s in the same process.
# 5xx/http (e.g. 503) do NOT trigger cooldown: they are instant responses,
# so the breaker tally must keep counting them toward auto-disable.
# auth/quota (config problems) and parse/schema/empty (model output
# problems) do NOT trigger cooldown; those need a node switch or a retry.
_NODE_COOLDOWN_SECONDS = 60.0
_NODE_COOLDOWN: dict[tuple[str, str], float] = {}
_COOLDOWN_CODES = frozenset({"timeout"})


def _node_cooldown_key(tenant_id: str, node_id: str) -> tuple[str, str]:
    return (tenant_id, node_id)


def _is_node_cooled_down(tenant_id: str, node_id: str) -> bool:
    """Return True if the node is in cooldown (skip it)."""
    key = _node_cooldown_key(tenant_id, node_id)
    expires_at = _NODE_COOLDOWN.get(key)
    if expires_at is None:
        return False
    if time.monotonic() >= expires_at:
        # Cooldown expired; clean up.
        _NODE_COOLDOWN.pop(key, None)
        return False
    return True


def _cool_down_node(tenant_id: str, node_id: str) -> None:
    """Put a node into cooldown for _NODE_COOLDOWN_SECONDS."""
    key = _node_cooldown_key(tenant_id, node_id)
    _NODE_COOLDOWN[key] = time.monotonic() + _NODE_COOLDOWN_SECONDS


def _should_cool_down(code: str | None) -> bool:
    """Return True if the failure code triggers cooldown."""
    return code in _COOLDOWN_CODES


def clear_node_cooldown() -> None:
    """Clear all cooldowns (for tests)."""
    _NODE_COOLDOWN.clear()

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

    P0: multi-active failover — returns first usable node (local first).
    Callers that need failover should use ``usable_active_nodes`` instead.

    Module 8: skip nodes in process-local cooldown (timeout/http failures).
    A cooled-down node is skipped in favour of the next healthy usable
    node, so a flapping first node does not make the whole tenant look
    node-less while healthy nodes exist behind it.
    """
    usable = getattr(node_store, "get_usable_node", None)
    node = usable(tenant_id) if callable(usable) else None
    if node and not _is_node_cooled_down(tenant_id, node.get("node_id", "")):
        return node
    # The single-node answer is cooled down (or absent): fall back to the
    # full list so the next healthy usable node is served instead of
    # reporting "no node at all" while healthy nodes exist.
    nodes = getattr(node_store, "get_usable_nodes", None)
    if callable(nodes):
        for candidate in nodes(tenant_id):
            if candidate and not _is_node_cooled_down(
                tenant_id, candidate.get("node_id", "")
            ):
                return candidate
        return None
    active = getattr(node_store, "get_active_node", None)
    node = active(tenant_id) if callable(active) else None
    if node and _is_node_cooled_down(tenant_id, node.get("node_id", "")):
        return None
    return node


def usable_active_nodes(node_store: Any, tenant_id: str) -> list[dict]:
    """All usable nodes for failover (P0 multi-active).

    Returns nodes sorted by priority: local first, then remote. Empty list
    when no node is usable. Duck-typed for node-store fakes.
    """
    usable = getattr(node_store, "get_usable_nodes", None)
    if callable(usable):
        return usable(tenant_id)
    # Fallback for stores without multi-node support
    single = usable_active_node(node_store, tenant_id)
    return [single] if single else []


def _fallback_candidates(
    node_store: Any,
    tenant_id: str,
    primary_node: dict | None,
    default_config: Any = None,
) -> list[tuple[dict | None, Any]]:
    """Return fallback candidates after the primary attempt.

    An explicit ``default_config`` is the only fallback when supplied.
    Otherwise every usable node except the primary is tried in priority
    order, so a failed primary is never immediately re-aimed at itself.
    """
    if default_config is not None:
        return [(None, default_config)]

    primary_id = (primary_node or {}).get("node_id")
    seen: set[str] = {primary_id} if primary_id else set()
    candidates: list[tuple[dict | None, Any]] = []
    for node in usable_active_nodes(node_store, tenant_id):
        if node is primary_node:
            continue
        node_id = node.get("node_id")
        if node_id and node_id in seen:
            continue
        # Module 8: skip cooled-down nodes in the fallback chain too.
        if node_id and _is_node_cooled_down(tenant_id, node_id):
            continue
        if node_id:
            seen.add(node_id)
        candidates.append((node, None))
    return candidates


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
    any ``fn_kwargs``. On ``LLMResponseError`` (after the client's internal
    retries), it falls back through the remaining usable nodes in priority
    order. An explicit ``default_config`` is the only fallback in that case.

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
    # Module 8: a cooled-down node must not be re-aimed as the primary —
    # skip the first attempt entirely and go straight to the fallback
    # nodes instead of paying a full timeout on a node that just failed.
    if primary_node and _is_node_cooled_down(
        tenant_id, primary_node.get("node_id", "")
    ):
        primary_node = None
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
            # Module 8: cooldown on timeout failures (5xx/http do not trigger).
            code = getattr(exc, "code", "other")
            if _should_cool_down(code) and primary_node:
                _cool_down_node(tenant_id, primary_node.get("node_id", ""))
            _report_call_outcome(
                node_store, tenant_id, primary_node,
                success=False, code=code,
            )
            logger.warning(
                "Role %s primary node failed: %s; trying fallback nodes",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        except Exception as exc:
            # Module 8: cooldown on unexpected errors (treated as timeout —
            # connection failures and stalled transports are the cooldown's
            # core scenario).
            if primary_node:
                _cool_down_node(tenant_id, primary_node.get("node_id", ""))
            _report_call_outcome(
                node_store, tenant_id, primary_node, success=False, code="other"
            )
            logger.warning(
                "Role %s primary node unexpected error: %s; trying fallback nodes",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        finally:
            client.close()

    # ---- Fallback through the remaining usable nodes ----
    candidates = _fallback_candidates(
        node_store, tenant_id, primary_node, default_config
    )
    if not candidates:
        meta["error"] = "No default node available for fallback"
        raise LLMResponseError(meta["error"], code=LlmFailureCode.HTTP)

    last_exc: Exception | None = None
    for index, (fallback_node, explicit_config) in enumerate(candidates):
        # Module 8: a cooled-down primary (primary_node=None) still counts
        # as fallback — the fallback node took over the call.
        meta["fallback_used"] = True

        if fallback_node is not None:
            from ..models import ResuAlignConfig
            fallback_config = ResuAlignConfig(
                provider=fallback_node.get("provider", ""),
                model=fallback_node.get("model", ""),
                api_key=fallback_node.get("api_key", ""),
                base_url=fallback_node.get("base_url", ""),
                disable_thinking=bool(
                    fallback_node.get("disable_thinking", False)
                ),
            )
            meta["fallback_node_name"] = fallback_node.get("name", "")
        else:
            fallback_config = explicit_config

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
            _report_call_outcome(
                node_store, tenant_id, fallback_node, success=True
            )
            return result, meta
        except Exception as exc:
            _report_call_outcome(
                node_store, tenant_id, fallback_node,
                success=False, code=getattr(exc, "code", "other"),
            )
            meta["error"] = str(exc)[:200]
            last_exc = exc
        finally:
            client.close()

    if last_exc is not None:
        raise last_exc
    raise LLMResponseError(meta["error"] or "No fallback node succeeded")


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
    ``LLMResponseError`` it falls back through the remaining usable nodes
    in priority order.

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
    # Module 8: skip a cooled-down primary (same contract as call_with_role).
    if primary_node and _is_node_cooled_down(
        tenant_id, primary_node.get("node_id", "")
    ):
        primary_node = None
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
            # Module 8: cooldown on transport-class failures — a stalled
            # stream counts as timeout, LLMResponseError carries its code.
            code = getattr(exc, "code", "") or (
                LlmFailureCode.TIMEOUT.value
                if isinstance(exc, StreamConnectionError)
                else ""
            )
            if _should_cool_down(code) and primary_node:
                _cool_down_node(tenant_id, primary_node.get("node_id", ""))
            _report_call_outcome(
                node_store, tenant_id, primary_node,
                success=False, code=code or "other",
            )
            logger.warning(
                "Role %s primary stream failed: %s; trying fallback nodes",
                role, exc,
            )
            meta["error"] = str(exc)[:200]
            meta["fallback_used"] = True
        finally:
            client.close()

    # ---- Fallback through the remaining usable nodes ----
    candidates = _fallback_candidates(node_store, tenant_id, primary_node)
    if not candidates:
        meta["error"] = "No default node available for fallback"
        raise LLMResponseError(meta["error"], code=LlmFailureCode.HTTP)

    last_exc: Exception | None = None
    for index, (fallback_node, _) in enumerate(candidates):
        # Module 8: a cooled-down primary (primary_node=None) still counts
        # as fallback — the fallback node took over the call.
        meta["fallback_used"] = True

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
            _report_call_outcome(
                node_store, tenant_id, fallback_node, success=True
            )
            return result, meta
        except Exception as exc:
            _report_call_outcome(
                node_store, tenant_id, fallback_node,
                success=False, code=getattr(exc, "code", "other"),
            )
            meta["error"] = str(exc)[:200]
            last_exc = exc
        finally:
            client.close()

    if last_exc is not None:
        raise last_exc
    raise LLMResponseError(meta["error"] or "No fallback node succeeded")


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
