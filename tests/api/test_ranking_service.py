"""ADR-0065: ranking service - rebuild, recommend, best-resume, degradation.

Deterministic tests use the hashing embedder (RESUALIGN_EMBED_PROVIDER=hashing),
so no network and no model download; ordering semantics are what is under test.
"""

from __future__ import annotations

import pytest

from resualign.api.services import resume_ranking as rr
from resualign.job_library import JobLibraryStore
from resualign.vector_index import VectorIndex
from resualign.workspace import MasterResumeStore

TENANT = "tenant-ranking"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("RESUALIGN_RESUME_RANKING", "1")
    monkeypatch.setenv("RESUALIGN_EMBED_PROVIDER", "hashing")
    monkeypatch.delenv("RESUALIGN_RANKING_FUSION", raising=False)
    rr.reset_index_for_tests()
    db = tmp_path / "jobs.db"
    jobs = JobLibraryStore(db_path=db)
    resumes = MasterResumeStore(db_path=db)
    index = VectorIndex(db_path=db)
    yield rr, jobs, resumes, index
    rr.reset_index_for_tests()


def _seed_jobs(jobs, count=3):
    created = []
    for position in range(count):
        job = jobs.create_job(
            TENANT,
            title="Backend Engineer " + str(position),
            jd_text="Java Spring Boot Redis MySQL backend role " + str(position),
            job_function="后端",
            match_score=90.0 - position,
        )
        created.append(job["job_id"])
    return created


def test_flag_off_returns_disabled(env, monkeypatch):
    service, jobs, resumes, index = env
    monkeypatch.setenv("RESUALIGN_RESUME_RANKING", "0")
    resume = resumes.create_master_resume(TENANT, "R", "Java backend resume")
    result = service.recommend_jobs(
        TENANT, jobs, resumes, resume_id=resume["resume_id"], index=index
    )
    assert result == {"enabled": False, "degraded": True, "reason": "disabled", "items": []}


def test_rebuild_embeds_and_is_idempotent(env):
    service, jobs, resumes, index = env
    _seed_jobs(jobs)
    first = service.rebuild_index(TENANT, jobs, index=index)
    assert first["embedded"] == 3
    assert first["skipped"] == 0
    second = service.rebuild_index(TENANT, jobs, index=index)
    assert second["embedded"] == 0
    assert second["skipped"] == 3
    stats = index.stats(TENANT)
    assert stats["jobs"]["count"] == 3
    assert stats["needs_rebuild"] is False


def test_rebuild_stores_jd_skills(env):
    service, jobs, _, index = env
    _seed_jobs(jobs, count=1)
    service.rebuild_index(TENANT, jobs, index=index)
    skills = index.job_skills(TENANT, model="hashing:ngram-256")
    assert any("java" in value for value in skills.values())


def test_recommend_returns_ranked_items(env):
    service, jobs, resumes, index = env
    _seed_jobs(jobs)
    service.rebuild_index(TENANT, jobs, index=index)
    resume = resumes.create_master_resume(TENANT, "R", "Java Spring Boot backend")
    result = service.recommend_jobs(
        TENANT, jobs, resumes, resume_id=resume["resume_id"], limit=2, index=index
    )
    assert result["enabled"] is True
    assert result["degraded"] is False
    assert len(result["items"]) == 2
    first = result["items"][0]
    assert first["job_id"]
    assert 0 <= first["why"]["semantic_percentile"] <= 100
    assert isinstance(first["why"]["skill_hits"], list)


def test_recommend_missing_resume_degrades(env):
    service, jobs, resumes, index = env
    _seed_jobs(jobs)
    result = service.recommend_jobs(
        TENANT, jobs, resumes, resume_id="nope", index=index
    )
    assert result["degraded"] is True
    assert result["reason"] == "resume_missing"


def test_recommend_empty_library_returns_empty(env):
    service, jobs, resumes, index = env
    resume = resumes.create_master_resume(TENANT, "R", "Java backend")
    result = service.recommend_jobs(
        TENANT, jobs, resumes, resume_id=resume["resume_id"], index=index
    )
    assert result["items"] == []
    assert result["degraded"] is False


def test_recommend_falls_back_to_match_score_when_index_empty(env):
    service, jobs, resumes, index = env
    _seed_jobs(jobs, count=2)
    resume = resumes.create_master_resume(TENANT, "R", "Java backend")
    result = service.recommend_jobs(
        TENANT, jobs, resumes, resume_id=resume["resume_id"], index=index
    )
    assert result["degraded"] is True
    assert result["reason"] == "index_empty"
    scores = [item["score"] for item in result["items"]]
    assert scores == sorted(scores, reverse=True)


def test_best_resume_ranks_and_never_writes_back(env):
    service, jobs, resumes, index = env
    job_ids = _seed_jobs(jobs, count=1)
    before = jobs.get_job(TENANT, job_ids[0])
    assert "workbench_resume_id" not in before or not before["workbench_resume_id"]
    resumes.create_master_resume(TENANT, "Java", "Java Spring Boot Redis")
    resumes.create_master_resume(TENANT, "Product", "PRD roadmap user research")
    result = service.best_resume(TENANT, jobs, resumes, job_ids[0], limit=2, index=index)
    assert result["degraded"] is False
    assert len(result["items"]) == 2
    after = jobs.get_job(TENANT, job_ids[0])
    assert not after.get("workbench_resume_id")


def test_best_resume_missing_job_raises(env):
    service, jobs, resumes, index = env
    with pytest.raises(KeyError):
        service.best_resume(TENANT, jobs, resumes, "missing", index=index)


def test_fusion_rrf_math_and_flag(env, monkeypatch):
    first = [("a", 1.0), ("b", 0.9), ("c", 0.8)]
    second = [("b", 1.0), ("a", 0.9), ("c", 0.1)]
    fused = rr._rrf(first, second, k=60)
    assert [job_id for job_id, _ in fused] == ["a", "b", "c"]
    monkeypatch.setenv("RESUALIGN_RANKING_FUSION", "1")
    assert rr.fusion_enabled() is True


def test_fusion_path_returns_items(env, monkeypatch):
    service, jobs, resumes, index = env
    _seed_jobs(jobs, count=3)
    service.rebuild_index(TENANT, jobs, index=index)
    monkeypatch.setenv("RESUALIGN_RANKING_FUSION", "1")
    resume = resumes.create_master_resume(TENANT, "R", "Java Spring Boot backend")
    result = service.recommend_jobs(
        TENANT, jobs, resumes, resume_id=resume["resume_id"], limit=3, index=index
    )
    assert result["degraded"] is False
    assert len(result["items"]) >= 1


def test_index_status_reports_counts(env):
    service, jobs, _, index = env
    _seed_jobs(jobs, count=2)
    service.rebuild_index(TENANT, jobs, index=index)
    status = service.index_status(TENANT, index=index)
    assert status["jobs"]["count"] == 2
    assert status["limit"] == 5000
    assert status["enabled"] is True


def test_similar_existing_jobs_threshold(env):
    service, jobs, _, index = env
    job_ids = _seed_jobs(jobs, count=2)
    service.rebuild_index(TENANT, jobs, index=index)
    hits = service.similar_existing_jobs(
        TENANT,
        jobs,
        "Java Spring Boot Redis MySQL backend role 0",
        index=index,
        threshold=0.5,
    )
    assert any(hit["job_id"] == job_ids[0] for hit in hits)


def test_detect_skills_helper():
    from resualign.prematch import detect_skills

    skills = detect_skills("熟悉 Java、Spring Boot、Redis 与 Kubernetes")
    assert "java" in skills and "redis" in skills

def test_similar_existing_for_texts_batches_and_excludes(env):
    service, jobs, _, index = env
    job_ids = _seed_jobs(jobs, count=2)
    service.rebuild_index(TENANT, jobs, index=index)
    results = service.similar_existing_for_texts(
        TENANT,
        jobs,
        ["Java Spring Boot Redis MySQL backend role 0", ""],
        exclude_ids=[job_ids[1]],
        index=index,
        threshold=0.5,
    )
    assert len(results) == 2
    assert results[1] == []
    assert any(hit["job_id"] == job_ids[0] for hit in results[0])
    assert all(hit["job_id"] != job_ids[1] for hit in results[0])
