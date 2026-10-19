from resualign.api.services.alignment_rules import split_verified_diffs


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
