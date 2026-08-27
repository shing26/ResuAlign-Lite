"""G6: applications -> library jobs migration helper."""

from __future__ import annotations

from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    merge_applications_into_jobs,
)


def _stores(tmp_path):
    db = tmp_path / "merge.db"
    apps = ApplicationStore(db_path=db)
    resumes = MasterResumeStore(db_path=db)
    jobs = JobLibraryStore(db_path=db)
    return apps, resumes, jobs


def test_merge_maps_statuses_and_applied_at(tmp_path):
    apps, resumes, jobs = _stores(tmp_path)
    resume = resumes.create_master_resume("t1", "Master", "Python developer.")

    job_url = jobs.create_job(
        tenant_id="t1",
        title="Backend A",
        jd_text="Python backend role A",
        source_url="https://example.com/jobs/1",
    )
    job_text = jobs.create_job(
        tenant_id="t1", title="Backend B", jd_text="Python backend role B"
    )

    app_url = apps.create_application(
        "t1",
        "App A",
        resume["resume_id"],
        jd_url="https://example.com/jobs/1",
    )
    apps.update_application("t1", app_url["application_id"], status="interview")

    app_text = apps.create_application(
        "t1",
        "App B",
        resume["resume_id"],
        jd_text="Python backend role B",
    )
    apps.update_application("t1", app_text["application_id"], status="applied")

    merged, skipped = merge_applications_into_jobs(apps, jobs, "t1")
    assert (merged, skipped) == (2, 0)

    by_url = jobs.get_job("t1", job_url["job_id"])
    assert by_url["status"] == "面试中"
    assert by_url["status_canonical"] == "interview"
    assert by_url["applied_at"] is not None

    by_text = jobs.get_job("t1", job_text["job_id"])
    assert by_text["status"] == "已投递"
    assert by_text["status_canonical"] == "applied"
    assert by_text["applied_at"] is not None


def test_merge_skips_unmatched_and_non_draft_jobs(tmp_path):
    apps, resumes, jobs = _stores(tmp_path)
    resume = resumes.create_master_resume("t1", "Master", "Python developer.")

    job = jobs.create_job(
        tenant_id="t1",
        title="Backend",
        jd_text="Python backend role",
        source_url="https://example.com/jobs/1",
    )
    # Move the job past the initial state first.
    jobs.update_job("t1", job["job_id"], status="面试中")

    app = apps.create_application(
        "t1",
        "App",
        resume["resume_id"],
        jd_url="https://example.com/jobs/1",
    )
    apps.update_application("t1", app["application_id"], status="offer")

    orphan = apps.create_application(
        "t1", "Orphan", resume["resume_id"], jd_text="no such job anywhere"
    )
    assert orphan["application_id"]

    merged, skipped = merge_applications_into_jobs(apps, jobs, "t1")
    assert (merged, skipped) == (0, 2)
    assert jobs.get_job("t1", job["job_id"])["status"] == "面试中"


def test_merge_draft_maps_to_not_applied_and_is_idempotent(tmp_path):
    apps, resumes, jobs = _stores(tmp_path)
    resume = resumes.create_master_resume("t1", "Master", "Python developer.")

    job = jobs.create_job(
        tenant_id="t1",
        title="Backend",
        jd_text="Python backend role",
        source_url="https://example.com/jobs/2",
    )
    app = apps.create_application(
        "t1",
        "App",
        resume["resume_id"],
        jd_url="https://example.com/jobs/2",
    )
    # Status stays 'draft' -> maps to 未投递, no applied_at.
    assert app["status"] == "draft"

    first = merge_applications_into_jobs(apps, jobs, "t1")
    assert first == (1, 0)
    refreshed = jobs.get_job("t1", job["job_id"])
    assert refreshed["status"] == "未投递"
    assert refreshed["applied_at"] is None

    # Second run: job is still 未投递 and app still draft -> merges again,
    # but there is nothing new to record; counts stay stable.
    second = merge_applications_into_jobs(apps, jobs, "t1")
    assert second == (1, 0)


def test_merge_is_tenant_scoped(tmp_path):
    apps, resumes, jobs = _stores(tmp_path)
    resume_a = resumes.create_master_resume("t1", "Master A", "Python dev.")
    resume_b = resumes.create_master_resume("t2", "Master B", "Java dev.")

    jobs.create_job(
        tenant_id="t1",
        title="Backend A",
        jd_text="Python backend role",
        source_url="https://example.com/jobs/9",
    )
    jobs.create_job(
        tenant_id="t2",
        title="Backend B",
        jd_text="Python backend role",
        source_url="https://example.com/jobs/9",
    )
    apps.create_application(
        "t1",
        "App A",
        resume_a["resume_id"],
        jd_url="https://example.com/jobs/9",
    )
    app_b = apps.create_application(
        "t2",
        "App B",
        resume_b["resume_id"],
        jd_url="https://example.com/jobs/9",
    )
    apps.update_application("t2", app_b["application_id"], status="applied")

    merged, skipped = merge_applications_into_jobs(apps, jobs, "t1")
    assert (merged, skipped) == (1, 0)

    job_a = next(
        j for j in jobs.list_jobs("t1") if j["title"] == "Backend A"
    )
    job_b = next(
        j for j in jobs.list_jobs("t2") if j["title"] == "Backend B"
    )
    assert job_a["status"] == "未投递"
    # Tenant t2's job is untouched by the t1 migration.
    assert job_b["status"] == "未投递"
