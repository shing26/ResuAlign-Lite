"""Delivery-loop status lifecycle rules (ADR-0027 / issue #21)."""

from __future__ import annotations

from resualign.job_library import status_lifecycle_fields


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
