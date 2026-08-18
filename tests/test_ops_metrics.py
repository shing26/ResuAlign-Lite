"""Tests for the /api/ops/metrics endpoint."""

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.llm_usage import LLMUsageStore
from resualign.settings_store import SettingsStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_registry(tmp_path):
    saved = {
        "registry": api_module._registry,
        "settings": api_module._settings_store,
        "llm_usage": api_module._llm_usage,
    }
    api_module._registry = JobRegistry(db_path=tmp_path / "ops.db")
    api_module._settings_store = SettingsStore(db_path=tmp_path / "ops.db")
    api_module._llm_usage = LLMUsageStore(db_path=tmp_path / "ops.db")
    yield
    api_module._registry = saved["registry"]
    api_module._settings_store = saved["settings"]
    api_module._llm_usage = saved["llm_usage"]


def test_metrics_endpoint_shape():
    r = client.get("/api/ops/metrics")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"queue", "jobs", "llm", "uptime_seconds"}
    assert set(body["queue"]) == {"depth", "oldest_waiting_seconds"}
    assert body["queue"]["depth"] == 0
    assert body["queue"]["oldest_waiting_seconds"] is None
    assert set(body["jobs"]) == {"by_status", "failure_rate"}
    assert body["jobs"]["by_status"] == {}
    assert body["jobs"]["failure_rate"] is None
    assert set(body["llm"]) == {
        "total", "successes", "failures", "success_rate", "duration", "daily",
    }
    assert set(body["llm"]["duration"]) == {
        "count", "min_ms", "p50_ms", "p95_ms", "max_ms",
    }
    assert set(body["llm"]["daily"]) == {
        "date", "calls", "cap", "estimated_cost", "blocked", "remaining",
    }
    assert body["llm"]["daily"]["calls"] == 0
    assert body["llm"]["daily"]["blocked"] is False
    assert isinstance(body["uptime_seconds"], (int, float))


def test_metrics_queue_depth_and_oldest_waiting(tmp_path):
    now = [1000.0]
    registry = JobRegistry(db_path=tmp_path / "clock.db", clock=lambda: now[0])
    api_module._registry = registry

    first = registry.create({"a": 1}, None)
    now[0] += 12.0
    second = registry.create({"b": 2}, None)

    body = client.get("/api/ops/metrics").json()
    assert body["queue"]["depth"] == 2
    assert body["queue"]["oldest_waiting_seconds"] == 12.0

    registry.claim_running(first.job_id)
    # queued + running both count towards the depth.
    assert client.get("/api/ops/metrics").json()["queue"]["depth"] == 2

    registry.succeed(first.job_id, {"score": 1})
    registry.succeed(second.job_id, {"score": 1})
    body = client.get("/api/ops/metrics").json()
    assert body["queue"]["depth"] == 0
    assert body["queue"]["oldest_waiting_seconds"] is None


def test_metrics_job_failure_rate():
    registry = api_module._registry
    ok = registry.create({"a": 1}, None)
    bad = registry.create({"b": 2}, None)
    registry.succeed(ok.job_id, {"score": 1})
    registry.fail(bad.job_id, "boom")

    body = client.get("/api/ops/metrics").json()
    assert body["jobs"]["by_status"] == {"succeeded": 1, "failed": 1}
    assert body["jobs"]["failure_rate"] == 0.5


def test_metrics_llm_aggregates_current_snapshot():
    """The endpoint surfaces whatever the in-process LLM stats hold."""
    from resualign.llm import llm_metrics_snapshot

    body = client.get("/api/ops/metrics").json()
    snapshot = llm_metrics_snapshot()
    assert body["llm"]["total"] == snapshot["total"]
    assert body["llm"]["successes"] == snapshot["successes"]
    assert body["llm"]["failures"] == snapshot["failures"]
    assert body["llm"]["duration"] == snapshot["duration"]
    assert set(body["llm"]["daily"]) == {
        "date", "calls", "cap", "estimated_cost", "blocked", "remaining",
    }
