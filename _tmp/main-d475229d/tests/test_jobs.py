"""Tests for the SQLite-backed job registry used by the async API."""

import pytest

from resualign.jobs import JobRegistry


class _Config:
    pass


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "jobs.db"


def _registry(now, db_path, max_jobs=3, ttl_seconds=60):
    return JobRegistry(
        db_path=db_path,
        max_jobs=max_jobs,
        ttl_seconds=ttl_seconds,
        clock=lambda: now[0],
    )


def test_create_returns_queued_job_with_payload(db_path):
    now = [100.0]
    reg = _registry(now, db_path)
    cfg = _Config()

    job = reg.create(
        {"resume_text": "resume", "jd_url": "https://example.com/job"},
        cfg,
    )

    assert job.job_id
    assert job.status == "queued"
    assert job.payload == {
        "resume_text": "resume",
        "jd_url": "https://example.com/job",
    }
    assert job.config is cfg
    assert job.created_at == 100.0
    assert len(reg) == 1


def test_create_persists_application_id(db_path):
    now = [100.0]
    reg = _registry(now, db_path)
    job = reg.create(
        {"resume_text": "resume"},
        _Config(),
        application_id="app-1",
    )

    payload = reg.get_payload(job.job_id)
    assert payload is not None
    assert payload[2] == "app-1"


def test_registry_cap_evicts_oldest_finished_job(db_path):
    now = [100.0]
    reg = _registry(now, db_path, max_jobs=2, ttl_seconds=3600)

    first = reg.create({"resume_text": "first"}, _Config())
    reg.succeed(first.job_id, {"score": 80})
    second = reg.create({"resume_text": "second"}, _Config())
    now[0] += 1
    third = reg.create({"resume_text": "third"}, _Config())

    assert len(reg) == 2
    assert reg.get(first.job_id) is None
    assert reg.get(second.job_id) is not None
    assert reg.get(third.job_id) is not None


def test_registry_cap_never_evicts_active_jobs(db_path):
    now = [100.0]
    reg = _registry(now, db_path, max_jobs=2, ttl_seconds=3600)

    reg.create({"resume_text": "first"}, _Config())
    reg.create({"resume_text": "second"}, _Config())
    reg.create({"resume_text": "third"}, _Config())

    assert len(reg) == 3
    assert reg.get(reg.pending_job_ids()[0]) is not None


def test_ttl_expiry_removes_job_on_access(db_path):
    now = [100.0]
    reg = _registry(now, db_path, ttl_seconds=60)
    job = reg.create({"resume_text": "resume"}, _Config())

    assert reg.get(job.job_id) is not None

    now[0] += 61

    assert reg.get(job.job_id) is None
    assert reg.snapshot(job.job_id) is None
    assert len(reg) == 0


def test_snapshot_tracks_stage_elapsed_and_success(db_path):
    now = [100.0]
    reg = _registry(now, db_path)
    job = reg.create({"resume_text": "resume"}, _Config())

    assert reg.snapshot(job.job_id)["status"] == "queued"
    assert reg.snapshot(job.job_id)["elapsed_seconds"] == 0.0

    now[0] = 100.5
    reg.mark_running(job.job_id)
    reg.update_progress(job.job_id, "jd_profile", "Extracting JD profile...")
    now[0] = 101.0

    running = reg.snapshot(job.job_id)
    assert running["status"] == "running"
    assert running["stage"] == "jd_profile"
    assert running["message"] == "Extracting JD profile..."
    assert running["elapsed_seconds"] == 0.5
    assert running["result"] is None
    assert running["error"] is None

    now[0] = 101.5
    reg.succeed(job.job_id, {"score": 82})

    done = reg.snapshot(job.job_id)
    assert done["status"] == "succeeded"
    assert done["result"] == {"score": 82}
    assert done["error"] is None
    assert done["elapsed_seconds"] == 1.0


def test_failed_snapshot_only_exposes_error(db_path):
    now = [100.0]
    reg = _registry(now, db_path)
    job = reg.create({"resume_text": "resume"}, _Config())

    now[0] = 100.25
    reg.mark_running(job.job_id)
    now[0] = 100.75
    reg.fail(job.job_id, "boom")

    failed = reg.snapshot(job.job_id)
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"
    assert failed["result"] is None
    assert failed["elapsed_seconds"] == 0.5


def test_delete_removes_job_and_payload(db_path):
    now = [100.0]
    reg = _registry(now, db_path)
    job = reg.create({"resume_text": "resume"}, _Config())

    assert reg.delete(job.job_id) is True
    assert reg.get(job.job_id) is None
    assert reg.get_payload(job.job_id) is None
    assert len(reg) == 0
    assert reg.delete(job.job_id) is False


def test_delete_scoped_to_tenant(db_path):
    now = [100.0]
    reg = _registry(now, db_path)
    job = reg.create({"resume_text": "resume"}, _Config(), tenant_id="tenant-a")

    assert reg.delete(job.job_id, tenant_id="tenant-b") is False
    assert reg.get(job.job_id) is not None
    assert reg.delete(job.job_id, tenant_id="tenant-a") is True
    assert reg.get(job.job_id) is None
