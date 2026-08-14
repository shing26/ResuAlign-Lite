"""API tests for master resume management and the application workspace,
plus the Single-Job Workspace endpoints."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.models import (
    DiffItem,
    GapReport,
    JDProfile,
    Report,
    ResuAlignConfig,
    TailoredResume,
)
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None
_other_cache = None


def _config(api_key="sk-test"):
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
    global _other_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "import_batches": getattr(api_module, "_import_batches", {}),
        "settings": getattr(api_module, "_settings_store", None),
    }
    db_path = tmp_path / "workbench.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    _other_cache = None
    yield
    api_module._registry = saved["registry"]
    api_module._users = saved["users"]
    api_module._resumes = saved["resumes"]
    api_module._applications = saved["applications"]
    api_module._jobs = saved["jobs"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    api_module._payloads = saved["payloads"]
    api_module._import_batches = saved["import_batches"]
    api_module._settings_store = saved["settings"]
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    _other_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "tester@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "tester@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def _other_headers():
    global _other_cache
    if _other_cache is not None:
        return _other_cache
    r = client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "other-password"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "other-password"},
    )
    assert r.status_code == 200
    _other_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _other_cache


def _create_resume(title="Master Resume", content="Python developer."):
    r = client.post(
        "/api/master-resumes",
        json={"title": title, "content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def test_master_resume_crud_and_versioning():
    created = _create_resume()
    resume_id = created["resume_id"]
    assert created["current_version"] == 1

    r = client.get(f"/api/master-resumes/{resume_id}", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["content"] == "Python developer."
    assert len(r.json()["versions"]) == 1

    r = client.patch(
        f"/api/master-resumes/{resume_id}",
        json={"content": "Python developer. FastAPI."},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["current_version"] == 2
    assert r.json()["content"] == "Python developer. FastAPI."

    r = client.post(
        f"/api/master-resumes/{resume_id}/rollback",
        json={"version": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["current_version"] == 1
    assert r.json()["content"] == "Python developer."

    r = client.get("/api/master-resumes", headers=_auth_headers())
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.delete(
        f"/api/master-resumes/{resume_id}", headers=_auth_headers()
    )
    assert r.status_code == 204
    r = client.get(f"/api/master-resumes/{resume_id}", headers=_auth_headers())
    assert r.status_code == 404


def test_resume_upload_parse_txt():
    content = (
        b"Python developer resume.\n"
        b"Python developer with 5 years of experience in "
        b"backend development.\n"
    )
    r = client.post(
        "/api/master-resumes/parse",
        files={"file": ("resume.txt", content, "text/plain")},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Python developer resume."
    assert "Python developer resume." in body["content"]
    assert body["size"] > 0


def test_resume_upload_rejects_unsupported_extension():
    r = client.post(
        "/api/master-resumes/parse",
        files={"file": ("resume.exe", b"binary", "application/octet-stream")},
        headers=_auth_headers(),
    )
    assert r.status_code == 415
    assert "Unsupported format" in r.json()["detail"]


def test_resume_upload_rejects_empty_file():
    r = client.post(
        "/api/master-resumes/parse",
        files={"file": ("empty.txt", b"", "text/plain")},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_resume_upload_requires_file():
    r = client.post("/api/master-resumes/parse", headers=_auth_headers())
    assert r.status_code == 422


def test_master_resume_isolation_between_users():
    created = _create_resume()

    r = client.get(
        f"/api/master-resumes/{created['resume_id']}",
        headers=_other_headers(),
    )
    assert r.status_code == 404

    r = client.get("/api/master-resumes", headers=_other_headers())
    assert r.json() == []


def test_application_create_list_detail_run():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Backend at Acme",
                "master_resume_id": resume["resume_id"],
                "jd_text": "Looking for a Python backend engineer.",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 201
    app = r.json()
    assert app["title"] == "Backend at Acme"
    assert app["resume_snapshot"] == "Python developer."
    assert app["resume_version"] == 1
    assert app["status"] == "draft"

    r = client.get("/api/applications", headers=_auth_headers())
    assert len(r.json()) == 1

    app_id = app["application_id"]
    r = client.get(f"/api/applications/{app_id}", headers=_auth_headers())
    assert r.status_code == 200
    assert r.json()["latest_job_id"] is None

    report = Report(score=81, skills=["Python"], model="test-model")
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/applications/{app_id}/run",
            headers=_auth_headers(),
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        queued_app = client.get(
            f"/api/applications/{app_id}", headers=_auth_headers()
        ).json()
        assert queued_app["status"] == "running"
        assert queued_app["latest_job_id"] == job_id

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(job_id)

    app_detail = client.get(
        f"/api/applications/{app_id}", headers=_auth_headers()
    ).json()
    assert app_detail["latest_job_id"] == job_id
    assert app_detail["status"] in ("running", "succeeded")

    job = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert job["status"] == "succeeded"
    assert job["result"]["score"] == 81


def test_application_run_recovery_keeps_application_link():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Recovery App",
                "master_resume_id": resume["resume_id"],
                "jd_text": "Python backend engineer.",
            },
            headers=_auth_headers(),
        )
    app_id = r.json()["application_id"]

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/applications/{app_id}/run",
            headers=_auth_headers(),
        )
    job_id = r.json()["job_id"]

    # Simulate a restart: in-memory payload is gone, SQLite payload remains.
    api_module._payloads.clear()
    report = Report(score=80, skills=["Python"], model="test-model")
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(job_id)

    app_detail = client.get(
        f"/api/applications/{app_id}", headers=_auth_headers()
    ).json()
    assert app_detail["status"] == "succeeded"


def test_cancel_application_run_resets_application_status():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Cancel App",
                "master_resume_id": resume["resume_id"],
                "jd_text": "Python backend engineer.",
            },
            headers=_auth_headers(),
        )
        app_id = r.json()["application_id"]
        r = client.post(
            f"/api/applications/{app_id}/run",
            headers=_auth_headers(),
        )
        job_id = r.json()["job_id"]

    r = client.post(
        f"/api/jobs/{job_id}/cancel",
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    app_detail = client.get(
        f"/api/applications/{app_id}", headers=_auth_headers()
    ).json()
    assert app_detail["status"] == "draft"


def test_application_uses_pinned_resume_snapshot_after_master_update():
    resume = _create_resume(content="Version one content.")
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Backend at Acme",
                "master_resume_id": resume["resume_id"],
                "jd_text": "Python backend engineer.",
            },
            headers=_auth_headers(),
        )
    app = r.json()
    assert app["resume_snapshot"] == "Version one content."

    r = client.patch(
        f"/api/master-resumes/{resume['resume_id']}",
        json={"content": "Version two content."},
        headers=_auth_headers(),
    )
    assert r.json()["current_version"] == 2

    detail = client.get(
        f"/api/applications/{app['application_id']}", headers=_auth_headers()
    ).json()
    assert detail["resume_snapshot"] == "Version one content."
    assert detail["resume_version"] == 1

    report = Report(score=80, skills=["Python"], model="test-model")
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ) as mock_run:
        r = client.post(
            f"/api/applications/{app['application_id']}/run",
            headers=_auth_headers(),
        )
        api_module._run_job(r.json()["job_id"])

    assert mock_run.call_args.args[1] == "Version one content."


def test_application_isolation_between_users():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Backend at Acme",
                "master_resume_id": resume["resume_id"],
            },
            headers=_auth_headers(),
        )
    app_id = r.json()["application_id"]

    r = client.get(f"/api/applications/{app_id}", headers=_other_headers())
    assert r.status_code == 404
    other_list = client.get(
        "/api/applications", headers=_other_headers()
    ).json()
    assert other_list == []


def test_application_update_and_delete():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Backend at Acme",
                "master_resume_id": resume["resume_id"],
                "jd_text": "old jd",
            },
            headers=_auth_headers(),
        )
    app_id = r.json()["application_id"]

    r = client.patch(
        f"/api/applications/{app_id}",
        json={"title": "Backend at Acme 2", "jd_text": "new jd"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Backend at Acme 2"
    assert r.json()["jd_text"] == "new jd"

    r = client.delete(f"/api/applications/{app_id}", headers=_auth_headers())
    assert r.status_code == 204
    deleted = client.get(
        f"/api/applications/{app_id}", headers=_auth_headers()
    )
    assert deleted.status_code == 404


def test_application_requires_existing_resume():
    r = client.post(
        "/api/applications",
        json={"title": "Backend", "master_resume_id": "missing"},
        headers=_auth_headers(),
    )
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Single-Job Workspace endpoints
# ---------------------------------------------------------------------------


def _create_library_job(jd_text="Python backend 20-30K", **overrides):
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": jd_text,
                "company": "Acme",
                "location": "Shanghai",
                **overrides,
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 201
    return r.json()


def _finished_report():
    diff = DiffItem(
        type="modify",
        original="Python developer.",
        proposed="Python developer with Redis caching.",
        reason="JD match",
        confidence="high",
        provenance="Python developer.",
    )
    return Report(
        score=80,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(must_have_skills=["Python"]),
        gap_report=GapReport(missing_keywords=["Redis"]),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI services with Redis"},
            diffs=[diff],
        ),
        diffs=[diff],
    )


def test_workbench_run_polls_and_returns_report():
    job = _create_library_job()
    resume = _create_resume()

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={
                "master_resume_id": resume["resume_id"],
                "granularity": "coarse",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    assert r.json()["workbench"] is True
    analysis_job_id = r.json()["job_id"]

    report = _finished_report()
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)

    snapshot = client.get(
        f"/api/jobs/{analysis_job_id}", headers=_auth_headers()
    ).json()
    assert snapshot["status"] == "succeeded"
    assert snapshot["result"]["score"] == 80
    assert snapshot["result"]["diffs"][0]["proposed"].startswith(
        "Python developer with Redis"
    )


def test_workbench_run_emits_job_stage_into_open_session():
    job = _create_library_job()
    resume = _create_resume()
    session = client.get(
        f"/api/workspace/session/{job['job_id']}",
        headers=_auth_headers(),
    ).json()
    session_id = session["session_id"]

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    analysis_job_id = r.json()["job_id"]

    def run_with_stages(
        config,
        resume_text,
        jd_text,
        run_eval=False,
        granularity="medium",
        prompt_focus="balanced",
        custom_prompt="",
        diagnosis=None,
        on_stage=None,
        cache=None,
        tenant="default",
    ):
        if on_stage is not None:
            on_stage("jd_analysis", "Extracting JD profile")
        return _finished_report()

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", side_effect=run_with_stages
    ):
        api_module._run_job(analysis_job_id)

    session = api_module._session_store.get(session_id)
    assert session is not None
    stage_events = [
        item
        for item in session["events"]
        if item["event"] == "job.stage"
    ]
    assert stage_events
    assert all(item["data"].get("workbench") is True for item in stage_events)
    assert all(
        item["data"].get("job_id") == job["job_id"]
        for item in stage_events
    )


def test_workbench_run_persists_tailor_prefs():
    job = _create_library_job()
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={
                "master_resume_id": resume["resume_id"],
                "granularity": "fine",
                "prompt_focus": "skills",
                "custom_prompt": "强调高并发缓存场景",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    updated = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert updated["tailor_granularity"] == "fine"
    assert updated["tailor_focus"] == "skills"
    assert updated["custom_prompt"] == "强调高并发缓存场景"


def test_job_update_persists_tailor_prefs():
    job = _create_library_job()
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={
            "tailor_granularity": "coarse",
            "tailor_focus": "quantified",
            "custom_prompt": "突出部署经验",
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tailor_granularity"] == "coarse"
    assert body["tailor_focus"] == "quantified"
    assert body["custom_prompt"] == "突出部署经验"


def test_workbench_accept_diffs_returns_draft():
    job = _create_library_job()
    resume = _create_resume(content="Python developer. Redis.")
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    analysis_job_id = r.json()["job_id"]

    report = _finished_report()
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)

    r = client.post(
        f"/api/jobs/{job['job_id']}/workbench/accept",
        json={"job_id": analysis_job_id, "accepted_indices": [0]},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted_count"] == 1
    assert "Redis caching" in body["draft"]
    assert "Python developer." not in body["draft"]


def test_workbench_accept_uses_stored_job_id_and_counts_applied():
    job = _create_library_job()
    resume = _create_resume(content="Python developer. Redis.")
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    analysis_job_id = r.json()["job_id"]

    report = _finished_report()
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)

    r = client.post(
        f"/api/jobs/{job['job_id']}/workbench/accept",
        json={
            "job_id": "client-supplied-wrong-id",
            "accepted_indices": [0, 0, 99],
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["accepted_count"] == 1
    assert "Redis caching" in body["draft"]


def test_workbench_run_rate_limited():
    old_max = api_module._analyze_rate_limiter.max_requests
    api_module._analyze_rate_limiter.max_requests = 1
    try:
        job = _create_library_job()
        resume = _create_resume()
        with patch("resualign.api._run_job"), patch(
            "resualign.api.build_config", return_value=_config()
        ):
            first = client.post(
                f"/api/jobs/{job['job_id']}/workbench",
                json={"master_resume_id": resume["resume_id"]},
                headers=_auth_headers(),
            )
            second = client.post(
                f"/api/jobs/{job['job_id']}/workbench",
                json={"master_resume_id": resume["resume_id"]},
                headers=_auth_headers(),
            )
        assert first.status_code == 202
        assert second.status_code == 429
    finally:
        api_module._analyze_rate_limiter.max_requests = old_max
        api_module._analyze_rate_limiter.reset()


def test_workbench_requires_existing_resume_and_tenant_isolation():
    job = _create_library_job()

    with patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": "missing"},
            headers=_auth_headers(),
        )
    assert r.status_code == 404

def test_workbench_accept_missing_pinned_resume_returns_404():
    job = _create_library_job()
    resume = _create_resume(content="Python developer. Redis.")
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    analysis_job_id = r.json()["job_id"]

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=_finished_report()
    ):
        api_module._run_job(analysis_job_id)

    assert (
        client.delete(
            f"/api/master-resumes/{resume['resume_id']}",
            headers=_auth_headers(),
        ).status_code
        == 204
    )
    r = client.post(
        f"/api/jobs/{job['job_id']}/workbench/accept",
        json={"job_id": analysis_job_id, "accepted_indices": [0]},
        headers=_auth_headers(),
    )
    assert r.status_code == 404


def test_workbench_rejects_invalid_granularity():
    job = _create_library_job()
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={
                "master_resume_id": resume["resume_id"],
                "granularity": "wild",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 422

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={
                "master_resume_id": resume["resume_id"],
                "prompt_focus": "wild",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 422


def test_workbench_passes_prompt_focus_to_pipeline():
    job = _create_library_job()
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={
                "master_resume_id": resume["resume_id"],
                "prompt_focus": "skills",
            },
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    analysis_job_id = r.json()["job_id"]

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=_finished_report()
    ) as mock_run:
        api_module._run_job(analysis_job_id)

    assert mock_run.call_args.kwargs["prompt_focus"] == "skills"


def test_settings_get_update_and_validation():
    r = client.get("/api/settings", headers=_auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert "job_functions" in body["classification_vocabulary"]
    assert "appraisal_weights" not in body
    assert "salary_reference" not in body

    r = client.put(
        "/api/settings",
        json={
            "classification_vocabulary": {
                "job_functions": ["后端", "前端"],
                "seniorities": ["高级"],
                "statuses": ["未投递"],
            }
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["classification_vocabulary"]["job_functions"] == [
        "后端",
        "前端",
    ]


def test_application_status_update_preserves_workbench_result():
    resume = _create_resume()
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/applications",
            json={
                "title": "Backend at Acme",
                "master_resume_id": resume["resume_id"],
                "jd_text": "Python backend engineer.",
            },
            headers=_auth_headers(),
        )
        app_id = r.json()["application_id"]
        client.post(
            f"/api/applications/{app_id}/run",
            headers=_auth_headers(),
        )
        latest = client.get(
            f"/api/applications/{app_id}", headers=_auth_headers()
        ).json()
        job_id = latest["latest_job_id"]

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=_finished_report()
    ):
        api_module._run_job(job_id)

    r = client.patch(
        f"/api/applications/{app_id}",
        json={"status": "applied"},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "applied"
    assert r.json()["latest_job_id"] == job_id
    job = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert job["status"] == "succeeded"


def test_cached_diagnosis_reuses_matching_hash():
    job = api_module._registry.create(
        {"resume_text": "Python developer."}, _config(), tenant_id="tenant"
    )
    resume = {
        "content": "Python developer.",
        "latest_diagnosis_job_id": job.job_id,
    }
    api_module._registry.succeed(job.job_id, {
        "score": 88,
        "diagnosis": {
            "score": 88,
            "skills": ["Python"],
            "issues": [],
            "model": "test-model",
        },
        "diagnosis_source_hash": api_module._content_sha256(
            resume["content"]
        ),
    })
    cached = api_module._cached_diagnosis(resume, _config(), tenant_id="tenant")
    assert cached == {"score": 88, "skills": ["Python"], "issues": []}


def test_cached_diagnosis_rejects_changed_content_or_model():
    job = api_module._registry.create(
        {"resume_text": "Python developer."}, _config(), tenant_id="tenant"
    )
    resume = {
        "content": "Python developer.",
        "latest_diagnosis_job_id": job.job_id,
    }
    api_module._registry.succeed(job.job_id, {
        "score": 88,
        "diagnosis": {
            "score": 88,
            "skills": ["Python"],
            "issues": [],
            "model": "test-model",
        },
        "diagnosis_source_hash": api_module._content_sha256(
            resume["content"]
        ),
    })
    changed = dict(resume, content="Python developer with Docker.")
    assert (
        api_module._cached_diagnosis(changed, _config(), tenant_id="tenant")
        is None
    )
    other_model = ResuAlignConfig(
        provider="deepseek", api_key="sk-test", model="other-model"
    )
    assert (
        api_module._cached_diagnosis(resume, other_model, tenant_id="tenant")
        is None
    )


def test_cached_diagnosis_falls_back_to_master_resume_snapshot():
    resume = _create_resume(content="Python developer.")
    token = _auth_headers()["Authorization"].split(" ", 1)[1]
    user = api_module._users.user_for_token(token)
    assert user is not None
    source_hash = api_module._content_sha256("Python developer.")
    api_module._resumes.set_latest_diagnosis_snapshot(
        user["user_id"],
        resume["resume_id"],
        {
            "score": 91,
            "skills": ["Python"],
            "issues": [],
            "model": "test-model",
        },
        source_hash,
    )
    detail = api_module._resumes.get_master_resume(
        user["user_id"], resume["resume_id"]
    )
    assert detail["latest_diagnosis"] is not None
    assert api_module._cached_diagnosis(
        detail, _config(), tenant_id=user["user_id"]
    ) == {"score": 91, "skills": ["Python"], "issues": []}

    changed = api_module._resumes.update_master_resume(
        user["user_id"],
        resume["resume_id"],
        "Python developer. Docker.",
    )
    assert (
        api_module._cached_diagnosis(
            changed, _config(), tenant_id=user["user_id"]
        )
        is None
    )
