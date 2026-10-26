"""ADR-0065: vector index storage - roundtrip, isolation, drift, incremental."""

from __future__ import annotations

import pytest

from resualign.vector_index import VectorIndex


@pytest.fixture
def index(tmp_path):
    return VectorIndex(db_path=tmp_path / "jobs.db")


def test_upsert_get_roundtrip_normalizes(index):
    assert index.upsert_job("t1", "job-1", [3.0, 4.0], model="m") is True
    stored = index.get_job("t1", "job-1", model="m")
    assert stored is not None
    assert abs(stored[0] - 0.6) < 1e-6 and abs(stored[1] - 0.8) < 1e-6


def test_sha_unchanged_skips_write(index):
    sha = VectorIndex.text_sha256("some jd")
    assert index.upsert_job("t1", "job-1", [1.0, 0.0], model="m", text_sha256=sha)
    assert index.upsert_job("t1", "job-1", [0.0, 1.0], model="m", text_sha256=sha) is False
    assert index.get_job("t1", "job-1", model="m")[0] == 1.0
    assert index.upsert_job(
        "t1", "job-1", [0.0, 1.0], model="m", text_sha256=VectorIndex.text_sha256("changed")
    )


def test_search_orders_by_cosine_and_honors_k_and_ids(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m")
    index.upsert_job("t1", "b", [0.0, 1.0], model="m")
    index.upsert_job("t1", "c", [0.9, 0.1], model="m")
    hits = index.search_jobs("t1", [1.0, 0.0], model="m", k=2)
    assert [job_id for job_id, _ in hits] == ["a", "c"]
    filtered = index.search_jobs("t1", [1.0, 0.0], model="m", k=5, job_ids=["b"])
    assert [job_id for job_id, _ in filtered] == ["b"]
    assert index.search_jobs("t1", [1.0, 0.0], model="m", k=5, job_ids=[]) == []


def test_tenant_isolation(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m")
    assert index.search_jobs("t2", [1.0, 0.0], model="m") == []
    assert index.get_job("t2", "a", model="m") is None


def test_dim_mismatch_is_excluded_not_scored(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m")
    assert index.search_jobs("t1", [1.0, 0.0, 0.0], model="m") == []


def test_model_mismatch_is_excluded(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m1")
    assert index.search_jobs("t1", [1.0, 0.0], model="m2") == []


def test_delete_and_clear(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m")
    index.upsert_job("t1", "b", [0.0, 1.0], model="m")
    index.delete_job("t1", "a")
    assert index.get_job("t1", "a", model="m") is None
    assert index.clear("t1") == 1
    assert index.search_jobs("t1", [1.0, 0.0], model="m") == []


def test_stats_reports_drift_and_limit(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m1")
    assert index.stats("t1")["needs_rebuild"] is False
    index.upsert_job("t1", "b", [1.0, 0.0, 0.0], model="m2")
    stats = index.stats("t1")
    assert stats["needs_rebuild"] is True
    assert stats["jobs"]["count"] == 2
    assert stats["over_limit"] is False


def test_resume_vectors_roundtrip_and_search(index):
    index.upsert_resume("t1", "r1", [1.0, 0.0], model="m")
    index.upsert_resume("t1", "r2", [0.0, 1.0], model="m")
    assert index.get_resume("t1", "r1", model="m") is not None
    hits = index.search_resumes("t1", [1.0, 0.0], model="m", k=1)
    assert [resume_id for resume_id, _ in hits] == ["r1"]


def test_job_skills_roundtrip(index):
    index.upsert_job(
        "t1", "a", [1.0, 0.0], model="m", skills=["java", "redis"]
    )
    assert index.job_skills("t1", model="m") == {"a": ["java", "redis"]}


def test_missing_job_ids(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m")
    missing = index.missing_job_ids("t1", ["a", "b"], model="m")
    assert missing == ["b"]
    assert index.missing_job_ids("t1", [], model="m") == []


def test_zero_vector_rejected(index):
    with pytest.raises(ValueError):
        index.upsert_job("t1", "a", [0.0, 0.0], model="m")


def test_sha_helpers(index):
    index.upsert_job("t1", "a", [1.0, 0.0], model="m", text_sha256="abc")
    assert index.job_shas("t1", model="m") == {"a": "abc"}
    index.upsert_resume("t1", "r1", [1.0, 0.0], model="m", text_sha256="xyz")
    assert index.resume_sha("t1", "r1", model="m") == "xyz"
    assert index.resume_sha("t1", "missing", model="m") is None
