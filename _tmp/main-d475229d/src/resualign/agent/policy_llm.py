"""LLM decision policy for JD intake blockers (ADR-0029 Phase A).

``LLMJdIntakePolicy`` implements the same duck-typed contract as
``JdIntakePolicy`` but asks the configured LLM for the keep/resolve decision
using a fixed prompt and a structured JSON schema. It is deliberately
conservative: the prompt forbids auto-resolving login/CAPTCHA/rule blockers
and requires pasted JD text before resolving a transient fetch failure.

The orchestrator owns degradation: when this policy raises (no API key,
invalid LLM output, network failure), ``_decide_blocker`` keeps the blocker
pending and logs ``agent.failure``.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import build_config
from ..llm import (
    LLMClient,
    LLMResponseError,
    OpenAIClient,
    _structured_or_json,
)
from ..schema_registry import JdIntakeDecisionSchema
from .orchestrator import ACTION_KEEP_PENDING, ACTION_RESOLVE

logger = logging.getLogger(__name__)

JD_INTAKE_POLICY_PROMPT = (
    "You are a conservative JD intake automation policy. A URL fetch failed "
    "and the system created a blocker. Decide whether the agent may "
    "auto-resolve it with pasted JD text or must keep it pending for a "
    "human.\n"
    "Rules:\n"
    "- Never auto-resolve login/CAPTCHA, invalid URL, or rule-rejected "
    "blockers.\n"
    "- Only resolve transient fetch failures (network_error, timeout, "
    "site_error, fetch_error, no_content) when pasted JD text is provided.\n"
    "- When in doubt, keep the blocker pending.\n"
    "Return JSON with \"action\" (keep_pending or resolve) and a short "
    "\"reason\". Output ONLY JSON."
)

_JD_INTAKE_POLICY_TIMEOUT = 30.0
_MAX_RESOLVE_TEXT_CHARS = 2000


class LLMJdIntakePolicy:
    """LLM-backed keep/resolve policy for one blocked JD fetch."""

    max_agent_rounds = 1

    def __init__(self, client: LLMClient | None = None):
        self._client = client

    def decide(self, blocker: dict[str, Any], resolve_text: str = "") -> str:
        user = self._user_prompt(blocker, resolve_text)
        if self._client is not None:
            result = _structured_or_json(
                self._client,
                JD_INTAKE_POLICY_PROMPT,
                user,
                JdIntakeDecisionSchema,
            )
        else:
            config = build_config()
            if not config.is_llm_configured:
                raise LLMResponseError(
                    "LLM not configured for the JD intake policy"
                )
            with OpenAIClient(
                config, timeout=_JD_INTAKE_POLICY_TIMEOUT
            ) as client:
                result = _structured_or_json(
                    client,
                    JD_INTAKE_POLICY_PROMPT,
                    user,
                    JdIntakeDecisionSchema,
                )
        action = (result or {}).get("action") or ACTION_KEEP_PENDING
        if action not in (ACTION_KEEP_PENDING, ACTION_RESOLVE):
            raise LLMResponseError(
                f"LLM JD intake policy returned invalid action: {action!r}"
            )
        if action == ACTION_RESOLVE and not (resolve_text or "").strip():
            return ACTION_KEEP_PENDING
        return action

    @staticmethod
    def _user_prompt(
        blocker: dict[str, Any], resolve_text: str
    ) -> str:
        snippet = (resolve_text or "").strip()
        if len(snippet) > _MAX_RESOLVE_TEXT_CHARS:
            snippet = snippet[:_MAX_RESOLVE_TEXT_CHARS] + " [truncated]"
        payload: dict[str, Any] = {
            "blocker_id": blocker.get("blocker_id"),
            "url": blocker.get("url"),
            "category": blocker.get("category"),
            "reason": blocker.get("reason"),
            "has_pasted_jd_text": bool(snippet),
        }
        if snippet:
            payload["pasted_jd_text_preview"] = snippet
        return (
            "Blocker:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
