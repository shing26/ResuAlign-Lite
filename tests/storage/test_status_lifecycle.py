"""Delivery-loop status lifecycle rules (ADR-0027 / issue #21 / module 3)."""

from __future__ import annotations

import pytest

from resualign.job_library import (
    StatusTransitionError,
    allowed_transition_targets,
    can_transition_status,
    is_terminal_status,
    status_lifecycle_fields,
    validate_status_transition,
)

TODAY = "2026-08-14"


def _job(status: str = "draft", **fields):
    data = {"status": status}
    data.update(fields)
    return data


def test_applied_fills_missing_applied_at_with_today():
    fields = status_lifecycle_fields(_job("draft"), "applied", today=TODAY)
    assert fields["applied_at"] == TODAY
    assert fields["offer_at"] == ""
    assert fields["rejected_at"] == ""
    assert fields["interview_stage"] == ""
    assert "next_step" not in fields


def test_applied_keeps_explicit_applied_at():
    fields = status_lifecycle_fields(
        _job("draft"),
        "applied",
        today=TODAY,
        provided={"applied_at": "2026-08-10"},
    )
    assert fields["applied_at"] == "2026-08-10"


def test_applied_explicit_empty_clears_existing_applied_at():
    fields = status_lifecycle_fields(
        _job("applied", applied_at="2026-08-10"),
        "applied",
        today=TODAY,
        provided={"applied_at": ""},
    )
    assert fields["applied_at"] == ""


def test_interview_keeps_existing_applied_at():
    fields = status_lifecycle_fields(
        _job("applied", applied_at="2026-08-10"),
        "interview",
        today=TODAY,
    )
    assert fields["applied_at"] == "2026-08-10"


def test_interview_fills_missing_applied_at():
    fields = status_lifecycle_fields(
        _job("draft"),
        "interview",
        today=TODAY,
    )
    assert fields["applied_at"] == TODAY
    assert fields["offer_at"] == ""
    assert fields["rejected_at"] == ""


def test_interview_explicit_empty_clears_existing_applied_at():
    fields = status_lifecycle_fields(
        _job("applied", applied_at="2026-08-10"),
        "interview",
        today=TODAY,
        provided={"applied_at": ""},
    )
    assert fields["applied_at"] == ""


def test_interview_none_provided_keeps_existing_applied_at():
    fields = status_lifecycle_fields(
        _job("applied", applied_at="2026-08-10"),
        "interview",
        today=TODAY,
        provided={"applied_at": None},
    )
    assert fields["applied_at"] == "2026-08-10"


def test_offer_sets_offer_at_and_clears_followup_fields():
    current = _job(
        "interview",
        applied_at="2026-08-10",
        next_step="二面",
        next_step_due_at="2026-08-20T09:00:00Z",
        interview_stage="二面",
    )
    fields = status_lifecycle_fields(current, "offer", today=TODAY)
    assert fields["offer_at"] == TODAY
    assert fields["rejected_at"] == ""
    assert fields["next_step"] == ""
    assert fields["next_step_due_at"] == ""
    assert fields["interview_stage"] == ""
    assert "applied_at" not in fields


def test_offer_uses_explicit_offer_at():
    fields = status_lifecycle_fields(
        _job("applied"),
        "offer",
        today=TODAY,
        provided={"offer_at": "2026-08-12"},
    )
    assert fields["offer_at"] == "2026-08-12"


def test_offer_explicit_empty_clears_offer_at():
    fields = status_lifecycle_fields(
        _job("applied", offer_at="2026-08-12"),
        "offer",
        today=TODAY,
        provided={"offer_at": ""},
    )
    assert fields["offer_at"] == ""


def test_withdrawn_keeps_history_and_clears_followups():
    current = _job(
        "interview",
        applied_at="2026-08-10",
        offer_at=None,
        next_step="三面",
        next_step_due_at="2026-08-22T09:00:00Z",
        interview_stage="三面",
    )
    fields = status_lifecycle_fields(current, "withdrawn", today=TODAY)
    assert fields["rejected_at"] == TODAY
    assert fields["next_step"] == ""
    assert fields["next_step_due_at"] == ""
    assert fields["interview_stage"] == ""
    assert "applied_at" not in fields
    assert "offer_at" not in fields


def test_withdrawn_uses_explicit_rejected_at():
    fields = status_lifecycle_fields(
        _job("applied"),
        "withdrawn",
        today=TODAY,
        provided={"rejected_at": "2026-08-12"},
    )
    assert fields["rejected_at"] == "2026-08-12"


def test_withdrawn_explicit_empty_clears_rejected_at():
    fields = status_lifecycle_fields(
        _job("applied", rejected_at="2026-08-12"),
        "withdrawn",
        today=TODAY,
        provided={"rejected_at": ""},
    )
    assert fields["rejected_at"] == ""


def test_backward_to_draft_clears_all_stage_fields():
    current = _job(
        "offer",
        applied_at="2026-08-10",
        offer_at="2026-08-12",
        next_step="入职",
        next_step_due_at="2026-09-01T00:00:00Z",
        interview_stage="",
    )
    fields = status_lifecycle_fields(current, "draft", today=TODAY)
    assert fields["applied_at"] == ""
    assert fields["offer_at"] == ""
    assert fields["rejected_at"] == ""
    assert fields["next_step"] == ""
    assert fields["next_step_due_at"] == ""
    assert fields["interview_stage"] == ""


# ------------------------------------------------------------------ #
# Delivery status transition matrix (module 3)                       #
# ------------------------------------------------------------------ #

def test_forward_transitions_are_allowed():
    assert can_transition_status("draft", "applied")
    assert can_transition_status("draft", "interview")
    assert can_transition_status("draft", "offer")
    assert can_transition_status("draft", "withdrawn")
    assert can_transition_status("applied", "interview")
    assert can_transition_status("applied", "offer")
    assert can_transition_status("applied", "withdrawn")
    assert can_transition_status("interview", "offer")
    assert can_transition_status("interview", "withdrawn")
    assert can_transition_status("offer", "withdrawn")


def test_skip_transitions_are_allowed():
    # Skipping stages is valid (e.g. imported jobs that jump to interview).
    assert can_transition_status("draft", "interview")
    assert can_transition_status("draft", "offer")
    assert can_transition_status("applied", "offer")


def test_backward_transitions_are_rejected():
    assert not can_transition_status("applied", "draft")
    assert not can_transition_status("interview", "applied")
    assert not can_transition_status("interview", "draft")
    assert not can_transition_status("offer", "interview")
    assert not can_transition_status("offer", "applied")
    assert not can_transition_status("offer", "draft")
    assert not can_transition_status("withdrawn", "offer")
    assert not can_transition_status("withdrawn", "interview")
    assert not can_transition_status("withdrawn", "applied")
    assert not can_transition_status("withdrawn", "draft")


def test_self_transitions_are_allowed():
    # Self-transitions are idempotent re-writes (e.g. merge_applications_into_jobs
    # re-applies the same status); they are always allowed.
    assert can_transition_status("draft", "draft")
    assert can_transition_status("applied", "applied")
    assert can_transition_status("interview", "interview")
    assert can_transition_status("offer", "offer")
    assert can_transition_status("withdrawn", "withdrawn")


def test_terminal_statuses():
    assert not is_terminal_status("draft")
    assert not is_terminal_status("applied")
    assert not is_terminal_status("interview")
    assert is_terminal_status("offer")
    assert is_terminal_status("withdrawn")

def test_allowed_transition_targets():
    assert allowed_transition_targets("draft") == [
        "applied",
        "draft",
        "interview",
        "offer",
        "withdrawn",
    ]
    assert allowed_transition_targets("applied") == [
        "applied",
        "interview",
        "offer",
        "withdrawn",
    ]
    assert allowed_transition_targets("interview") == [
        "interview",
        "offer",
        "withdrawn",
    ]
    assert allowed_transition_targets("offer") == [
        "offer",
        "withdrawn",
    ]


def test_validate_status_transition_raises_on_backward():
    with pytest.raises(StatusTransitionError, match="Illegal status transition"):
        validate_status_transition("offer", "applied")
    with pytest.raises(StatusTransitionError, match="Illegal status transition"):
        validate_status_transition("withdrawn", "draft")


def test_validate_status_transition_allows_forward():
    # Should not raise.
    validate_status_transition("draft", "applied")
    validate_status_transition("applied", "interview")
    validate_status_transition("interview", "offer")
    validate_status_transition("offer", "withdrawn")


def test_validate_status_transition_allows_revive():
    # Revive: terminal → non-terminal is allowed when revive=True.
    validate_status_transition("offer", "applied", revive=True)
    validate_status_transition("withdrawn", "interview", revive=True)
    validate_status_transition("withdrawn", "draft", revive=True)


def test_validate_status_transition_revive_still_rejects_non_terminal_backward():
    # revive=True only unlocks terminal → non-terminal; other backward moves
    # are still rejected.
    with pytest.raises(StatusTransitionError):
        validate_status_transition("interview", "applied", revive=True)
    with pytest.raises(StatusTransitionError):
        validate_status_transition("applied", "draft", revive=True)
