"""ADR-0065: ranking HTTP surface is registered and ordered correctly."""

from __future__ import annotations


def _paths():
    import resualign.api as api_module

    return [route.path for route in api_module.app.routes]


def test_ranking_routes_are_registered():
    paths = _paths()
    assert "/api/jobs/recommended" in paths
    assert "/api/jobs/{job_id}/best-resume" in paths
    assert "/api/jobs/embeddings/status" in paths
    assert "/api/jobs/embeddings/rebuild" in paths


def test_recommended_route_precedes_job_detail():
    """Otherwise /api/jobs/{job_id} would swallow /api/jobs/recommended."""
    paths = _paths()
    assert paths.index("/api/jobs/recommended") < paths.index("/api/jobs/{job_id}")
