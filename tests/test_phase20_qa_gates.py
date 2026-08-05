"""T9 QA gates: concurrency claims, SSE ordering, and fallback polling."""

from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    EvalScore,
    GapReport,
    JDProfile,
    Report,
    ResuAlignConfig,
    TailoredResume,
)
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
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
    db_path = tmp_path / "phase20.db"
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
        json={"email": "phase20@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "phase20@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def test_concurrent_worker_wal_claims(tmp_path):
    """Several threads writing the same SQLite file must all succeed."""
    store = JobLibraryStore(db_path=tmp_path / "workers.db")
    errors: list[Exception] = []
    created: list[str] = []
    barrier = threading.Barrier(8)

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=5)
            job = store.create_job(
                tenant_id="tenant-1",
                title=f"Worker {index}",
                jd_text=f"JD for worker {index}",
                status="draft",
            )
            created.append(job["job_id"])
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(created) == 8
    assert len(store.list_jobs("tenant-1", limit=100)) == 8


def test_sse_event_order_matches_session_snapshot():
    """Replayed SSE history must agree with the final workstation state."""
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

    events: list[tuple[str, dict]] = []
    with client.stream(
        "GET",
        f"/api/workbench/session/{session_id}/events?replay=1",
        headers=_auth_headers(),
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event: "):
                name = line.split(" ", 1)[1]
                events.append((name, {}))
            elif line.startswith("data: "):
                if events:
                    data = line[6:]
                    events[-1] = (events[-1][0], data)

    names = [name for name, _ in events]
    assert "job.stage" in names
    assert "job.gap_ready" in names
    gap_index = names.index("job.gap_ready")
    gap_data = events[gap_index][1]
    assert gap_data
    assert '"jd_profile"' in gap_data
    assert final["jd"]["profile"]["must_have_skills"] == ["Python"]
    assert final["gap"]["status"] == "blocked"


def test_session_polling_etag_fallback():
    """Polling with If-None-Match returns 304 until state changes."""
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


def test_workbench_result_updates_session_and_emits_job_result():
    """A completed workbench run must refresh the session alignment."""
    with patch("resualign.api._classify_job", return_value={}):
        job = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer with FastAPI.",
            },
            headers=_auth_headers(),
        ).json()
    resume = client.post(
        "/api/master-resumes",
        json={
            "title": "Master Resume",
            "content": "Python developer with FastAPI experience.",
        },
        headers=_auth_headers(),
    ).json()

    session = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    ).json()
    assert session["alignment"]["status"] == "idle"

    diff = DiffItem(
        type="modify",
        original="Python developer with FastAPI experience.",
        proposed="Python developer with FastAPI async endpoints.",
        reason="JD match",
        confidence="high",
        provenance="Python developer with FastAPI experience.",
    )
    report = Report(
        score=88,
        skills=["Python", "FastAPI"],
        model="test-model",
        jd_profile=JDProfile(must_have_skills=["Python", "FastAPI"]),
        gap_report=GapReport(missing_keywords=["async"], strength_matches=["Python"]),
        tailored_resume=TailoredResume(
            sections={"experience": "Python developer with FastAPI async endpoints."},
            diffs=[diff],
        ),
        diffs=[diff],
        eval_score=EvalScore(
            jd_match_score=90,
            improvement=8,
            hallucination_detected=False,
            hallucination_details=[],
            gap_coverage=0.9,
        ),
    )

    with patch(
        "resualign.api.build_config", return_value=_config()
    ), patch("resualign.api.run", return_value=report):
        queued = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
        api_module._run_job(queued.json()["job_id"])

    refreshed = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    ).json()
    assert refreshed["alignment"]["status"] == "succeeded"
    assert len(refreshed["alignment"]["diffs"]) == 1
    assert refreshed["alignment"]["diffs"][0]["original"].startswith(
        "Python developer"
    )
    assert refreshed["job"]["alignment_status"] == "succeeded"
    assert refreshed["gap"]["status"] in {"ready", "blocked"}

    events: list[str] = []
    with client.stream(
        "GET",
        f"/api/workbench/session/{session['session_id']}/events?replay=1",
        headers=_auth_headers(),
    ) as stream:
        for line in stream.iter_lines():
            if line.startswith("event: "):
                events.append(line.split(" ", 1)[1])
    assert "job.result" in events
    assert "tailor.diff" in events
    assert events.index("tailor.diff") < events.index("job.result")
