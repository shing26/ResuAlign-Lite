"""T3: workstation session orchestration, SSE event bus, and polling."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import GapReport, JDProfile, ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)


client = TestClient(app)
_auth_cache = None


def _config(api_key: str = "sk-test") -> ResuAlignConfig:
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
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
            "_PERSONAL_MODE",
            "_payloads",
        )
    }
    db_path = tmp_path / "session.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._session_store = api_module._workbench_service.WorkstationSessionStore()
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "session@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "session@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job() -> dict:
    with patch("resualign.api._classify_job", return_value={}):
        return client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer with FastAPI.",
            },
            headers=_auth_headers(),
        ).json()


def _create_resume() -> dict:
    return client.post(
        "/api/master-resumes",
        json={
            "title": "Master Resume",
            "content": "Python developer with FastAPI experience.",
        },
        headers=_auth_headers(),
    ).json()


def test_init_raw_jd_returns_202_state():
    with patch("resualign.api.build_config", return_value=_config(api_key="")):
        r = client.post(
            "/api/workbench/session/init",
            json={"raw_jd": "Backend engineer with Redis caching."},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    state = r.json()
    assert state["session_id"]
    assert state["status"] == "ready"
    assert state["job"]["jd_text"] == "Backend engineer with Redis caching."
    assert state["jd"]["status"] == "ready"
    assert state["gap"]["status"] == "blocked"
    assert state["meta"]["event_url"].endswith("/events")
    assert state["meta"]["etag"]


def test_init_url_queues_crawl_without_blocking():
    with patch(
        "resualign.api.services.workbench._run_session_pipeline"
    ) as pipeline_mock:
        r = client.post(
            "/api/workbench/session/init",
            json={"jd_url": "https://example.com/jobs/123"},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    state = r.json()
    assert state["status"] == "initializing"
    assert state["job"] is None
    assert state["jd"]["status"] == "queued"
    assert state["crawl"]["status"] == "queued"
    assert state["crawl"]["crawl_id"]
    pipeline_mock.assert_called_once()


def test_init_requires_raw_jd_or_url():
    r = client.post(
        "/api/workbench/session/init",
        json={},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_init_duplicate_raw_jd_reopens_existing_job():
    """Pasting the same JD twice must open the existing job, not 409."""
    payload = {"raw_jd": "Duplicate backend engineer role with Redis."}
    with patch("resualign.api.build_config", return_value=_config(api_key="")):
        first = client.post(
            "/api/workbench/session/init",
            json=payload,
            headers=_auth_headers(),
        )
        second = client.post(
            "/api/workbench/session/init",
            json=payload,
            headers=_auth_headers(),
        )
    assert first.status_code == 202
    assert second.status_code == 202
    first_state = first.json()
    second_state = second.json()
    assert second_state["job"]["job_id"] == first_state["job"]["job_id"]
    assert second_state["session_id"]


def test_init_idempotency_key_reuses_session():
    payload = {
        "raw_jd": "Backend engineer.",
        "idempotency_key": "session-key-1",
    }
    with patch("resualign.api.build_config", return_value=_config(api_key="")):
        first = client.post(
            "/api/workbench/session/init", json=payload, headers=_auth_headers()
        )
        second = client.post(
            "/api/workbench/session/init", json=payload, headers=_auth_headers()
        )
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["session_id"] == second.json()["session_id"]


def test_get_workspace_session_is_read_only():
    job = _create_job()
    with patch("resualign.api.profile_jd") as profile_mock, patch(
        "resualign.api.profile_and_gaps"
    ) as gaps_mock:
        r = client.get(
            f"/api/workspace/session/{job['job_id']}",
            headers=_auth_headers(),
        )
    assert r.status_code == 200
    state = r.json()
    assert state["job"]["job_id"] == job["job_id"]
    assert state["jd"]["status"] == "ready"
    assert state["meta"]["event_url"]
    profile_mock.assert_not_called()
    gaps_mock.assert_not_called()


def test_get_workspace_session_not_found():
    r = client.get(
        "/api/workspace/session/unknown-job",
        headers=_auth_headers(),
    )
    assert r.status_code == 404


def test_analyze_library_job_session_queues_pipeline_once():
    job = _create_job()
    state = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    ).json()
    session_id = state["session_id"]
    with patch(
        "resualign.api.services.workbench._run_session_pipeline"
    ) as pipeline_mock:
        r = client.post(
            f"/api/workbench/session/{session_id}/analyze",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["jd"]["status"] == "queued"
        assert body["gap"]["status"] == "queued"

        # A second call while queued must not spawn another worker.
        again = client.post(
            f"/api/workbench/session/{session_id}/analyze",
            headers=_auth_headers(),
        )
        assert again.status_code == 200
        time.sleep(0.1)
    assert pipeline_mock.call_count == 1


def test_analyze_is_noop_when_profile_ready():
    job = _create_job()
    state = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    ).json()
    session_id = state["session_id"]
    api_module._session_store.update(
        session_id,
        {"jd": {"profile": {"title": "Backend"}, "status": "ready", "error": None}},
    )
    with patch(
        "resualign.api.services.workbench._run_session_pipeline"
    ) as pipeline_mock:
        r = client.post(
            f"/api/workbench/session/{session_id}/analyze",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        assert r.json()["jd"]["profile"] == {"title": "Backend"}
    pipeline_mock.assert_not_called()


def test_analyze_requires_jd_text():
    job = _create_job()
    state = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    ).json()
    session_id = state["session_id"]
    api_module._session_store.update(
        session_id,
        {"job": {**api_module._session_store.get(session_id)["job"], "jd_text": ""}},
    )
    r = client.post(
        f"/api/workbench/session/{session_id}/analyze",
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_polling_etag_returns_304():
    with patch("resualign.api.build_config", return_value=_config(api_key="")):
        state = client.post(
            "/api/workbench/session/init",
            json={"raw_jd": "Backend engineer."},
            headers=_auth_headers(),
        ).json()
    etag = state["meta"]["etag"]
    same = client.get(
        f"/api/workbench/session/{state['session_id']}",
        headers={**_auth_headers(), "If-None-Match": etag},
    )
    assert same.status_code == 304
    stale = client.get(
        f"/api/workbench/session/{state['session_id']}",
        headers={**_auth_headers(), "If-None-Match": '"stale-etag"'},
    )
    assert stale.status_code == 200


def _event_names(stream) -> list[str]:
    names: list[str] = []
    for line in stream.iter_lines():
        if line.startswith("event: "):
            names.append(line.split(" ", 1)[1])
            if len(names) >= 3:
                break
    return names


def test_sse_streams_replayed_history():
    with patch("resualign.api.build_config", return_value=_config(api_key="")):
        state = client.post(
            "/api/workbench/session/init",
            json={"raw_jd": "Backend engineer."},
            headers=_auth_headers(),
        ).json()
    session_id = state["session_id"]
    api_module._session_store.emit(
        session_id, "job.stage", {"stage": "classifying", "message": "Classifying"}
    )
    api_module._session_store.emit(
        session_id,
        "tailor.diff",
        {"diff_id": "d1", "proposed": "Redis caching"},
    )
    with client.stream(
        "GET",
        f"/api/workbench/session/{session_id}/events?replay=1",
        headers=_auth_headers(),
    ) as stream:
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        names = _event_names(stream)
    assert "job.stage" in names
    assert "tailor.diff" in names

    # A second subscriber replays the same history (idempotent cursor).
    with client.stream(
        "GET",
        f"/api/workbench/session/{session_id}/events?replay=1",
        headers=_auth_headers(),
    ) as stream:
        names = _event_names(stream)
    assert "job.stage" in names
    assert "tailor.diff" in names


def test_session_pipeline_emits_gap_ready():
    resume = _create_resume()
    profile = JDProfile(
        must_have_skills=["Python"],
        nice_to_have_skills=["Redis"],
        business_scenarios=["high concurrency"],
    )
    gap = GapReport(
        missing_keywords=["Redis"],
        strength_matches=["Python"],
    )
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api._classify_job",
        return_value={
            "job_function": "后端",
            "seniority": "中级",
            "tech_tags": ["Python"],
        },
    ), patch(
        "resualign.api.profile_and_gaps", return_value=(profile, gap)
    ):
        state = client.post(
            "/api/workbench/session/init",
            json={
                "raw_jd": "Backend engineer with Redis caching.",
                "master_resume_id": resume["resume_id"],
            },
            headers=_auth_headers(),
        ).json()

        session_id = state["session_id"]
        deadline = time.time() + 10
        final = state
        while time.time() < deadline:
            final = client.get(
                f"/api/workbench/session/{session_id}",
                headers=_auth_headers(),
            ).json()
            if final["jd"].get("profile") is not None:
                break
            time.sleep(0.05)
    assert final["jd"]["status"] == "ready"
    assert final["jd"]["profile"]["must_have_skills"] == ["Python"]
    assert final["gap"]["status"] == "ready"
    assert final["gap"]["gap_report"]["missing_keywords"] == ["Redis"]
    assert final["job"]["classification_pending"] == 0
    assert final["job"]["job_function"] == "后端"
    assert final["status"] == "ready"
    tenant = final["job"]["tenant_id"]
    stored = api_module._jobs.get_job(tenant, final["job"]["job_id"])
    assert stored is not None
    assert (stored.get("jd_profile") or {}).get("must_have_skills") == ["Python"]
    assert (stored.get("gap_report") or {}).get("missing_keywords") == ["Redis"]
    assert stored.get("match_score") is not None


def test_session_pipeline_jd_only_sets_blocked_gap():
    """JD-only session init must not crash when no resume is pinned."""
    profile = JDProfile(
        must_have_skills=["Python"],
        nice_to_have_skills=["Redis"],
        business_scenarios=["backend"],
    )
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api._classify_job",
        return_value={
            "job_function": "后端",
            "seniority": "中级",
            "tech_tags": ["Python"],
        },
    ), patch("resualign.api.profile_jd", return_value=profile):
        state = client.post(
            "/api/workbench/session/init",
            json={"raw_jd": "Backend engineer with Redis caching."},
            headers=_auth_headers(),
        ).json()

        session_id = state["session_id"]
        deadline = time.time() + 10
        final = state
        while time.time() < deadline:
            final = client.get(
                f"/api/workbench/session/{session_id}",
                headers=_auth_headers(),
            ).json()
            if final["jd"].get("profile") is not None:
                break
            time.sleep(0.05)
    assert final["status"] == "ready"
    assert final["jd"]["status"] == "ready"
    assert final["jd"]["error"] is None
    assert final["jd"]["profile"]["must_have_skills"] == ["Python"]
    assert final["gap"]["status"] == "blocked"
    assert final["gap"]["gap_report"] is None
    assert final["gap"]["score"] is None
