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
    """Expand a canonical or legacy status to all values that map to it."""
    value = str(status or "").strip()
    canonical = canonical_status(value)
    aliases = tuple(
        legacy
        for legacy, canon in _JOB_STATUS_ALIASES.items()
        if canon == canonical
    )
    if value not in aliases:
        aliases = aliases + (value,)
    return aliases


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
