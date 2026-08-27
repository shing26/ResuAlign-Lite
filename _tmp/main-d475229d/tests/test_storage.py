"""Tests for SQLite persistence and restart recovery of the job registry."""

from resualign.jobs import JobRegistry, default_job_db_path


class _Config:
    pass


def _store(db_path, now):
    return JobRegistry(db_path=db_path, clock=lambda: now[0])


def test_persistence_across_store_instances(tmp_path):
    db_path = tmp_path / "jobs.db"
    now = [1000.0]
    first = _store(db_path, now)
    job = first.create({"resume_text": "Python developer."}, _Config())

    now[0] = 1000.5
    first.mark_running(job.job_id)
    now[0] = 1001.0
    first.succeed(job.job_id, {"score": 82})

    second = _store(db_path, now)
    stored = second.get(job.job_id)

    assert stored is not None
    assert stored.status == "succeeded"
    assert stored.result == {"score": 82}
    assert stored.payload is None
    assert stored.config is None
    assert second.snapshot(job.job_id)["status"] == "succeeded"


def test_restart_recovery_keeps_pending_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    now = [1000.0]
    first = _store(db_path, now)

    queued = first.create({"resume_text": "queued"}, _Config())
    running = first.create({"resume_text": "running"}, _Config())
    first.mark_running(running.job_id)
    done = first.create({"resume_text": "done"}, _Config())
    first.succeed(done.job_id, {"score": 90})

    second = JobRegistry(db_path=db_path, clock=lambda: 1500.0)

    recovered_queued = second.get(queued.job_id)
    assert recovered_queued.status == "queued"
    assert recovered_queued.error is None
    assert second.get_payload(queued.job_id) is not None

    recovered_running = second.get(running.job_id)
    assert recovered_running.status == "running"
    assert recovered_running.error is None

    assert second.pending_job_ids() == [queued.job_id, running.job_id]

    kept = second.get(done.job_id)
    assert kept.status == "succeeded"
    assert kept.error is None
    assert kept.finished_at == 1000.0


def test_store_creates_db_directory(tmp_path):
    db_path = tmp_path / "nested" / "data" / "jobs.db"
    reg = JobRegistry(db_path=db_path)

    reg.create({"resume_text": "Python developer."}, _Config())

    assert db_path.exists()


def test_default_db_path_honors_env_override(monkeypatch, tmp_path):
    expected = tmp_path / "custom" / "jobs.db"
    monkeypatch.setenv("RESUALIGN_JOB_DB", str(expected))

    assert default_job_db_path() == expected
