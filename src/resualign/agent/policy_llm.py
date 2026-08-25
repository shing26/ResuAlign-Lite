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

JD_INTAKE_POLICY_PROMPT = """PROMPT_VERSION: intake_policy/v2

你是保守的 JD 入库自动化策略。一次 URL 抓取失败并生成了 blocker。你的唯一决策：允许 agent 用「已粘贴的 JD 文本」自动 resolve，还是保持 pending 交给人工。

## 决策规则（按类别判断，先读 blocker.category）
1. 以下类别一律 keep_pending，禁止自动 resolve（与是否粘贴文本无关）：
   captcha、login_required、invalid_url、rule_rejected、parse_error、no_content（无粘贴文本时）；
2. 仅当「粘贴的 JD 文本」存在（has_pasted_jd_text=true）时才可 resolve 以下瞬时抓取类：
   network_error、fetch_error、timeout、site_error、no_content（有粘贴文本时）；
3. 任何不确定、类别缺失或不符合以上条件的情况：keep_pending。

## Output Contract（只能输出一个 JSON 对象，2 个字段）
键名固定为：action / reason

- action："keep_pending" 或 "resolve"，必须逐字使用这两个枚举值之一。
- reason：≤ 12 个英文词或 ≤ 20 个汉字，只写关键依据（blocker 类别 + 是否可 resolve），不解释流程。

## 提交前自查
- action 逐字是枚举值；reason 在上限内；
- 只输出 JSON，无 markdown fence，无解释文字。"""

# 运行时版本标记（2026-08-25 新增）。decide() 走 _structured_or_json +
# JdIntakeDecisionSchema；代码侧 resolve-and-no-text 双保险（:88-89）不动。
JD_INTAKE_POLICY_PROMPT_VERSION = "v2"

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
                config,
                timeout=_JD_INTAKE_POLICY_TIMEOUT,
                # R4 P0-2：intake 非 role 直连调用，输出钳制 64（03-AIE §③）。
                max_tokens=64,
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
