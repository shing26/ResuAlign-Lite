"""Job lifecycle FSM helpers extracted from the legacy store module."""

from __future__ import annotations

import time
from typing import Any

from ..store_base import UserStoreError
from .models import (
    _JOB_STATUS_ALIASES,
    _STATUS_LABELS,
    JOB_STATUSES,
    JOB_STATUSES_CANONICAL,
)

# Delivery status transition matrix (ADR-0027 / module 3).
# Single-direction funnel: draft → applied → interview → offer/withdrawn.
# Skipping stages is allowed (draft → interview is valid for imported jobs).
# Any backward move is rejected with 422; "revive" (重新打开) is an explicit
# action that moves from a terminal status back to a non-terminal one while
# preserving terminal timestamps (semantic: "曾经到过").
DELIVERY_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"draft", "applied", "interview", "offer", "withdrawn"}),
    "applied": frozenset({"applied", "interview", "offer", "withdrawn"}),
    "interview": frozenset({"interview", "offer", "withdrawn"}),
    "offer": frozenset({"offer", "withdrawn"}),
    "withdrawn": frozenset({"withdrawn"}),  # terminal; only "revive" can move out
}

TERMINAL_DELIVERY_STATUSES = frozenset({"offer", "withdrawn"})


class StatusTransitionError(UserStoreError):
    """Raised when a delivery status transition is not allowed."""


def can_transition_status(prev: str | None, new: str) -> bool:
    """Return True if prev → new is a valid forward/skip transition."""
    prev = canonical_status(prev or "draft")
    new = canonical_status(new)
    return new in DELIVERY_TRANSITIONS.get(prev, frozenset())



def is_terminal_status(status: str | None) -> bool:
    """Return True if the status is a terminal delivery state."""
    return canonical_status(status or "") in TERMINAL_DELIVERY_STATUSES


def allowed_transition_targets(status: str | None) -> list[str]:
    """Return the list of valid target statuses from the given status."""
    status = canonical_status(status or "draft")
    return sorted(DELIVERY_TRANSITIONS.get(status, frozenset()))


def validate_status_transition(
    current_status: str | None,
    target_status: str,
    *,
    revive: bool = False,
) -> None:
    """Validate a delivery status transition.

    Raises :class:`StatusTransitionError` on an illegal transition.
    When ``revive`` is True, allow moving from a terminal status back to a
    non-terminal one (the "重新打开" action); terminal timestamps are
    preserved by the caller.
    """
    current = canonical_status(current_status or "draft")
    target = canonical_status(target_status)
    if can_transition_status(current, target):
        return
    if revive and is_terminal_status(current) and not is_terminal_status(target):
        return
    allowed = allowed_transition_targets(current)
    raise StatusTransitionError(
        f"Illegal status transition {current!r} -> {target!r}. "
        f"Allowed targets from {current!r}: {allowed}"
    )


def canonical_status(status: str) -> str:
    """Return the canonical five-state key for a stored status value."""
    value = str(status or "").strip()
    return _JOB_STATUS_ALIASES.get(value, value)


def status_label(status: str) -> str:
    """Return the display label for a canonical or stored status value."""
    value = str(status or "").strip()
    canonical = _JOB_STATUS_ALIASES.get(value, value)
    return _STATUS_LABELS.get(canonical, canonical)


def _status_filter_values(status: str) -> tuple[str, ...]:
    """Expand a canonical or legacy status to all values that map to it.

    The returned tuple always includes the canonical key plus every legacy
    label for it, so either storage flavour (canonical ``applied`` or the
    legacy 中文 ``已投递``) matches an ``IN (...)`` filter (Bug-08/Bug-12).
    """
    value = str(status or "").strip()
    canonical = canonical_status(value)
    aliases = tuple(
        legacy
        for legacy, canon in _JOB_STATUS_ALIASES.items()
        if canon == canonical
    )
    result = list(aliases)
    if canonical not in result:
        result.append(canonical)
    if value not in result:
        result.append(value)
    return tuple(result)


def _validate_status(status: str) -> str:
    value = str(status or "").strip()
    if value in JOB_STATUSES or value in JOB_STATUSES_CANONICAL:
        return value
    raise UserStoreError(f"Invalid status: {value}")


def status_lifecycle_fields(
    current: dict[str, Any] | None,
    target_status: str,
    today: str | None = None,
    provided: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return timeline field writes for a status transition (ADR-0027).

    Values follow ``update_job``'s clear-on-empty contract: ``""`` clears a
    field, a string sets it, and omitted keys leave it unchanged. Forward
    moves fill the stage's missing timestamp with ``today``; terminal states
    keep historical timestamps while clearing follow-up fields.
    """
    target = canonical_status(target_status)
    if target not in JOB_STATUSES_CANONICAL:
        return {}
    today = today or time.strftime("%Y-%m-%d")
    current = current or {}
    provided = provided or {}
    out: dict[str, str] = {}

    def pick(field: str, fallback: str) -> str:
        value = provided.get(field)
        return fallback if value is None else value

    if target == "draft":
        for field in (
            "applied_at",
            "offer_at",
            "rejected_at",
            "next_step",
            "next_step_due_at",
            "interview_stage",
        ):
            out[field] = ""
        return out

    if target == "applied":
        out["applied_at"] = pick("applied_at", current.get("applied_at") or today)
        for field in ("offer_at", "rejected_at", "interview_stage"):
            out[field] = ""
        return out

    if target == "interview":
        out["applied_at"] = pick("applied_at", current.get("applied_at") or today)
        for field in ("offer_at", "rejected_at"):
            out[field] = ""
        return out

    if target == "offer":
        out["offer_at"] = pick("offer_at", today)
        out["rejected_at"] = ""
        for field in ("next_step", "next_step_due_at", "interview_stage"):
            out[field] = ""
        return out

    if target == "withdrawn":
        out["rejected_at"] = pick("rejected_at", today)
        for field in ("next_step", "next_step_due_at", "interview_stage"):
            out[field] = ""
        return out

    return out
