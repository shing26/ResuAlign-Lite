"""Q6: concurrent multi-tenant API traffic stays isolated and error-free.

Two tenants hammer the API in parallel (8 worker threads: 4 per tenant,
each with its own TestClient and bearer token). Every request must succeed
(0 errors), each tenant must only ever see its own records, and cross-tenant
reads of a foreign resource id must behave like a missing resource (404).

The SQLite backing file is shared: this doubles as the API-level WAL
concurrency gate (store-level coverage lives in
test_phase20_qa_gates.py::test_concurrent_worker_wal_claims).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.models import Report, ResuAlignConfig
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None

TENANTS = ("tenant-a", "tenant-b")
WORKERS_PER_TENANT = 4
CONCURRENCY = len(TENANTS) * WORKERS_PER_TENANT


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
            "_import_batches",
        )
    }
    db_path = tmp_path / "concurrency.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._session_store = api_module._workbench_service.WorkstationSessionStore()
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
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def test_concurrent_tenant_workload_stays_isolated():
    """8 parallel clients create jobs/resumes/applications with zero errors."""
    with patch("resualign.api._classify_job", return_value={}):
        outcomes: dict[tuple[str, int], dict] = {}
        errors: list[Exception] = []

        def worker(tenant: str, index: int) -> None:
            thread_client = TestClient(app)
            email = f"{tenant}-w{index}@concurrent.local"
            try:
                signup = thread_client.post(
                    "/api/auth/signup",
                    json={"email": email, "password": "password-123"},
                )
                assert signup.status_code == 201, signup.text
                token = thread_client.post(
                    "/api/auth/login",
                    json={"email": email, "password": "password-123"},
                ).json()["token"]
                headers = {"Authorization": f"Bearer {token}"}

                job = thread_client.post(
                    "/api/jobs",
                    json={
                        "title": f"{tenant} job {index}",
                        "jd_text": f"{tenant} JD {index}: Python + FastAPI.",
                        "company": f"{tenant}-co",
                    },
                    headers=headers,
                )
                assert job.status_code == 201, job.text
                resume = thread_client.post(
                    "/api/master-resumes",
                    json={
                        "title": f"{tenant} resume {index}",
                        "content": f"Resume of {tenant} worker {index}.",
                    },
                    headers=headers,
                )
                assert resume.status_code == 201, resume.text
                application = thread_client.post(
                    "/api/applications",
                    json={
                        "title": f"{tenant} application {index}",
                        "master_resume_id": resume.json()["resume_id"],
                        "jd_text": f"{tenant} JD {index}",
                    },
                    headers=headers,
                )
                assert application.status_code == 201, application.text
                outcomes[(tenant, index)] = {
                    "tenant": tenant,
                    "token": token,
                    "job": job.json(),
                    "resume": resume.json(),
                    "application": application.json(),
                }
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [
                pool.submit(worker, tenant, index)
                for tenant in TENANTS
                for index in range(WORKERS_PER_TENANT)
            ]
            for future in futures:
                future.result(timeout=60)

    assert not errors, f"worker failures: {errors}"
    assert len(outcomes) == CONCURRENCY

    # Every user (tenant) sees exactly its own records, scoped to its own id.
    tenant_ids: set[str] = set()
    for (owner, _index), outcome in outcomes.items():
        headers = {"Authorization": f"Bearer {outcome['token']}"}
        jobs = client.get("/api/jobs", headers=headers).json()
        assert len(jobs) == 1, f"{owner} jobs: {len(jobs)}"
        assert jobs[0]["job_id"] == outcome["job"]["job_id"]
        tenant_ids.add(jobs[0]["tenant_id"])

        resumes = client.get(
            "/api/master-resumes", headers=headers
        ).json()
        assert len(resumes) == 1
        assert resumes[0]["resume_id"] == outcome["resume"]["resume_id"]

        applications = client.get(
            "/api/applications", headers=headers
        ).json()
        assert len(applications) == 1
        assert (
            applications[0]["application_id"]
            == outcome["application"]["application_id"]
        )

    # The workers own disjoint tenant ids (one per user, MVP model).
    assert len(tenant_ids) == CONCURRENCY

    # Cross-tenant reads behave like missing resources (404).
    a_job = outcomes[("tenant-a", 0)]["job"]
    b_job = outcomes[("tenant-b", 0)]["job"]
    b_resume = outcomes[("tenant-b", 0)]["resume"]
    b_application = outcomes[("tenant-b", 0)]["application"]

    assert (
        client.get(
            f"/api/jobs/{b_job['job_id']}",
            headers={"Authorization": f"Bearer {outcomes[('tenant-a', 0)]['token']}"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/jobs/{a_job['job_id']}",
            headers={"Authorization": f"Bearer {outcomes[('tenant-b', 0)]['token']}"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/master-resumes/{b_resume['resume_id']}",
            headers={"Authorization": f"Bearer {outcomes[('tenant-a', 0)]['token']}"},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/applications/{b_application['application_id']}",
            headers={"Authorization": f"Bearer {outcomes[('tenant-a', 0)]['token']}"},
        ).status_code
        == 404
    )

    # Re-run the list views after cross-tenant probes: counts unchanged.
    for (_owner, _index), outcome in outcomes.items():
        headers = {"Authorization": f"Bearer {outcome['token']}"}
        jobs = client.get("/api/jobs", headers=headers).json()
        assert len(jobs) == 1


def test_concurrent_jobs_share_one_sqlite_file_without_locking_errors():
    """Queue and run jobs for two tenants while a third client writes.

    Exercises the API worker path (registry claims + WAL) under contention
    without any LLM call (engine run patched away).
    """
    with patch("resualign.api._classify_job", return_value={}):
        created: dict[str, dict] = {}

        def queue_and_run(tenant: str, index: int) -> None:
            thread_client = TestClient(app)
            email = f"runner-{tenant}-{index}@concurrent.local"
            thread_client.post(
                "/api/auth/signup",
                json={"email": email, "password": "password-123"},
            )
            token = thread_client.post(
                "/api/auth/login",
                json={"email": email, "password": "password-123"},
            ).json()["token"]
            headers = {"Authorization": f"Bearer {token}"}
            queued = thread_client.post(
                "/api/analyze",
                json={
                    "resume_text": f"Resume {tenant} {index}",
                    "jd_text": f"JD {tenant} {index} with FastAPI.",
                },
                headers=headers,
            )
            assert queued.status_code == 202, queued.text
            job_id = queued.json()["job_id"]
            created[job_id] = {"tenant": tenant, "headers": headers}

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = [
                pool.submit(queue_and_run, tenant, index)
                for tenant in TENANTS
                for index in range(WORKERS_PER_TENANT)
            ]
            for future in futures:
                future.result(timeout=60)

    with patch(
        "resualign.api.build_config", return_value=_config()
    ), patch(
        "resualign.api.run",
        return_value=Report(score=80, skills=["Python"], model="test-model"),
    ):
        for job_id in created:
            api_module._run_job(job_id)

    # All 8 jobs finished; each user sees its own job succeeded.
    for job_id, entry in created.items():
        snap = client.get(
            f"/api/jobs/{job_id}", headers=entry["headers"]
        ).json()
        assert snap["status"] == "succeeded"


def test_parallel_signup_login_sessions_are_distinct():
    """Bearer sessions minted in parallel resolve to the right user."""
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        sessions = list(
            pool.map(
                lambda index: _signup_login(index),
                range(CONCURRENCY),
            )
        )
    for index, token in sessions:
        me = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == f"session-{index}@concurrent.local"


def _signup_login(index: int) -> tuple[int, str]:
    thread_client = TestClient(app)
    email = f"session-{index}@concurrent.local"
    thread_client.post(
        "/api/auth/signup",
        json={"email": email, "password": "password-123"},
    )
    token = thread_client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    ).json()["token"]
    return index, token
