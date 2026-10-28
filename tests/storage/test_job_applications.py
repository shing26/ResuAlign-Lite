"""ADR-0067: applications are the spine, bound to a final-draft version."""

from __future__ import annotations

import pytest

from resualign.job_library import JobLibraryStore
from resualign.store_base import UserStoreError

TENANT = "t1"


def _store(tmp_path) -> JobLibraryStore:
    return JobLibraryStore(db_path=tmp_path / "jobs.db")


def _job(store: JobLibraryStore) -> dict:
    return store.create_job(TENANT, title="后端工程师", jd_text="Java 后端")


def test_record_application_requires_final_draft(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    with pytest.raises(UserStoreError):
        store.upsert_job_application(TENANT, job["job_id"], channel="官网")


def test_record_application_binds_version_and_projects_state(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    saved = store.save_final_draft(TENANT, job["job_id"], "定稿正文", accepted_diff_ids=["d1"])

    row = store.upsert_job_application(
        TENANT, job["job_id"], channel="官网", applied_at="2026-10-28", notes="内推码"
    )
    assert row["version_id"] == saved["version_id"]
    assert row["final_draft_version"] == 1
    assert row["draft_sha256"] == saved["sha256"]
    assert row["channel"] == "官网"
    assert row["status"] == "applied"

    projected = store.get_job(TENANT, job["job_id"])
    assert projected["applied_at"] == "2026-10-28"
    assert projected["status"] == "已投递"

    again = store.upsert_job_application(TENANT, job["job_id"], channel="平台")
    assert again["application_id"] == row["application_id"]
    assert again["channel"] == "平台"
    assert len(store.list_job_applications(TENANT)) == 1


def test_outcome_moves_projection_status(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    store.save_final_draft(TENANT, job["job_id"], "定稿")
    store.upsert_job_application(TENANT, job["job_id"], channel="官网")

    row = store.update_job_application_outcome(
        TENANT, job["job_id"], "interview", outcome_at="2026-11-02"
    )
    assert row["status"] == "interview"
    assert row["outcome_at"] == "2026-11-02"
    assert store.get_job(TENANT, job["job_id"])["status"] == "面试中"

    with pytest.raises(UserStoreError):
        store.update_job_application_outcome(TENANT, job["job_id"], "bogus")


def test_timeline_orders_events(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    store.save_final_draft(TENANT, job["job_id"], "第一版")
    store.save_final_draft(TENANT, job["job_id"], "第二版")
    store.upsert_job_application(TENANT, job["job_id"], channel="官网")
    store.update_job_application_outcome(TENANT, job["job_id"], "offer")

    timeline = store.job_timeline(TENANT, job["job_id"])
    kinds = [event["kind"] for event in timeline["events"]]
    assert kinds[0] == "created"
    assert kinds.count("final_draft") == 2
    assert "application" in kinds
    assert "outcome" in kinds
    assert kinds.index("final_draft") < kinds.index("application") < kinds.index("outcome")
    timestamps = [event["at"] for event in timeline["events"]]
    assert timestamps == sorted(timestamps)

    assert store.job_timeline(TENANT, "missing") is None
