"""Operator endpoints: lightweight in-process metrics.

``/api/ops/metrics`` is registered with ``include_in_schema=False`` on
purpose: ops endpoints are not part of the public v1 API contract, so the
OpenAPI golden/current snapshots stay unchanged (see
docs/ticket-9-observability.md).
"""

import time

from fastapi import APIRouter

import resualign.api as api_module

from ...llm import llm_metrics_snapshot

router = APIRouter(tags=["ops"])

_STARTED_AT = time.monotonic()


@router.get("/api/ops/metrics", include_in_schema=False)
def metrics() -> dict:
    """Return lightweight JSON metrics about the analysis pipeline."""
    registry = api_module._registry
    outcomes = registry.outcome_stats()
    terminal = outcomes.get("succeeded", 0) + outcomes.get("failed", 0)
    return {
        "queue": {
            "depth": registry.queue_depth(),
            "oldest_waiting_seconds": registry.oldest_waiting_seconds(),
        },
        "jobs": {
            "by_status": outcomes,
            "failure_rate": (
                round(outcomes.get("failed", 0) / terminal, 4)
                if terminal
                else None
            ),
        },
        "llm": llm_metrics_snapshot(),
        "uptime_seconds": round(time.monotonic() - _STARTED_AT, 1),
    }
