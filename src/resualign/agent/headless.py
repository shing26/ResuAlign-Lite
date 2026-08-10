"""Headless daemon for agent-native operation.

``run_headless`` starts the FastAPI application in a background thread
(optional, ``start_server``) and then loops forever (or for ``max_rounds``),
polling two workloads per round:

1. **Pending blockers** - classify each pending blocker and log the policy
   disposition. Rule-rejected blockers are expected outcomes (logged,
   kept pending for human review); login/CAPTCHA blockers need a browser or
   human; transient network blockers stay pending for a manual/HITL retry.
   The daemon never auto-resolves a blocker (that requires human pasted JD
   text via ``resolve_blocker``).

2. **Alignment candidates** - library jobs whose alignment is not terminal
   and not already in flight (``idle``/``failed``) get queued through the
   same ``auto_align_resume`` path as the MCP tool, so the agent can keep a
   resume aligned with every new JD without a web frontend.

The daemon is deliberately decoupled from the frontend: it runs its own
poll loop and never mounts or depends on ``static/``.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import resualign.api as api_module

from .mcp_server import DEFAULT_TENANT, auto_align_resume

logger = logging.getLogger(__name__)

# Blocker categories that a human (or browser session) must clear; the
# daemon only logs them and keeps them pending.
_SKIP_BLOCKER_CATEGORIES = {
    "rule_rejected": "blocked by an automation rule; keep pending for human review",
    "login_required": "needs a login; requires a human or browser session",
    "captcha": "needs CAPTCHA; requires a human",
    "invalid_url": "invalid URL; needs human input",
}

# Transient network failures: the daemon keeps them pending so a human or a
# later HITL-triggered retry can clear them.
_RETRYABLE_BLOCKER_CATEGORIES = {
    "network_error",
    "timeout",
    "site_error",
    "fetch_error",
    "no_content",
}

# Non-terminal alignment states the daemon may auto-queue. ``queued`` /
# ``running`` are in-flight (the registry owns them), ``succeeded`` is
# terminal, so only ``idle`` and ``failed`` are candidates.
_ALIGN_CANDIDATE_STATES = ("idle", "failed")


def _resolve_host_port() -> tuple[str, int]:
    host = os.environ.get("RESUALIGN_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("RESUALIGN_PORT", "8000"))
    except (TypeError, ValueError):
        port = 8000
    return host, port


def _is_port_open(host: str, port: int) -> bool:
    """Return True when something already binds ``host:port``.

    Uses a bind probe (not a connect probe): a connect can time out when the
    existing listener is on a different interface, while a failed bind is an
    unambiguous "address already in use" signal on every platform.
    """
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def _start_server() -> None:
    """Start the FastAPI app on a daemon uvicorn thread.

    Skips when the port is already bound (the API is running elsewhere), and
    failures are logged, never raised: the daemon loop must keep running even
    if the web server cannot start.
    """
    host, port = _resolve_host_port()
    if _is_port_open(host, port):
        logger.info(
            "Headless daemon: FastAPI already listening on %s:%s; "
            "reusing the running server",
            host,
            port,
        )
        return

    def _serve() -> None:
        import uvicorn

        try:
            uvicorn.run(
                "resualign.api:app",
                host=host,
                port=port,
                reload=False,
                log_level="warning",
            )
        except BaseException:  # noqa: BLE001 - a background server failure
            # (bind errors surface as SystemExit from uvicorn) must never
            # propagate as an unhandled thread exception
            logger.exception(
                "Headless daemon: FastAPI server on %s:%s failed to serve",
                host,
                port,
            )

    threading.Thread(target=_serve, daemon=True).start()
    logger.info("Headless daemon started FastAPI on http://%s:%s", host, port)


def _handle_blocker(tenant_id: str, blocker: dict[str, Any]) -> None:
    """Apply the daemon's blocker policy to one pending blocker."""
    category = blocker.get("category") or "fetch_error"
    reason = blocker.get("reason")
    if category in _SKIP_BLOCKER_CATEGORIES:
        logger.info(
            "Headless: keep blocker %s pending (%s): %s",
            blocker["blocker_id"],
            category,
            _SKIP_BLOCKER_CATEGORIES[category],
        )
        return
    if category in _RETRYABLE_BLOCKER_CATEGORIES:
        logger.info(
            "Headless: blocker %s is transient (%s): %s - keeping pending "
            "for manual/HITL retry",
            blocker["blocker_id"],
            category,
            reason,
        )
        return
    logger.warning(
        "Headless: unknown blocker category %s for %s (%s)",
        category,
        blocker["blocker_id"],
        reason,
    )


def _alignment_auto_candidates(tenant_id: str) -> list[dict[str, Any]]:
    """Return library jobs the daemon may auto-align this round.

    A job qualifies when its alignment is ``idle``/``failed``, it has JD
    text, and its pinned analysis job (if any) is not still in flight or
    already succeeded - guards against double-queueing while the registry
    job is queued/running.
    """
    jobs = api_module._jobs.list_jobs(tenant_id)
    candidates: list[dict[str, Any]] = []
    for job in jobs:
        if job.get("alignment_status") not in _ALIGN_CANDIDATE_STATES:
            continue
        if not (job.get("jd_text") or "").strip():
            continue
        pinned = job.get("workbench_job_id")
        if pinned:
            snapshot = api_module._registry.snapshot(
                pinned, tenant_id=tenant_id
            )
            if snapshot and snapshot.get("status") in (
                "queued",
                "running",
                "succeeded",
            ):
                continue
        candidates.append(job)
    return candidates


def run_headless_round(tenant_id: str = DEFAULT_TENANT) -> dict[str, Any]:
    """Run one daemon round: classify blockers + queue alignment candidates.

    Returns a small stats dict for logging/tests. Never raises: individual
    blocker/job failures are caught per-item.
    """
    stats: dict[str, Any] = {
        "blockers_seen": 0,
        "align_candidates": 0,
        "align_queued": 0,
    }
    blockers = api_module._jobs.list_blockers(tenant_id, status="pending")
    stats["blockers_seen"] = len(blockers)
    for blocker in blockers:
        try:
            _handle_blocker(tenant_id, blocker)
        except Exception:  # noqa: BLE001 - one bad blocker never kills the round
            logger.exception(
                "Headless: failed to classify blocker %s",
                blocker.get("blocker_id"),
            )

    candidates = _alignment_auto_candidates(tenant_id)
    stats["align_candidates"] = len(candidates)
    for job in candidates:
        try:
            result = auto_align_resume(
                job_id=job["job_id"],
                master_resume_id=job.get("workbench_resume_id"),
                tenant_id=tenant_id,
            )
        except Exception:  # noqa: BLE001 - one bad job never kills the round
            logger.exception(
                "Headless: auto-align failed for job %s", job["job_id"]
            )
            continue
        if result.get("status") == "queued":
            stats["align_queued"] += 1
            logger.info(
                "Headless: queued alignment %s for job %s",
                result.get("analysis_job_id"),
                job["job_id"],
            )
        else:
            logger.info(
                "Headless: skip auto-align job %s: %s",
                job["job_id"],
                result.get("error") or result.get("status"),
            )
    return stats


def run_headless(
    interval: float = 30,
    tenant_id: str = DEFAULT_TENANT,
    start_server: bool = True,
    once: bool = False,
    max_rounds: int | None = None,
) -> dict[str, Any]:
    """Run the headless daemon: optional background API + poll loop.

    ``once=True`` (or ``max_rounds=1``) runs a single poll round and returns
    its stats, which is how tests and one-shot invocations drive the daemon.
    ``max_rounds`` bounds the loop for one-shot runs (``None`` loops forever
    unless ``once`` is set). ``start_server=False`` skips the background
    uvicorn thread so unit tests never bind a port.

    Returns the stats of the last executed round (``{}`` when no round ran).
    """
    if start_server:
        _start_server()
    limit = 1 if once else max_rounds
    rounds = 0
    last_stats: dict[str, Any] = {}
    while limit is None or rounds < limit:
        rounds += 1
        try:
            stats = run_headless_round(tenant_id)
            last_stats = stats
            logger.info("Headless round %d: %s", rounds, stats)
        except Exception:  # noqa: BLE001 - the daemon never dies on one round
            logger.exception("Headless round %d failed", rounds)
        if limit is not None and rounds >= limit:
            break
        time.sleep(max(0.0, float(interval)))
    return last_stats
