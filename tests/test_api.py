"""Tests for the asynchronous FastAPI job API."""

import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.crawler import CrawlError
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore
from resualign.models import (
    DiffItem,
    EvalScore,
    GapReport,
    JDProfile,
    Report,
    ResuAlignConfig,
    TailoredResume,
)

client = TestClient(app)
_auth_cache = None


def _config(api_key="sk-test"):
    return ResuAlignConfig(
        provider="deepseek",
        api_key=api_key,
        model="test-model",
    )


def _submit(payload):
    """Create a job without letting the daemon thread run it."""
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/analyze", json=payload, headers=_auth_headers()
        )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    return body["job_id"]


def _poll_until_finished(job_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    data = None
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/{job_id}", headers=_auth_headers())
        assert r.status_code == 200
        data = r.json()
        if data["status"] in ("succeeded", "failed"):
            return data
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s: {data}")


@pytest.fixture(autouse=True)
def temp_job_store(tmp_path):
    global _auth_cache
    saved_registry = api_module._registry
    saved_users = api_module._users
    saved_personal_mode = api_module._PERSONAL_MODE
    saved_payloads = getattr(api_module, "_payloads", {})
    saved_settings = getattr(api_module, "_settings_store", None)
    db_path = tmp_path / "api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
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
    yield
    api_module._registry = saved_registry
    api_module._users = saved_users
    api_module._PERSONAL_MODE = saved_personal_mode
    api_module._payloads = saved_payloads
    api_module._settings_store = saved_settings
    api_module._import_batches = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None


def _auth_headers():
    """Sign up a fresh user and return bearer auth headers."""
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


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_root_serves_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "ResuAlign" in r.text


def test_analyze_requires_resume():
    r = client.post("/api/analyze", json={}, headers=_auth_headers())
    assert r.status_code == 422


def test_analyze_requires_auth():
    r = client.post(
        "/api/analyze",
        json={"resume_text": "Python developer resume."},
    )
    assert r.status_code == 401


def test_job_read_requires_auth():
    r = client.get("/api/jobs/some-job")
    assert r.status_code == 401


def test_signup_login_me_logout_flow():
    r = client.post(
        "/api/auth/signup",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ada@example.com"
    assert "user_id" in body

    r = client.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    assert r.status_code == 200
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "ada@example.com"

    r = client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 200

    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401


def test_login_rejects_bad_password():
    client.post(
        "/api/auth/signup",
        json={"email": "ada@example.com", "password": "correct-horse"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": "wrong"},
    )
    assert r.status_code == 401


def test_jobs_are_isolated_between_users():
    report = Report(score=80, skills=["Python"], model="test-model")

    with patch("resualign.api.run", return_value=report):
        job_id = _submit({"resume_text": "Python developer."})
        api_module._run_job(job_id)

    r = client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "other-password"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "other-password"},
    )
    other_headers = {"Authorization": f"Bearer {r.json()['token']}"}

    assert client.get(f"/api/jobs/{job_id}", headers=other_headers).status_code == 404
    assert client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).status_code == 200


def test_analyze_no_api_key():
    with patch("resualign.api.build_config", return_value=_config("")):
        r = client.post(
            "/api/analyze",
            json={"resume_text": "Python developer resume."},
            headers=_auth_headers(),
        )
    assert r.status_code == 503
    assert "API key not configured" in r.json()["detail"]


def test_create_job_returns_202_and_queued_snapshot():
    job_id = _submit({"resume_text": "Python developer resume."})

    r = client.get(f"/api/jobs/{job_id}", headers=_auth_headers())

    assert r.status_code == 200
    assert r.json() == {
        "job_id": job_id,
        "status": "queued",
        "stage": "",
        "message": "",
        "elapsed_seconds": 0.0,
        "result": None,
        "error": None,
    }


def test_job_runs_to_succeeded_with_full_report_shape():
    report = Report(
        score=82,
        skills=["Python", "FastAPI"],
        issues=["Add more numbers"],
        diffs=[
            DiffItem(
                type="modify",
                original="old",
                proposed="new",
                reason="match",
                confidence="high",
            )
        ],
        model="test-model",
        jd_profile=JDProfile(
            must_have_skills=["Python"],
            nice_to_have_skills=["Redis"],
            soft_skills=["Communication"],
            business_scenarios=["Backend"],
            min_years_experience=3,
            education_requirements=["BS"],
        ),
        gap_report=GapReport(
            missing_keywords=["Redis"],
            misaligned_emphasis=["Leadership"],
            strength_matches=["Python"],
        ),
        tailored_resume=TailoredResume(
            sections={"experience": "Built REST APIs"},
            diffs=[DiffItem(original="old", proposed="new")],
        ),
        eval_score=EvalScore(
            jd_match_score=90,
            improvement=8,
            hallucination_detected=False,
            hallucination_details=[],
            gap_coverage=0.8,
        ),
        elapsed_seconds=12.3,
    )

    with patch("resualign.api.run", return_value=report) as mock_run:
        job_id = _submit(
            {
                "resume_text": "Python developer with FastAPI experience.",
                "jd_text": "Looking for a Python backend engineer.",
            }
        )
        api_module._run_job(job_id)

    on_stage = mock_run.call_args.kwargs["on_stage"]
    assert callable(on_stage)
    assert mock_run.call_args.kwargs["run_eval"] is False

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "succeeded"
    assert data["error"] is None
    result = data["result"]
    assert result["score"] == 82
    assert result["skills"] == ["Python", "FastAPI"]
    assert result["model"] == "test-model"
    assert result["diffs"][0]["type"] == "modify"
    assert result["jd_profile"] == {
        "must_have_skills": ["Python"],
        "nice_to_have_skills": ["Redis"],
        "soft_skills": ["Communication"],
        "business_scenarios": ["Backend"],
        "min_years_experience": 3,
        "education_requirements": ["BS"],
    }
    assert result["gap_report"] == {
        "missing_keywords": ["Redis"],
        "misaligned_emphasis": ["Leadership"],
        "strength_matches": ["Python"],
    }
    assert result["tailored_resume"]["sections"] == {
        "experience": "Built REST APIs"
    }
    assert result["eval_score"]["jd_match_score"] == 90
    assert result["elapsed_seconds"] >= 0


def test_job_without_jd_keeps_diagnosis_only_result():
    report = Report(
        score=65,
        skills=["Python"],
        issues=["Needs work"],
        model="test-model",
    )

    with patch("resualign.api.run", return_value=report):
        job_id = _submit({"resume_text": "Python developer."})
        api_module._run_job(job_id)

    result = client.get(
        f"/api/jobs/{job_id}", headers=_auth_headers()
    ).json()["result"]
    assert result["score"] == 65
    assert result["diffs"] == []
    assert result["jd_profile"] is None
    assert result["gap_report"] is None
    assert result["tailored_resume"] is None
    assert result["eval_score"] is None


def test_failed_job_carries_error():
    with patch("resualign.api.run", side_effect=RuntimeError("boom")):
        job_id = _submit({"resume_text": "Python developer."})
        api_module._run_job(job_id)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()

    assert data["status"] == "failed"
    assert data["error"] == "Analysis failed after an internal error"
    assert data["result"] is None


def test_unknown_job_returns_404():
    r = client.get("/api/jobs/not-a-real-job", headers=_auth_headers())

    assert r.status_code == 404
    assert r.json()["detail"] == "Job not found"


def test_jd_url_success_runs_inside_job():
    report = Report(
        score=77,
        skills=["Python"],
        model="test-model",
    )

    with patch("resualign.api.crawl_jd", return_value="JD from URL") as crawl, patch(
        "resualign.api.run", return_value=report
    ) as mock_run:
        job_id = _submit(
            {
                "resume_text": "Python developer.",
                "jd_url": "https://example.com/job",
            }
        )
        api_module._run_job(job_id)

    crawl.assert_called_once_with("https://example.com/job")
    assert mock_run.call_args.args[2] == "JD from URL"
    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "succeeded"
    assert data["result"]["score"] == 77


def test_jd_url_crawl_failure_becomes_failed_job():
    with patch(
        "resualign.api.crawl_jd", side_effect=CrawlError("boom")
    ), patch("resualign.api.run") as mock_run:
        job_id = _submit(
            {
                "resume_text": "Python developer.",
                "jd_url": "https://example.com/bad",
            }
        )
        api_module._run_job(job_id)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "failed"
    assert "Failed to crawl JD from URL" in data["error"]
    assert "boom" in data["error"]
    assert data["result"] is None
    mock_run.assert_not_called()


def test_job_runs_eval_when_requested():
    report = Report(
        score=80,
        skills=["Python"],
        model="test-model",
        eval_score=EvalScore(
            jd_match_score=85,
            improvement=5,
            hallucination_detected=False,
            hallucination_details=[],
            gap_coverage=0.7,
        ),
    )

    with patch("resualign.api.run", return_value=report) as mock_run:
        job_id = _submit(
            {
                "resume_text": "Python developer.",
                "jd_text": "Python backend engineer.",
                "run_eval": True,
            }
        )
        api_module._run_job(job_id)

    assert mock_run.call_args.kwargs["run_eval"] is True
    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "succeeded"
    assert data["result"]["eval_score"]["jd_match_score"] == 85


def test_analyze_passes_prompt_focus_and_rejects_invalid():
    report = Report(score=70, skills=["Python"], model="test-model")
    with patch("resualign.api.run", return_value=report) as mock_run:
        job_id = _submit(
            {
                "resume_text": "Python developer.",
                "prompt_focus": "quantified",
            }
        )
        api_module._run_job(job_id)

    assert mock_run.call_args.kwargs["prompt_focus"] == "quantified"
    r = client.post(
        "/api/analyze",
        json={"resume_text": "Python", "prompt_focus": "wild"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_real_thread_polls_to_succeeded():
    report = Report(
        score=88,
        skills=["Python"],
        model="test-model",
    )

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        r = client.post(
            "/api/analyze",
            json={"resume_text": "Python developer."},
            headers=_auth_headers(),
        )
        job_id = r.json()["job_id"]
        data = _poll_until_finished(job_id)

    assert data["status"] == "succeeded"
    assert data["result"]["score"] == 88


def test_real_thread_reports_stage_message_and_elapsed():
    entered = threading.Event()
    release = threading.Event()

    def fake_run(config, resume_text, jd_text, on_stage=None, run_eval=False, **kwargs):
        on_stage("jd_profile", "Extracting JD profile...")
        entered.set()
        if not release.wait(2):
            raise TimeoutError("test release timed out")
        return Report(score=70, skills=["Python"], model="test-model")

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", side_effect=fake_run
    ):
        r = client.post(
            "/api/analyze",
            json={
                "resume_text": "Python developer.",
                "jd_text": "Java backend engineer.",
            },
            headers=_auth_headers(),
        )
        job_id = r.json()["job_id"]

        try:
            assert entered.wait(2)
            running = client.get(
                f"/api/jobs/{job_id}", headers=_auth_headers()
            ).json()
            assert running["status"] == "running"
            assert running["stage"] == "jd_profile"
            assert running["message"] == "Extracting JD profile..."
            assert isinstance(running["elapsed_seconds"], float)
            release.set()
            data = _poll_until_finished(job_id)
        finally:
            release.set()

    assert data["status"] == "succeeded"
    assert data["result"]["score"] == 70


def test_registry_cap_evicts_oldest_job():
    old_max = api_module._registry.max_jobs
    old_ttl = api_module._registry.ttl_seconds
    api_module._registry.max_jobs = 2
    api_module._registry.ttl_seconds = 3600
    report = Report(score=70, skills=["Python"], model="test-model")
    try:
        with patch("resualign.api.run", return_value=report):
            first = _submit({"resume_text": "resume 0"})
            api_module._run_job(first)
        job_ids = [
            _submit({"resume_text": f"resume {i}"}) for i in range(1, 3)
        ]
    finally:
        api_module._registry.max_jobs = old_max
        api_module._registry.ttl_seconds = old_ttl

    headers = _auth_headers()
    assert client.get(f"/api/jobs/{first}", headers=headers).status_code == 404
    assert client.get(f"/api/jobs/{job_ids[0]}", headers=headers).status_code == 200
    assert client.get(f"/api/jobs/{job_ids[1]}", headers=headers).status_code == 200


def test_registry_ttl_expires_job():
    now = [1000.0]
    old_clock = api_module._registry._clock
    old_ttl = api_module._registry.ttl_seconds
    api_module._registry._clock = lambda: now[0]
    api_module._registry.ttl_seconds = 60
    try:
        job_id = _submit({"resume_text": "Python developer."})
        headers = _auth_headers()
        assert client.get(f"/api/jobs/{job_id}", headers=headers).status_code == 200

        now[0] += 61

        r = client.get(f"/api/jobs/{job_id}", headers=_auth_headers())
        assert r.status_code == 404
        assert r.json()["detail"] == "Job not found"
    finally:
        api_module._registry._clock = old_clock
        api_module._registry.ttl_seconds = old_ttl


def test_completed_job_survives_new_store_on_same_database():
    report = Report(
        score=73,
        skills=["Python"],
        model="test-model",
    )

    with patch("resualign.api.run", return_value=report):
        job_id = _submit({"resume_text": "Python developer."})
        api_module._run_job(job_id)

    db_path = api_module._registry.db_path
    api_module._registry = JobRegistry(db_path=db_path)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()

    assert data["status"] == "succeeded"
    assert data["result"]["score"] == 73


def test_payload_persisted_but_config_never_written_to_database():
    secret_resume = "RESUME_SECRET_TEXT_7f3a"
    secret_key = "sk-secret-key-9c2b"
    report = Report(
        score=74,
        skills=["Python"],
        model="test-model",
    )

    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config(secret_key)
    ):
        r = client.post(
            "/api/analyze",
            json={"resume_text": secret_resume},
            headers=_auth_headers(),
        )
        assert r.status_code == 202
        job_id = r.json()["job_id"]

    with patch("resualign.api.run", return_value=report):
        api_module._run_job(job_id)

    data = client.get(f"/api/jobs/{job_id}", headers=_auth_headers()).json()
    assert data["status"] == "succeeded"

    raw = api_module._registry.db_path.read_bytes()
    assert secret_resume.encode("utf-8") in raw
    assert secret_key.encode("utf-8") not in raw


def test_restart_recovery_requeues_pending_jobs():
    job_ids = [
        _submit({"resume_text": f"resume {i}"}) for i in range(2)
    ]

    with patch("resualign.api._run_job") as mock_run:
        api_module._recover_pending_jobs()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            calls = {call.args[0] for call in mock_run.call_args_list}
            if set(job_ids) <= calls:
                break
            time.sleep(0.01)

    assert {call.args[0] for call in mock_run.call_args_list} == set(job_ids)


def test_analyze_rate_limited_after_budget():
    old_max = api_module._analyze_rate_limiter.max_requests
    api_module._analyze_rate_limiter.max_requests = 2
    try:
        with patch("resualign.api._run_job"), patch(
            "resualign.api.build_config", return_value=_config()
        ):
            for _ in range(2):
                r = client.post(
                    "/api/analyze",
                    json={"resume_text": "Python developer."},
                    headers=_auth_headers(),
                )
                assert r.status_code == 202
            r = client.post(
                "/api/analyze",
                json={"resume_text": "Python developer."},
                headers=_auth_headers(),
            )
        assert r.status_code == 429
        assert "Too many requests" in r.json()["detail"]
    finally:
        api_module._analyze_rate_limiter.max_requests = old_max
        api_module._analyze_rate_limiter.reset()


def test_cancel_queued_job_and_ignore_worker():
    report = Report(score=70, skills=["Python"], model="test-model")
    job_id = _submit({"resume_text": "Python developer."})
    headers = _auth_headers()

    r = client.post(f"/api/jobs/{job_id}/cancel", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "canceled"

    with patch("resualign.api.run", return_value=report) as mock_run:
        api_module._run_job(job_id)
    mock_run.assert_not_called()

    snapshot = client.get(f"/api/jobs/{job_id}", headers=headers).json()
    assert snapshot["status"] == "canceled"
    assert snapshot["error"] == "Canceled by user"


def test_running_job_cannot_be_canceled():
    job_id = _submit({"resume_text": "Python developer."})
    api_module._registry.mark_running(job_id)

    r = client.post(f"/api/jobs/{job_id}/cancel", headers=_auth_headers())

    assert r.status_code == 409
    assert "queued" in r.json()["detail"]
