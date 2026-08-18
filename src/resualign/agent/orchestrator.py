"""Minimal JD intake orchestrator (ADR-0029 Phase A).

The orchestrator is the agent loop that drives the existing MCP tools
(``fetch_and_evaluate_job`` / ``get_pending_blockers`` / ``resolve_blocker``)
instead of touching stores, API internals, or the engine directly.

Budget and degradation follow ADR-0029:

- one fetch plus at most one agent decision round per URL by default;
- tool failures and unexpected results degrade to the existing blocker path
  (the blocker stays pending for the headless daemon / web UI / human);
- every decision/failure/budget event lands in structured observability logs
  (``agent.decision`` / ``agent.failure`` / ``agent.budget_exceeded``).

``JdIntakePolicy`` is the decision seam. Phase A ships a conservative
deterministic policy; a later LLM policy can implement the same interface
without changing the loop or the tool contract.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from ..observability import log_event
from .mcp_server import DEFAULT_TENANT

logger = logging.getLogger(__name__)

ACTION_KEEP_PENDING = "keep_pending"
ACTION_RESOLVE = "resolve"
_ALLOWED_ACTIONS = frozenset({ACTION_KEEP_PENDING, ACTION_RESOLVE})

# Categories that need a human/browser even when pasted JD text is available.
_HUMAN_BLOCKER_CATEGORIES = frozenset(
    {"invalid_url", "rule_rejected", "login_required", "captcha"}
)
# Transient fetch failures: the policy may auto-resolve them with pasted text.
_RETRYABLE_BLOCKER_CATEGORIES = frozenset(
    {"network_error", "timeout", "site_error", "fetch_error", "no_content"}
)


class JdIntakePolicyLike(Protocol):
    """Duck-typed policy contract used by the orchestrator loop."""

    max_agent_rounds: int

    def decide(self, blocker: dict[str, Any], resolve_text: str = "") -> str:
        ...


@dataclass(frozen=True)
class JdIntakePolicy:
    """Decision policy for one blocked JD fetch (one decision round per URL)."""

    max_agent_rounds: int = 1
    keep_pending_categories: frozenset[str] = _HUMAN_BLOCKER_CATEGORIES
    resolve_categories: frozenset[str] = _RETRYABLE_BLOCKER_CATEGORIES

    def decide(self, blocker: dict[str, Any], resolve_text: str = "") -> str:
        """Return ``resolve`` only when the category is retryable and text exists."""
        category = blocker.get("category") or "fetch_error"
        if category in self.keep_pending_categories:
            return ACTION_KEEP_PENDING
        if category in self.resolve_categories and (resolve_text or "").strip():
            return ACTION_RESOLVE
        return ACTION_KEEP_PENDING


@dataclass(frozen=True)
class JdIntakeTools:
    """MCP tool contract for the JD intake agent."""

    fetch: Callable[[str, str], dict[str, Any]]
    pending_blockers: Callable[[str], list[dict[str, Any]]]
    resolve: Callable[[str, str, str], dict[str, Any]]

    @classmethod
    def default(cls) -> "JdIntakeTools":
        from .mcp_server import (
            fetch_and_evaluate_job,
            get_pending_blockers,
            resolve_blocker,
        )

        return cls(
            fetch=fetch_and_evaluate_job,
            pending_blockers=get_pending_blockers,
            resolve=resolve_blocker,
        )


def _log(emitter: Callable[..., None], event: str, extra: dict[str, Any]) -> None:
    emitter(logger, event, extra=extra)


def _blocked_result(
    blocker: dict[str, Any],
    rounds: int,
    tool_calls: int,
    action: str,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "blocked",
        "url": blocker.get("url"),
        "blocker_id": blocker.get("blocker_id"),
        "category": blocker.get("category"),
        "reason": blocker.get("reason"),
        "rule_type": blocker.get("rule_type"),
        "agent_rounds": rounds,
        "tool_calls": tool_calls,
        "action": action,
        "budget_exceeded": False,
    }
    if error is not None:
        result["error"] = error
    return result


def _decide_blocker(
    blocker: dict[str, Any],
    tenant_id: str,
    *,
    resolve_text: str,
    policy: JdIntakePolicyLike,
    tools: JdIntakeTools,
    emitter: Callable[..., None],
    tool_calls: int = 0,
) -> tuple[dict[str, Any], int]:
    """Run the single permitted agent decision round for one blocker."""
    rounds = 1
    blocker_id = blocker.get("blocker_id")
    url = blocker.get("url") or ""
    try:
        action = policy.decide(blocker, resolve_text)
    except Exception as exc:  # noqa: BLE001 - a bad policy must not crash the loop
        error = str(exc)[:300]
        _log(
            emitter,
            "agent.failure",
            {
                "task": "jd_intake",
                "url": url,
                "blocker_id": blocker_id,
                "reason": "policy decision failed",
                "error": error,
            },
        )
        return (
            _blocked_result(
                blocker, rounds, tool_calls, "keep_pending", error=error
            ),
            tool_calls,
        )

    if action == ACTION_RESOLVE and not (resolve_text or "").strip():
        # Deterministic guard: never auto-resolve without pasted JD text.
        action = ACTION_KEEP_PENDING

    if action == ACTION_RESOLVE:
        try:
            tool_calls += 1
            resolved = tools.resolve(blocker_id, resolve_text, tenant_id)
        except Exception as exc:  # noqa: BLE001 - one failed resolve stays pending
            error = str(exc)[:300]
            _log(
                emitter,
                "agent.failure",
                {
                    "task": "jd_intake",
                    "url": url,
                    "blocker_id": blocker_id,
                    "reason": "resolve tool raised",
                    "error": error,
                },
            )
            return (
                _blocked_result(
                    blocker, rounds, tool_calls, "resolve_failed", error=error
                ),
                tool_calls,
            )
        if resolved.get("status") == "resolved":
            _log(
                emitter,
                "agent.decision",
                {
                    "task": "jd_intake",
                    "url": url,
                    "blocker_id": blocker_id,
                    "action": "resolve",
                    "status": "resolved",
                    "job_id": resolved.get("job_id"),
                    "agent_rounds": rounds,
                    "tool_calls": tool_calls,
                },
            )
            return (
                {
                    "status": "resolved",
                    "url": url,
                    "blocker_id": blocker_id,
                    "job_id": resolved.get("job_id"),
                    "agent_rounds": rounds,
                    "tool_calls": tool_calls,
                    "budget_exceeded": False,
                },
                tool_calls,
            )
        error = resolved.get("error") or resolved.get("status") or "resolve failed"
        _log(
            emitter,
            "agent.failure",
            {
                "task": "jd_intake",
                "url": url,
                "blocker_id": blocker_id,
                "reason": "resolve tool rejected",
                "error": str(error)[:300],
            },
        )
        return (
            _blocked_result(
                blocker, rounds, tool_calls, "resolve_failed", error=str(error)[:300]
            ),
            tool_calls,
        )

    if action != ACTION_KEEP_PENDING:
        error = f"invalid policy action {action!r}"
        _log(
            emitter,
            "agent.failure",
            {
                "task": "jd_intake",
                "url": url,
                "blocker_id": blocker_id,
                "reason": "policy returned an invalid action",
                "error": error,
            },
        )
        return (
            _blocked_result(blocker, rounds, tool_calls, "keep_pending", error=error),
            tool_calls,
        )

    _log(
        emitter,
        "agent.decision",
        {
            "task": "jd_intake",
            "url": url,
            "blocker_id": blocker_id,
            "action": "keep_pending",
            "status": "blocked",
            "reason": blocker.get("reason"),
            "agent_rounds": rounds,
            "tool_calls": tool_calls,
        },
    )
    return _blocked_result(blocker, rounds, tool_calls, "keep_pending"), tool_calls


def run_jd_intake(
    url: str,
    tenant_id: str = DEFAULT_TENANT,
    *,
    resolve_text: str = "",
    policy: JdIntakePolicyLike | None = None,
    tools: JdIntakeTools | None = None,
    emit: Callable[..., None] | None = None,
) -> dict[str, Any]:
    """Run one JD intake task: fetch once, then one bounded decision round.

    Returns one of:

    - ``created`` / ``duplicate``: accepted into the library (or already there)
    - ``blocked``: the blocker stays pending (keep_pending / resolve_failed)
    - ``resolved``: a pasted JD text replaced the blocked fetch
    - ``degraded``: the tool/policy failed or the agent budget was exceeded
    """
    policy = policy or JdIntakePolicy()
    tools = tools or JdIntakeTools.default()
    emitter = emit or log_event
    tool_calls = 0

    try:
        tool_calls += 1
        result = tools.fetch(url, tenant_id)
    except Exception as exc:  # noqa: BLE001 - agent failures degrade, never raise
        error = str(exc)[:300]
        _log(
            emitter,
            "agent.failure",
            {
                "task": "jd_intake",
                "url": url,
                "reason": "fetch tool raised",
                "error": error,
            },
        )
        return {
            "status": "degraded",
            "url": url,
            "reason": "fetch tool raised",
            "error": error,
            "agent_rounds": 0,
            "tool_calls": tool_calls,
            "budget_exceeded": False,
        }

    status = result.get("status")
    if status in ("created", "duplicate"):
        _log(
            emitter,
            "agent.decision",
            {
                "task": "jd_intake",
                "url": url,
                "action": "accept",
                "status": status,
                "job_id": result.get("job_id"),
                "agent_rounds": 0,
                "tool_calls": tool_calls,
            },
        )
        return {
            "status": status,
            "url": url,
            "job_id": result.get("job_id"),
            "reason": result.get("reason"),
            "agent_rounds": 0,
            "tool_calls": tool_calls,
            "budget_exceeded": False,
        }

    blocker = {
        "blocker_id": result.get("blocker_id"),
        "url": result.get("url") or url,
        "reason": result.get("reason"),
        "category": result.get("category") or "fetch_error",
        "rule_type": result.get("rule_type"),
    }
    if status not in ("blocked", "rule_rejected"):
        reason = f"unexpected fetch tool status {status!r}"
        _log(
            emitter,
            "agent.failure",
            {
                "task": "jd_intake",
                "url": url,
                "reason": "fetch tool returned an unexpected status",
                "error": reason,
            },
        )
        return {
            "status": "degraded",
            "url": url,
            "reason": reason,
            "blocker_id": blocker.get("blocker_id"),
            "agent_rounds": 0,
            "tool_calls": tool_calls,
            "budget_exceeded": False,
        }

    if policy.max_agent_rounds <= 0:
        _log(
            emitter,
            "agent.budget_exceeded",
            {
                "task": "jd_intake",
                "url": url,
                "blocker_id": blocker.get("blocker_id"),
                "max_agent_rounds": policy.max_agent_rounds,
            },
        )
        return {
            "status": "degraded",
            "url": url,
            "reason": "agent decision budget exceeded",
            "blocker_id": blocker.get("blocker_id"),
            "agent_rounds": 0,
            "tool_calls": tool_calls,
            "budget_exceeded": True,
        }

    result, tool_calls = _decide_blocker(
        blocker,
        tenant_id,
        resolve_text=resolve_text,
        policy=policy,
        tools=tools,
        emitter=emitter,
        tool_calls=tool_calls,
    )
    return result


def process_pending_blockers(
    tenant_id: str = DEFAULT_TENANT,
    *,
    resolve_texts: Mapping[str, str] | None = None,
    policy: JdIntakePolicyLike | None = None,
    tools: JdIntakeTools | None = None,
    emit: Callable[..., None] | None = None,
    max_blockers: int | None = None,
) -> dict[str, Any]:
    """Run one agent decision round per pending blocker (queue-driven mode).

    ``resolve_texts`` maps blocker_id -> pasted JD text; blockers without
    text (or in human-only categories) stay pending. Returns aggregate stats
    in the same compact shape as the headless daemon round.
    """
    policy = policy or JdIntakePolicy()
    tools = tools or JdIntakeTools.default()
    emitter = emit or log_event
    resolve_texts = dict(resolve_texts or {})

    pending = tools.pending_blockers(tenant_id)
    if max_blockers is not None:
        pending = pending[: max(0, int(max_blockers))]

    stats: dict[str, Any] = {
        "blockers_seen": len(pending),
        "blocker_decisions": 0,
        "blocked": 0,
        "resolved": 0,
        "degraded": 0,
    }
    if policy.max_agent_rounds <= 0:
        for blocker in pending:
            _log(
                emitter,
                "agent.budget_exceeded",
                {
                    "task": "jd_intake",
                    "url": blocker.get("url") or "",
                    "blocker_id": blocker.get("blocker_id"),
                    "max_agent_rounds": policy.max_agent_rounds,
                },
            )
        stats["degraded"] = len(pending)
        return stats

    for blocker in pending:
        blocker_id = blocker.get("blocker_id")
        result, _ = _decide_blocker(
            blocker,
            tenant_id,
            resolve_text=resolve_texts.get(blocker_id, ""),
            policy=policy,
            tools=tools,
            emitter=emitter,
        )
        stats["blocker_decisions"] += 1
        stats[result["status"]] += 1
    return stats
