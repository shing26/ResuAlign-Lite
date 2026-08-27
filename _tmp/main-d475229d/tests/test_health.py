"""Tests for the /health liveness and readiness probe."""

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.cache import ContentCache
from resualign.jobs import JobRegistry

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_state(tmp_path):
    """Isolate the registry and cache touched by the health probe."""
    saved_registry = api_module._registry
    saved_cache = api_module._cache
    api_module._registry = JobRegistry(db_path=tmp_path / "health.db")
    api_module._cache = ContentCache(db_path=tmp_path / "cache.db")
    yield
    api_module._registry = saved_registry
    api_module._cache = saved_cache


def test_health_ok_reports_status_and_checks():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"db", "cache"}
    assert body["checks"]["db"]["ok"] is True
    assert isinstance(body["checks"]["db"]["detail"], str)
    assert body["checks"]["cache"]["ok"] is True
    assert isinstance(body["checks"]["cache"]["detail"], str)


def test_health_degraded_when_db_unreadable():
    class BrokenRegistry:
        def ping(self):
            return False

    api_module._registry = BrokenRegistry()

    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"]["ok"] is False
    assert body["checks"]["cache"]["ok"] is True


def test_health_degraded_when_cache_broken():
    class BrokenCache:
        def put(self, *args, **kwargs):
            raise RuntimeError("cache is full")

        def get(self, *args, **kwargs):
            return None

    api_module._cache = BrokenCache()

    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["cache"]["ok"] is False
    assert "cache is full" in body["checks"]["cache"]["detail"]
    assert body["checks"]["db"]["ok"] is True
