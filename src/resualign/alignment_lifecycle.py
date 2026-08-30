"""Alignment pipeline status machine — single write point for alignment_status.

This owns the *alignment* state machine only::

    idle → queued → running → succeeded | failed (→ queued on rerun)

It is a separate machine from the delivery lifecycle
(``job_library/status_lifecycle.py``, draft/applied/interview/offer/withdrawn,
ADR-0027). CONTEXT.md: "Alignment" is a kanban badge derived from
``alignment_status``, never a sixth delivery status.

Write discipline:

- Every ``alignment_status`` write except *succeeded* goes through
  :func:`transition_alignment`. The succeeded write stays inside
  ``JobLibraryStore.save_alignment`` so the products (diffs/draft/scores)
  and the status land in one atomic UPDATE — splitting them would open a
  window where products exist while the badge still reads stale.
- The worker registry (``jobs.JobRegistry``) keeps its own analysis-job
  table; it is mirrored into ``alignment_status`` at claim (running) and
  fail (failed) so the badge can no longer go stale between failures and
  the next ``_recover_stale_alignments`` startup sweep.
"""

from __future__ import annotations

from typing import Any

ALIGNMENT_STATUSES = ("idle", "queued", "running", "succeeded", "failed")

TERMINAL_STATUSES = ("succeeded", "failed")

# prev -> allowed next statuses. Self-transitions are permitted: they cover
# idempotent re-writes such as re-triggering a queued/running job with new
# parameters (the router re-queues with fresh fields) and recovery
# re-confirming a terminal state.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "idle": frozenset({"queued"}),
    "queued": frozenset({"queued", "running", "failed", "idle"}),
    "running": frozenset({"running", "succeeded", "failed", "queued"}),
    "succeeded": frozenset({"succeeded", "queued"}),
    "failed": frozenset({"failed", "queued"}),
}


class AlignmentTransitionError(ValueError):
    """Raised when an alignment_status transition is not allowed."""


def is_terminal(status: str | None) -> bool:
    return (status or "") in TERMINAL_STATUSES


def can_transition(prev: str | None, new: str) -> bool:
    prev = prev or "idle"
    # 自转移恒允许：幂等重写（重触发、恢复扫描重复确认终态）。
    return new == prev or new in ALLOWED_TRANSITIONS.get(prev, frozenset())


def transition_alignment(
    store: Any,
    tenant_id: str,
    job_id: str,
    new_status: str,
    **extra_fields: Any,
) -> str:
    """Move a library job's alignment_status to ``new_status``.

    Validates the transition against the matrix, then performs a single
    ``update_job`` call carrying the status plus any extra fields so the
    status and its accompanying products/links stay atomic. Returns the
    previous status.

    Raises :class:`AlignmentTransitionError` on an illegal transition and
    propagates store errors unchanged.
    """
    if new_status not in ALIGNMENT_STATUSES:
        raise AlignmentTransitionError(f"Unknown alignment_status: {new_status}")
    job = store.get_job(tenant_id, job_id)
    if job is None:
        raise AlignmentTransitionError(f"Job not found: {job_id}")
    prev = job.get("alignment_status") or "idle"
    if not can_transition(prev, new_status):
        raise AlignmentTransitionError(
            f"Illegal alignment transition {prev!r} -> {new_status!r} "
            f"for job {job_id}"
        )
    store.update_job(tenant_id, job_id, alignment_status=new_status, **extra_fields)
    return prev
