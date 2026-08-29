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
