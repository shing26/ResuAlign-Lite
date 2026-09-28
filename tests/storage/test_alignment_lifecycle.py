"""Tests for the alignment_status state machine (alignment_lifecycle)."""

from __future__ import annotations

import pytest

from resualign.alignment_lifecycle import (
    ALIGNMENT_STATUSES,
    AlignmentTransitionError,
    can_transition,
    is_terminal,
    transition_alignment,
)
from resualign.job_library import JobLibraryStore


@pytest.fixture
def store(tmp_path):
    return JobLibraryStore(db_path=tmp_path / "jobs.db")


def _create_job(store, tenant="local"):
    job = store.create_job(tenant, title="对齐状态机测试", jd_text="JD 文本")
    return job["job_id"]


def test_transition_matrix_covers_full_happy_path(store):
    job_id = _create_job(store)
    tenant = "local"
    assert store.get_job(tenant, job_id)["alignment_status"] == "idle"

    assert transition_alignment(store, tenant, job_id, "queued") == "idle"
    assert transition_alignment(store, tenant, job_id, "running") == "queued"
    # succeeded 的正式写点在 save_alignment（原子携带产物），这里验证矩阵放行
    store.update_job(tenant, job_id, alignment_status="succeeded")
    assert store.get_job(tenant, job_id)["alignment_status"] == "succeeded"

    # 重跑：succeeded → queued → failed（LLM 失败同步）
    assert transition_alignment(store, tenant, job_id, "queued") == "succeeded"
    assert transition_alignment(store, tenant, job_id, "failed") == "queued"


def test_transition_rejects_illegal_paths(store):
    job_id = _create_job(store)
    tenant = "local"
    with pytest.raises(AlignmentTransitionError):
        transition_alignment(store, tenant, job_id, "succeeded")  # idle → succeeded
    transition_alignment(store, tenant, job_id, "queued")
    with pytest.raises(AlignmentTransitionError):
        transition_alignment(store, tenant, job_id, "succeeded")  # queued 不可直达 succeeded（succeeded 只由 save_alignment 原子写）


def test_transition_carries_extra_fields_atomically(store):
    job_id = _create_job(store)
    tenant = "local"
    transition_alignment(
        store, tenant, job_id, "queued", workbench_job_id="wj-1"
    )
    job = store.get_job(tenant, job_id)
    assert job["alignment_status"] == "queued"
    assert job["workbench_job_id"] == "wj-1"


def test_transition_unknown_status_and_missing_job(store):
    job_id = _create_job(store)
    with pytest.raises(AlignmentTransitionError):
        transition_alignment(store, "local", job_id, "paused")
    with pytest.raises(AlignmentTransitionError):
        transition_alignment(store, "local", "no-such-job", "queued")


def test_cancel_style_reset_queued_to_idle(store):
    job_id = _create_job(store)
    tenant = "local"
    transition_alignment(store, tenant, job_id, "queued")
    transition_alignment(store, tenant, job_id, "idle")
    assert store.get_job(tenant, job_id)["alignment_status"] == "idle"


def test_helpers():
    assert is_terminal("succeeded") and is_terminal("failed")
    assert not is_terminal("running") and not is_terminal(None)
    assert can_transition("queued", "failed")
    assert not can_transition("idle", "failed")
    for status in ALIGNMENT_STATUSES:
        assert can_transition(status, status)  # 自转移（幂等重写）恒允许


# -- usable_diffs / #111 / ADR-0041 决定 5 -----------------------------------


def test_save_alignment_persists_usable_diffs(store):
    job_id = _create_job(store)
    diffs = [
        {"type": "modify", "original": "a", "proposed": "b", "reason": "r"},
        {"type": "modify", "original": "c", "proposed": "d", "reason": "r"},
    ]
    saved = store.save_alignment("local", job_id, diffs=diffs)
    assert saved["usable_diffs"] == 2  # default = len(diffs)
    explicit = store.save_alignment("local", job_id, diffs=diffs, usable_diffs=1)
    assert explicit["usable_diffs"] == 1  # caller may override


def test_projection_no_gap_when_usable_zero(store):
    job_id = _create_job(store)
    saved = store.save_alignment(
        "local",
        job_id,
        diffs=[],
        gap_report={
            "missing_keywords": [],
            "misaligned_emphasis": [],
            "strength_matches": [],
        },
        alignment_status="succeeded",
    )
    assert saved["usable_diffs"] == 0
    assert saved["has_gap"] is False
    assert saved["alignment_reason"] == "no_gap"


def test_projection_no_output_when_failed_with_gap(store):
    job_id = _create_job(store)
    saved = store.save_alignment(
        "local",
        job_id,
        diffs=[],
        gap_report={"missing_keywords": ["Redis"]},
        alignment_status="failed",
        last_alignment_error="no_output: 有缺口但未产出可用建议",
    )
    assert saved["usable_diffs"] == 0
    assert saved["has_gap"] is True
    assert saved["alignment_reason"] == "no_output"


def test_legacy_db_backfills_usable_diffs(tmp_path):
    """Migration 45 adds the column AND backfills usable_diffs from
    diffs_json on a pre-#111 database (executescript runs ALTER + UPDATE)."""
    import json
    import sqlite3

    from resualign.job_library import _JOB_LIBRARY_SCHEMA

    legacy = _JOB_LIBRARY_SCHEMA.replace(
        "    usable_diffs INTEGER NOT NULL DEFAULT 0,\n", ""
    )
    assert "usable_diffs" not in legacy  # strip really happened
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(legacy)
    diffs = [
        {"type": "modify", "original": "a", "proposed": "b"},
        {"type": "modify", "original": "c", "proposed": "d"},
        {"type": "modify", "original": "e", "proposed": "f"},
    ]
    conn.execute(
        "INSERT INTO library_jobs (job_id, tenant_id, title, jd_text, "
        "dedupe_key, created_at, updated_at, alignment_status, diffs_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "legacy1",
            "local",
            "旧岗",
            "旧 JD",
            "k-legacy1",
            1.0,
            1.0,
            "succeeded",
            json.dumps(diffs, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()

    reopened = JobLibraryStore(db_path=db)  # triggers migrations 1..45
    job = reopened.get_job("local", "legacy1")
    assert job["usable_diffs"] == 3  # backfilled from diffs_json length
