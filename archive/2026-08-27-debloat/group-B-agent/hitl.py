"""Human-in-the-loop callbacks for agent-native integrations.

``emit_hitl_event`` is the single fan-out point for events the agent layer
wants a human (or an external orchestrator) to see:

- ``blocker.created``            a URL fetch hit a blocker the agent could
                                 not clear on its own (payload:
                                 ``{blocker_id, url, reason, category}``)
- ``alignment.low_confidence``   a produced diff carries low confidence and
                                 deserves human review (payload:
                                 ``{job_id, diff_index, confidence}``)

When ``RESUALIGN_WEBHOOK_URL`` is set, the event is POSTed as JSON to that
URL with a 5s timeout. Failures are logged and swallowed: the webhook must
never break the calling pipeline. Without a URL, the event is written
through the package's structured ``log_event`` helper so it still lands in
the app log.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..observability import log_event

logger = logging.getLogger(__name__)

_WEBHOOK_ENV = "RESUALIGN_WEBHOOK_URL"
_WEBHOOK_TIMEOUT = 5.0


def _get_webhook_url() -> str:
    """Return the configured HITL webhook URL, or ``""`` when disabled."""
    return (os.environ.get(_WEBHOOK_ENV) or "").strip()


def emit_hitl_event(event: str, payload: dict[str, Any]) -> None:
    """Fan out one HITL event to the configured webhook or the app log.

    Never raises: webhook delivery failures are logged at warning level and
    the caller's main flow continues.
    """
    url = _get_webhook_url()
    body: dict[str, Any] = {"event": event, "payload": payload}
    if not url:
        log_event(logger, event, extra=payload)
        return
    try:
        httpx.post(url, json=body, timeout=_WEBHOOK_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - webhook must not break the flow
        logger.warning(
            "HITL webhook %s failed for event %s: %s", url, event, exc
        )
