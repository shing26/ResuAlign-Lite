"""ADR-0065: ranking HTTP surface is registered and ordered correctly.

Uses the jobs router's own route table (every entry is an APIRoute with .path)
instead of app.routes: FastAPI 0.115+ may include _IncludedRouter objects there,
and CI runs a different FastAPI version than some dev machines.
"""

from __future__ import annotations


def _router_paths() -> list[str]:
    from resualign.api.routers.jobs import router

    return [route.path for route in router.routes if getattr(route, "path", None)]


def test_ranking_routes_are_registered():
    paths = _router_paths()
    assert "/api/jobs/recommended" in paths
    assert "/api/jobs/{job_id}/best-resume" in paths
    assert "/api/jobs/embeddings/status" in paths
    assert "/api/jobs/embeddings/rebuild" in paths


def test_recommended_route_precedes_job_detail():
    """Otherwise /api/jobs/{job_id} would swallow /api/jobs/recommended."""
    paths = _router_paths()
    assert paths.index("/api/jobs/recommended") < paths.index("/api/jobs/{job_id}")
