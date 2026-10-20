from resualign.api.services.alignment_rules import (
    resolve_alignment_outcome,
    split_verified_diffs,
)


def test_split_verified_diffs_quarantines_only_flagged_diffs():
    raw_diffs = [
        {
            "diff_id": "keep-1",
            "type": "modify",
            "original": "Built backend services",
            "proposed": "Built scalable backend services",
        },
        {
            "diff_id": "bad-1",
            "type": "modify",
            "original": "Built backend services",
            "proposed": "Built Kubernetes platform",
        },
    ]

    kept, invalid = split_verified_diffs(
        raw_diffs,
        [],
        eval_hallucinated=True,
        eval_hallucinated_diff_ids=["bad-1"],
        job_label="job-1",
    )

    assert [diff["diff_id"] for diff in kept] == ["keep-1"]
    assert [diff["diff_id"] for diff in invalid] == ["bad-1"]
    assert invalid[0]["provenance_state"] == "fabricated"
    assert "真实性评估" in invalid[0]["reason"]


def test_split_verified_diffs_falls_back_to_global_block_without_ids():
    raw_diffs = [
        {"diff_id": "keep-1", "type": "modify", "proposed": "A"},
        {"diff_id": "bad-1", "type": "modify", "proposed": "B"},
    ]

    kept, invalid = split_verified_diffs(
        raw_diffs,
        [],
        eval_hallucinated=True,
        job_label="job-2",
    )

    assert kept == []
    assert [diff["diff_id"] for diff in invalid] == ["keep-1", "bad-1"]


def test_all_blocked_hallucination_fails_without_reported_gap():
    """A blocked hallucination is still a failed run, not a green no-gap run."""
    status, error, reason = resolve_alignment_outcome(
        kept_diffs=[],
        gap_report={
            "missing_keywords": [],
            "misaligned_emphasis": [],
        },
        tailor_degraded=False,
        eval_hallucinated=True,
    )

    assert status == "failed"
    assert error is not None
    assert error.startswith("no_output: ")
    assert reason == "model_failed"


def test_no_safe_rewrite_fails_with_explanatory_reason():
    human_reason = (
        "岗位存在能力或经历缺口，但没有可在简历原文中逐字定位的证据，"
        "因此没有安全改写依据。"
    )
    status, error, outcome_reason = resolve_alignment_outcome(
        kept_diffs=[],
        gap_report={"missing_keywords": ["Kubernetes"]},
        tailor_degraded=False,
        eval_hallucinated=False,
        no_safe_rewrite=True,
        no_safe_rewrite_reason=human_reason,
    )

    assert status == "failed"
    assert error == f"no_output: {human_reason}"
    assert outcome_reason == "no_safe_rewrite"


def test_no_gap_zero_output_succeeds_without_claiming_alignment():
    status, error, reason = resolve_alignment_outcome(
        kept_diffs=[],
        gap_report={
            "missing_keywords": [],
            "misaligned_emphasis": [],
        },
        tailor_degraded=False,
        eval_hallucinated=False,
    )

    assert status == "succeeded"
    assert error is None
    assert reason == "no_gap"


def test_tailor_degraded_without_diff_is_a_model_failure():
    status, error, reason = resolve_alignment_outcome(
        kept_diffs=[],
        gap_report={
            "missing_keywords": [],
            "misaligned_emphasis": [],
        },
        tailor_degraded=True,
        eval_hallucinated=False,
    )

    assert status == "failed"
    assert error is not None
    assert error.startswith("no_output: ")
    assert reason == "model_failed"


def test_usable_diff_has_no_terminal_reason():
    status, error, reason = resolve_alignment_outcome(
        kept_diffs=[{"diff_id": "d1"}],
        gap_report={"missing_keywords": ["Redis"]},
        tailor_degraded=False,
        eval_hallucinated=False,
    )

    assert status == "succeeded"
    assert error is None
    assert reason is None
