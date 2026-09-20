"""Running-job watchdog (ticket #102 / plan §3).

A stuck worker can leave a job in ``running`` forever — the startup requeue
only helps after a restart. This watchdog sweeps periodically and moves
timed-out ``running`` rows to the EXISTING failed terminal state via
``JobRegistry.fail`` (conditional UPDATE: if the hung thread ever wakes and
tries to write, its late succeed/fail is a no-op and never overwrites).

Deliberate boundary (grilling decision): we only fix DB/board state. A truly
hung thread still holds its per-tenant run gate, so that tenant's next job
stays queued until the thread releases or the process restarts — same as
today, but now with honest state and a rerunnable board. Killing threads is
not possible safely in Python, and gate timeout would create a second
failure path; both deferred.

Cap semantics: no heartbeat column exists, so staleness is judged purely
against the task-level wall clock (``started_at`` + cap).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from ...app.context import context
from ...observability import log_event

logger = logging.getLogger("resualign.api.watchdog")

DEFAULT_MAX_RUNTIME_S = 1800.0
SCAN_INTERVAL_S = 60.0
_ENV_CAP = "RESUALIGN_JOB_MAX_RUNTIME_S"


def max_runtime_seconds() -> float | None:
    """Task-level wall-clock cap; None means disabled.

    Parsed per call (env hot-editable) with role_router._role_timeout style
    tolerance: invalid values fall back to the default instead of crashing
    the sweep. 0 or negative disables the watchdog entirely.
    """
    raw = os.environ.get(_ENV_CAP, "").strip()
    if not raw:
        return DEFAULT_MAX_RUNTIME_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MAX_RUNTIME_S
    if value <= 0:
        return None
    return value


def _timeout_error(cap: float) -> str:
    return (
        f"任务超时：运行超过 {int(cap)} 秒仍未完成，已标记失败（可重新对齐）。"
        "若本地模型较慢，可调大 RESUALIGN_JOB_MAX_RUNTIME_S。"
    )


def scan_once(now: float | None = None) -> list[str]:
    """Fail running jobs older than the cap. Returns the job ids forced."""
    cap = max_runtime_seconds()
    if cap is None:
        return []
    now = time.time() if now is None else now
    forced: list[str] = []
    for row in context._registry.stale_running_jobs(now - cap):
        job_id = row["job_id"]
        tenant_id = row["tenant_id"]
        error = _timeout_error(cap)
        # Conditional UPDATE inside fail() decides the race against a
        # possibly-alive worker: whoever writes the terminal state first wins.
        if not context._registry.fail(job_id, error):
            continue
        forced.append(job_id)
        log_event(
            logger,
            "job.watchdog_timeout",
            level="warning",
            extra={
                "job_id": job_id,
                "tenant_id": tenant_id,
                "started_at": row["started_at"],
                "cap_s": int(cap),
            },
        )
        # Mirror the worker's failed-terminal linkage (services/jobs.py
        # except branch): board badge + last_alignment_error so the failure
        # stays diagnosable, and the application pointer if one exists.
        stored = context._registry.get_payload(job_id)
        payload: dict[str, Any] = stored[0] if stored else {}
        library_job_id = payload.get("library_job_id")
        if library_job_id:
            try:
                context._jobs.update_job(
                    tenant_id,
                    library_job_id,
                    alignment_status="failed",
                    last_alignment_error=error,
                )
            except Exception:
                logger.exception(
                    "watchdog: failed to persist alignment error for library job %s",
                    library_job_id,
                )
        application_id = payload.get("application_id") or (
            stored[2] if stored else None
        )
        if application_id:
            try:
                context._applications.set_application_job(
                    tenant_id, application_id, job_id, "failed"
                )
            except Exception:
                logger.exception(
                    "watchdog: failed to link application %s after timeout %s",
                    application_id,
                    job_id,
                )
    return forced


def _loop(stop: threading.Event) -> None:
    while not stop.wait(SCAN_INTERVAL_S):
        try:
            scan_once()
        except Exception:
            # The sweep must never kill the loop; the next tick retries.
            logger.exception("watchdog scan failed")


def start() -> threading.Event | None:
    """Start the daemon sweep; returns its stop event, or None if disabled.

    Called from the API lifespan. ``Event.wait`` returns as soon as the flag
    is set, so shutdown is prompt even mid-interval.
    """
    if max_runtime_seconds() is None:
        return None
    stop = threading.Event()
    threading.Thread(
        target=_loop, args=(stop,), daemon=True, name="resualign-watchdog"
    ).start()
    return stop
