"""Job lifecycle events emitted by JobRegistry via log_event."""

import json
import logging

import pytest

from resualign.jobs import JobRegistry


class _CaptureHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def captured():
    logger = logging.getLogger("resualign.jobs")
    saved_handlers = list(logger.handlers)
    saved_propagate = logger.propagate
    saved_level = logger.level
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    handler = _CaptureHandler()
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    logger.handlers[:] = saved_handlers
    logger.propagate = saved_propagate
    logger.setLevel(saved_level)


@pytest.fixture
def registry(tmp_path):
    return JobRegistry(db_path=tmp_path / "events.db")


def _events(handler):
    return [json.loads(record.getMessage()) for record in handler.records]


def test_queued_event_on_create(registry, captured):
    job = registry.create({"resume": "text"}, None, tenant_id="t1")

    events = _events(captured)
    assert len(events) == 1
    assert events[0]["event"] == "job.queued"
    assert events[0]["extra"] == {"job_id": job.job_id, "tenant_id": "t1"}


def test_claimed_event_on_claim(registry, captured):
    job = registry.create({}, None)
    assert registry.claim_running(job.job_id) is True

    events = _events(captured)
    assert [e["event"] for e in events] == ["job.queued", "job.claimed"]
    assert events[1]["extra"] == {"job_id": job.job_id}


def test_no_claimed_event_on_double_claim(registry, captured):
    job = registry.create({}, None)
    registry.claim_running(job.job_id)
    assert registry.claim_running(job.job_id) is False

    events = _events(captured)
    assert [e["event"] for e in events] == ["job.queued", "job.claimed"]


def test_stage_event_on_progress(registry, captured):
    job = registry.create({}, None)
    registry.claim_running(job.job_id)
    registry.update_progress(job.job_id, "gap_report", "Matching gaps...")

    events = _events(captured)
    assert [e["event"] for e in events] == [
        "job.queued", "job.claimed", "job.stage",
    ]
    assert events[2]["extra"] == {
        "job_id": job.job_id,
        "stage": "gap_report",
        "message": "Matching gaps...",
    }


def test_no_stage_event_when_job_not_running(registry, captured):
    job = registry.create({}, None)
    registry.update_progress(job.job_id, "gap_report", "ignored")

    events = _events(captured)
    assert [e["event"] for e in events] == ["job.queued"]


def test_finished_event_on_succeed(registry, captured):
    job = registry.create({}, None)
    registry.claim_running(job.job_id)
    registry.succeed(job.job_id, {"score": 90})

    events = _events(captured)
    assert events[-1]["event"] == "job.finished"
    assert events[-1]["extra"] == {"job_id": job.job_id, "outcome": "succeeded"}


def test_finished_event_on_fail(registry, captured):
    job = registry.create({}, None)
    registry.fail(job.job_id, "Analysis failed")

    events = _events(captured)
    assert events[-1]["event"] == "job.finished"
    assert events[-1]["extra"] == {
        "job_id": job.job_id,
        "outcome": "failed",
        "error": "Analysis failed",
    }


def test_finished_event_on_cancel(registry, captured):
    job = registry.create({}, None)
    assert registry.cancel(job.job_id) is True

    events = _events(captured)
    assert events[-1]["event"] == "job.finished"
    assert events[-1]["extra"] == {"job_id": job.job_id, "outcome": "canceled"}


def test_requeued_event_on_recovery(registry, captured):
    job = registry.create({}, None)
    registry.claim_running(job.job_id)
    assert registry.requeue_interrupted(job.job_id) is True

    events = _events(captured)
    assert events[-1]["event"] == "job.requeued"
    assert events[-1]["extra"] == {"job_id": job.job_id}
