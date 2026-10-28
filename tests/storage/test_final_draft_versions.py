"""ADR-0066: final-draft versions are append-only, hashed, and rollback-safe."""

from __future__ import annotations

import hashlib

from resualign.job_library import JobLibraryStore

TENANT = "t1"


def _store(tmp_path) -> JobLibraryStore:
    return JobLibraryStore(db_path=tmp_path / "jobs.db")


def _job(store: JobLibraryStore) -> dict:
    return store.create_job(
        TENANT,
        title="后端工程师",
        jd_text="Java 后端开发",
        model="deepseek-v4-flash",
        prompt_version="engine:diag:v3",
    )


def test_save_appends_hashed_versions(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    first = store.save_final_draft(TENANT, job["job_id"], "第一版", accepted_diff_ids=["d1"])
    second = store.save_final_draft(
        TENANT, job["job_id"], "第二版", accepted_diff_ids=["d2", "d1"]
    )
    assert (first["version"], second["version"]) == (1, 2)
    assert first["sha256"] == hashlib.sha256("第一版".encode("utf-8")).hexdigest()
    assert second["sha256"] == hashlib.sha256("第二版".encode("utf-8")).hexdigest()

    versions = store.list_final_draft_versions(TENANT, job["job_id"])
    assert [item["version"] for item in versions] == [1, 2]
    assert versions[1]["accepted_diff_ids"] == ["d1", "d2"]
    assert versions[1]["sha256"] == second["sha256"]
    assert versions[1]["chars"] == len("第二版")

    detail = store.get_final_draft_version(TENANT, job["job_id"], 1)
    assert detail is not None and detail["draft"] == "第一版"

    current = store.current_final_draft_version(TENANT, job["job_id"])
    assert current["version"] == 2
    assert current["version_id"] == second["version_id"]


def test_projection_matches_latest_version(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    store.save_final_draft(TENANT, job["job_id"], "第一版")
    store.save_final_draft(TENANT, job["job_id"], "第二版")
    saved = store.get_job(TENANT, job["job_id"])
    assert saved["final_draft"] == "第二版"
    assert saved["final_draft_version"] == 2


def test_rollback_appends_new_version(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    store.save_final_draft(TENANT, job["job_id"], "第一版", accepted_diff_ids=["d1"])
    store.save_final_draft(TENANT, job["job_id"], "第二版")

    rolled = store.rollback_final_draft(TENANT, job["job_id"], 1)
    assert rolled["version"] == 3
    assert rolled["draft"] == "第一版"
    assert rolled["accepted_diff_ids"] == ["d1"]

    versions = store.list_final_draft_versions(TENANT, job["job_id"])
    assert [item["version"] for item in versions] == [1, 2, 3]
    assert versions[2]["source"] == "rollback"
    assert versions[2]["source_version"] == 1
    assert store.get_job(TENANT, job["job_id"])["final_draft"] == "第一版"


def test_rollback_unknown_version_returns_none(tmp_path):
    store = _store(tmp_path)
    job = _job(store)
    store.save_final_draft(TENANT, job["job_id"], "第一版")
    assert store.rollback_final_draft(TENANT, job["job_id"], 99) is None


def test_legacy_row_without_version_falls_back_to_projection(tmp_path):
    store = _store(tmp_path)
    job = store.create_job(TENANT, title="旧岗位", jd_text="Python", final_draft="旧定稿")
    current = store.current_final_draft_version(TENANT, job["job_id"])
    assert current["version_id"] is None
    assert current["source"] == "projection"
    assert current["sha256"] == hashlib.sha256("旧定稿".encode("utf-8")).hexdigest()
