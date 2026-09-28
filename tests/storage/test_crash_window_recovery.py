"""O3: crash-window ordering in _run_job and startup alignment recovery."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import resualign.api as api_module
from resualign.jobs import JobRegistry
from resualign.models import Report
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)


def _report(score: int = 70) -> Report:
    return Report(score=score, skills=["Python"], model="test-model")


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        name: getattr(api_module, name)
        for name in (
            "_registry",
            "_users",
            "_resumes",
            "_applications",
            "_jobs",
            "_settings_store",
            "_session_store",
            "_payloads",
        )
    }
    db_path = tmp_path / "crash-window.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._session_store = (
        api_module._workbench_service.WorkstationSessionStore()
    )
    api_module._payloads = {}
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)


def _queue_workbench_job(payload: dict, application_id=None) -> str:
    """Create a registry job + in-memory payload without spawning a thread."""
    config = api_module.build_config()
    job = api_module._registry.create(
        payload, config, tenant_id="t1", application_id=application_id
    )
    api_module._payloads[job.job_id] = (payload, config, application_id, "t1")
    return job.job_id


def test_save_alignment_failure_keeps_registry_job_non_succeeded():
    job = api_module._jobs.create_job(
        tenant_id="t1", title="Backend", jd_text="Python backend engineer."
    )
    resume = api_module._resumes.create_master_resume(
        "t1", "Master", "Python developer with FastAPI."
    )
    job_id = _queue_workbench_job(
        {
            "resume_text": resume["content"],
            "jd_text": job["jd_text"],
            "library_job_id": job["job_id"],
            "workbench": True,
        }
    )
    with patch(
        "resualign.api._jobs.save_alignment",
        side_effect=RuntimeError("disk full"),
    ), patch("resualign.api.run", return_value=_report()):
        api_module._run_job(job_id)

    registry_job = api_module._registry.get(job_id)
    assert registry_job.status == "failed"
    stored = api_module._jobs.get_job("t1", job["job_id"])
    assert stored["alignment_status"] != "succeeded"


def test_alignment_persisted_before_registry_succeed():
    job = api_module._jobs.create_job(
        tenant_id="t1", title="Backend", jd_text="Python backend engineer."
    )
    resume = api_module._resumes.create_master_resume(
        "t1", "Master", "Python developer with FastAPI."
    )
    job_id = _queue_workbench_job(
        {
            "resume_text": resume["content"],
            "jd_text": job["jd_text"],
            "library_job_id": job["job_id"],
            "workbench": True,
        }
    )
    order: list[str] = []
    real_save = api_module._jobs.save_alignment

    def tracking_save(*args, **kwargs):
        order.append(api_module._registry.get(job_id).status)
        return real_save(*args, **kwargs)

    with patch(
        "resualign.api._jobs.save_alignment", side_effect=tracking_save
    ), patch("resualign.api.run", return_value=_report()):
        api_module._run_job(job_id)

    assert order == ["running"]  # saved while the registry job was running
    assert api_module._registry.get(job_id).status == "succeeded"
    assert (
        api_module._jobs.get_job("t1", job["job_id"])["alignment_status"]
        == "succeeded"
    )


def test_application_link_failure_does_not_flip_succeeded_job():
    resume = api_module._resumes.create_master_resume(
        "t1", "Master", "Python developer."
    )
    app_record = api_module._applications.create_application(
        "t1", "App", resume["resume_id"], jd_text="Python role"
    )
    job_id = _queue_workbench_job(
        {
            "resume_text": resume["content"],
            "jd_text": "Python role",
            "run_eval": False,
        },
        application_id=app_record["application_id"],
    )
    with patch(
        "resualign.api._applications.set_application_job",
        side_effect=RuntimeError("link db down"),
    ), patch("resualign.api.run", return_value=_report()):
        api_module._run_job(job_id)

    assert api_module._registry.get(job_id).status == "succeeded"


def test_recovery_flags_stale_alignment_when_registry_terminal():
    job = api_module._jobs.create_job(
        tenant_id="t1", title="Backend", jd_text="Python backend engineer."
    )
    config = api_module.build_config()
    reg_job = api_module._registry.create(
        {"resume_text": "r"}, config, tenant_id="t1"
    )
    api_module._registry.succeed(reg_job.job_id, {"score": 1})
    api_module._jobs.update_job(
        "t1",
        job["job_id"],
        workbench_job_id=reg_job.job_id,
        alignment_status="running",
    )

    with patch("resualign.api._run_job"):
        api_module._recover_pending_jobs()

    refreshed = api_module._jobs.get_job("t1", job["job_id"])
    assert refreshed["alignment_status"] == "failed"
    # Alignment product fields survive for a rerun.
    assert refreshed["workbench_job_id"] == reg_job.job_id


def test_recovery_flags_old_succeeded_intermediate_state():
    """Registry succeeded but alignment still 'running' (old commit order)."""
    job = api_module._jobs.create_job(
        tenant_id="t1", title="Backend", jd_text="Python backend engineer."
    )
    config = api_module.build_config()
    reg_job = api_module._registry.create(
        {"resume_text": "r"}, config, tenant_id="t1"
    )
    api_module._registry.succeed(reg_job.job_id, {"score": 1})
    api_module._jobs.update_job(
        "t1",
        job["job_id"],
        workbench_job_id=reg_job.job_id,
        alignment_status="running",
    )

    with patch("resualign.api._run_job"):
        api_module._recover_pending_jobs()

    assert (
        api_module._jobs.get_job("t1", job["job_id"])["alignment_status"]
        == "failed"
    )


def test_recovery_skips_in_flight_alignment():
    job = api_module._jobs.create_job(
        tenant_id="t1", title="Backend", jd_text="Python backend engineer."
    )
    config = api_module.build_config()
    reg_job = api_module._registry.create(
        {"resume_text": "r"}, config, tenant_id="t1"
    )
    api_module._jobs.update_job(
        "t1",
        job["job_id"],
        workbench_job_id=reg_job.job_id,
        alignment_status="running",
    )

    with patch("resualign.api._run_job"):
        api_module._recover_pending_jobs()

    # Registry job is still queued: the normal requeue path owns it.
    assert (
        api_module._jobs.get_job("t1", job["job_id"])["alignment_status"]
        == "running"
    )


def test_recovery_flags_orphan_workbench_job_id():
    job = api_module._jobs.create_job(
        tenant_id="t1", title="Backend", jd_text="Python backend engineer."
    )
    api_module._jobs.update_job(
        "t1",
        job["job_id"],
        workbench_job_id="ghost-registry-job",
        alignment_status="queued",
    )

    with patch("resualign.api._run_job"):
        api_module._recover_pending_jobs()

    assert (
        api_module._jobs.get_job("t1", job["job_id"])["alignment_status"]
        == "failed"
    )
