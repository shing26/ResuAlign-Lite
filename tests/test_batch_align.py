"""API tests for batch alignment queueing, isolation, cancel, and matrix."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.batch import BatchAlignStore
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
        "resumes": api_module._resumes,
        "applications": api_module._applications,
        "jobs": api_module._jobs,
        "settings": api_module._settings_store,
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
        "import_batches": api_module._import_batches,
        "batch_store": api_module._batch_store,
    }
    db_path = tmp_path / "batch.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    api_module._batch_store = BatchAlignStore()
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
    api_module._settings_store = saved["settings"]
    api_module._PERSONAL_MODE = saved["personal_mode"]
    api_module._payloads = saved["payloads"]
    api_module._import_batches = saved["import_batches"]
    api_module._batch_store = saved["batch_store"]
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
        json={"email": "batch@example.com", "password": "password-123"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "batch@example.com", "password": "password-123"},
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
        json={"email": "other-batch@example.com", "password": "other-password"},
    )
    assert r.status_code == 201
    r = client.post(
        "/api/auth/login",
        json={"email": "other-batch@example.com", "password": "other-password"},
    )
    assert r.status_code == 200
    _other_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _other_cache


def _create_resume(content="Python developer with 5 years experience."):
    r = client.post(
        "/api/master-resumes",
        json={"title": "Master Resume", "content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _create_library_jobs(count):
    job_ids = []
    with patch("resualign.api._classify_job", return_value={}):
        for index in range(count):
            r = client.post(
                "/api/jobs",
                json={
                    "title": f"Backend Engineer {index}",
                    "jd_text": f"Python backend {20 + index}-30K",
                    "company": "Acme",
                    "location": "Shanghai",
                },
                headers=_auth_headers(),
            )
            assert r.status_code == 201
            job_ids.append(r.json()["job_id"])
    return job_ids


def _queue_payloads(job_ids, resume_id, **overrides):
    return {
        "master_resume_id": resume_id,
        "job_ids": job_ids,
        **overrides,
    }


def test_batch_align_queues_two_jobs_with_fine_granularity():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    queued = []

    def fake_queue_job(user, payload, workbench=False):
        queued.append((payload, workbench))
        return f"analysis-{len(queued)}"

    with patch(
        "resualign.api._queue_job", side_effect=fake_queue_job
    ), patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(job_ids, resume["resume_id"]),
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    body = r.json()
    assert body["total"] == 2
    assert body["queued"] == 2
    assert len(queued) == 2
    assert all(payload["granularity"] == "fine" for payload, _ in queued)
    assert all(payload["library_job_id"] in job_ids for payload, _ in queued)
    assert all(workbench for _, workbench in queued)

    status = client.get(
        f"/api/batch-align/{body['batch_id']}", headers=_auth_headers()
    ).json()
    assert status["summary"]["total"] == 2
    assert [row["status"] for row in status["rows"]] == ["queued", "queued"]
    assert [row["analysis_job_id"] for row in status["rows"]] == [
        "analysis-1",
        "analysis-2",
    ]


def test_batch_align_accepts_five_jobs():
    resume = _create_resume()
    job_ids = _create_library_jobs(5)
    with patch("resualign.api._queue_job", return_value="analysis-x"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(
                job_ids, resume["resume_id"], granularity="medium"
            ),
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    assert r.json()["total"] == 5


def _queue_batch(job_ids, resume_id, **overrides):
    queued = []

    def fake_queue_job(user, payload, workbench=False):
        queued.append((payload, workbench))
        return f"analysis-{len(queued)}"

    with patch(
        "resualign.api._queue_job", side_effect=fake_queue_job
    ), patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(
                job_ids, resume_id, **overrides
            ),
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    return queued


def test_batch_align_run_eval_defaults_to_false_when_unset():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    queued = _queue_batch(job_ids, resume["resume_id"])
    assert all(payload["run_eval"] is False for payload, _ in queued)


def test_batch_align_run_eval_falls_back_to_global_default():
    client.put(
        "/api/settings", json={"eval_default": True}, headers=_auth_headers()
    )
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    queued = _queue_batch(job_ids, resume["resume_id"])
    assert all(payload["run_eval"] is True for payload, _ in queued)


def test_batch_align_run_eval_explicit_false_overrides_global_default():
    client.put(
        "/api/settings", json={"eval_default": True}, headers=_auth_headers()
    )
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    queued = _queue_batch(
        job_ids, resume["resume_id"], run_eval=False
    )
    assert all(payload["run_eval"] is False for payload, _ in queued)


def test_batch_align_run_eval_explicit_true_wins():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    queued = _queue_batch(job_ids, resume["resume_id"], run_eval=True)
    assert all(payload["run_eval"] is True for payload, _ in queued)


def test_batch_align_rejects_out_of_range_job_counts():
    headers = _auth_headers()
    r = client.post(
        "/api/batch-align",
        json={"master_resume_id": "x", "job_ids": ["one"]},
        headers=headers,
    )
    assert r.status_code == 422
    r = client.post(
        "/api/batch-align",
        json={"master_resume_id": "x", "job_ids": [f"j{i}" for i in range(6)]},
        headers=headers,
    )
    assert r.status_code == 422


def test_batch_align_tenant_isolation():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    with patch("resualign.api._queue_job", return_value="analysis-x"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(job_ids, resume["resume_id"]),
            headers=_auth_headers(),
        )
    batch_id = r.json()["batch_id"]
    other = _other_headers()
    assert (
        client.get(
            f"/api/batch-align/{batch_id}", headers=other
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/batch-align/{batch_id}/cancel", headers=other
        ).status_code
        == 404
    )


def _finished_report(score=80, missing=None):
    diff = DiffItem(
        type="modify",
        original="Python developer.",
        proposed="Python developer with Redis caching.",
        reason="JD match",
        confidence="high",
        provenance="Python developer.",
    )
    return Report(
        score=score,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(must_have_skills=["Python"]),
        gap_report=GapReport(missing_keywords=missing or []),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI services with Redis"},
            diffs=[diff],
        ),
        diffs=[diff],
    )


def test_batch_align_result_matrix_shape():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(job_ids, resume["resume_id"]),
            headers=_auth_headers(),
        )
    batch_id = r.json()["batch_id"]
    batch = client.get(
        f"/api/batch-align/{batch_id}", headers=_auth_headers()
    ).json()
    analysis_ids = [row["analysis_job_id"] for row in batch["rows"]]

    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run",
        side_effect=[
            _finished_report(score=80, missing=["Redis"]),
            _finished_report(score=65, missing=["Docker"]),
        ],
    ):
        for analysis_id in analysis_ids:
            api_module._run_job(analysis_id)

    body = client.get(
        f"/api/batch-align/{batch_id}", headers=_auth_headers()
    ).json()
    assert body["summary"]["succeeded"] == 2
    assert body["summary"]["average_score"] == 72.5
    assert body["summary"]["best_score"] == 80
    assert body["summary"]["best_job_id"] == job_ids[0]
    for row in body["rows"]:
        assert row["status"] == "succeeded"
        assert set(row["summary"]) == {
            "score",
            "eval",
            "key_gaps",
            "next_step",
        }
        assert row["summary"]["eval"] is None
        assert isinstance(row["summary"]["key_gaps"], list)
        assert isinstance(row["summary"]["next_step"], str)


def test_batch_align_cancel_queued_rows():
    resume = _create_resume()
    job_ids = _create_library_jobs(3)

    def fake_queue(user, payload, application_id=None, workbench=False):
        job = api_module._registry.create(
            payload, None, tenant_id=user["user_id"]
        )
        return job.job_id

    with patch(
        "resualign.api._queue_job", side_effect=fake_queue
    ), patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(job_ids, resume["resume_id"]),
            headers=_auth_headers(),
        )
    batch_id = r.json()["batch_id"]
    r = client.post(
        f"/api/batch-align/{batch_id}/cancel", headers=_auth_headers()
    )
    assert r.status_code == 200
    assert r.json()["canceled"] == 3
    body = client.get(
        f"/api/batch-align/{batch_id}", headers=_auth_headers()
    ).json()
    assert body["summary"]["canceled"] == 3
    assert all(row["status"] == "canceled" for row in body["rows"])


def test_batch_align_cancel_marks_lost_analysis_as_failed_not_canceled():
    """A row whose analysis job no longer exists (TTL-purged / lost on
    restart) must read as failed with a reason, never as canceled -
    'canceled' implies the user chose to stop it."""
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    with patch("resualign.api._queue_job", return_value="gone-job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(job_ids, resume["resume_id"]),
            headers=_auth_headers(),
        )
    batch_id = r.json()["batch_id"]

    r = client.post(
        f"/api/batch-align/{batch_id}/cancel", headers=_auth_headers()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["canceled"] == 0
    assert body["failed"] == 2

    rows = client.get(
        f"/api/batch-align/{batch_id}", headers=_auth_headers()
    ).json()["rows"]
    assert all(row["status"] == "failed" for row in rows)
    assert all("已过期或丢失" in (row["error"] or "") for row in rows)


def test_batch_align_requires_api_key():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    with patch("resualign.api.build_config", return_value=_config("")):
        r = client.post(
            "/api/batch-align",
            json=_queue_payloads(job_ids, resume["resume_id"]),
            headers=_auth_headers(),
        )
    assert r.status_code == 503


def _set_alignment_status(job_id, status, workbench_job_id=None):
    """用 store 直改 alignment_status，模拟历史遗留的各状态岗位。"""
    jobs = client.get("/api/jobs", headers=_auth_headers()).json()
    rows = jobs if isinstance(jobs, list) else jobs.get("jobs") or []
    tenant = next(j["tenant_id"] for j in rows if j["job_id"] == job_id)
    api_module._jobs.update_job(
        tenant, job_id, alignment_status=status, workbench_job_id=workbench_job_id
    )


def test_batch_align_pending_queues_idle_and_failed_only():
    resume = _create_resume()
    job_ids = _create_library_jobs(3)
    _set_alignment_status(job_ids[0], "succeeded")
    _set_alignment_status(job_ids[1], "failed")
    # job_ids[2] 保持 idle

    queued = []
    def fake_queue_job(user, payload, workbench=False):
        queued.append((payload, workbench))
        return f"analysis-{len(queued)}"

    with patch(
        "resualign.api._queue_job", side_effect=fake_queue_job
    ), patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json={"selector": "pending", "master_resume_id": resume["resume_id"], "job_ids": []},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    assert r.json()["total"] == 2
    assert {payload["library_job_id"] for payload, _ in queued} == {
        job_ids[1],
        job_ids[2],
    }


def test_batch_align_pending_includes_stale_queued():
    resume = _create_resume()
    job_ids = _create_library_jobs(2)
    # registry 中不存在 / 无注册任务 → 都是"卡死的 queued"
    _set_alignment_status(job_ids[0], "queued", workbench_job_id="ghost-job")
    _set_alignment_status(job_ids[1], "queued", workbench_job_id=None)

    with patch("resualign.api._queue_job", return_value="analysis-x"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        r = client.post(
            "/api/batch-align",
            json={"selector": "pending", "master_resume_id": resume["resume_id"], "job_ids": []},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    assert r.json()["total"] == 2


def test_batch_align_pending_defaults_to_latest_resume():
    _create_resume("first content")
    latest = _create_resume("second content")
    _create_library_jobs(1)

    queued = []
    def fake_queue_job(user, payload, workbench=False):
        queued.append((payload, workbench))
        return f"analysis-{len(queued)}"

    with patch(
        "resualign.api._queue_job", side_effect=fake_queue_job
    ), patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json={"selector": "pending", "master_resume_id": "", "job_ids": []},
            headers=_auth_headers(),
        )
    assert r.status_code == 202
    assert queued[0][0]["master_resume_id"] == latest["resume_id"]


def test_batch_align_pending_without_pending_jobs_422():
    _create_resume()
    with patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json={"selector": "pending", "master_resume_id": "", "job_ids": []},
            headers=_auth_headers(),
        )
    assert r.status_code == 422
    assert "待处理" in r.json()["detail"]


def test_batch_align_pending_without_resume_422():
    _create_library_jobs(1)
    with patch("resualign.api.build_config", return_value=_config()):
        r = client.post(
            "/api/batch-align",
            json={"selector": "pending", "master_resume_id": "", "job_ids": []},
            headers=_auth_headers(),
        )
    assert r.status_code == 422
    assert "主简历" in r.json()["detail"]
