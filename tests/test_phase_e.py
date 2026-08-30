"""Phase E: alignment runtime refinements (local probe, noop, concurrency)."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.api.services.jobs import (
    _get_tenant_run_gate,
    _is_local_node,
    _probe_active_llm_quick,
    _run_job,
)
from resualign.job_library import JobLibraryStore
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
    db_path = tmp_path / "phase_e.db"
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


def _auth_headers():
    global _auth_cache
    if _auth_cache is None:
        client.post(
            "/api/auth/signup",
            json={"email": "phase-e@test.com", "password": "password-123"},
        )
        token = client.post(
            "/api/auth/login",
            json={"email": "phase-e@test.com", "password": "password-123"},
        ).json()["token"]
        _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _create_job():
    resp = client.post("/api/jobs", json={
        "title": "Phase E Test",
        "jd_text": "Python developer. Redis caching.",
        "company": "Test",
    }, headers=_auth_headers())
    return resp.json()


def _create_resume():
    resp = client.post("/api/master-resumes", json={
        "title": "Phase E Resume",
        "content": "Python developer. Java experience.",
    }, headers=_auth_headers())
    return resp.json()


# -- _is_local_node ----------------------------------------------------------

def test_is_local_node_ollama():
    assert _is_local_node("ollama", "http://localhost:11434") is True
    assert _is_local_node("ollama", "https://ollama.example.com") is True


def test_is_local_node_localhost_url():
    assert _is_local_node("deepseek", "http://localhost:11434") is True
    assert _is_local_node("deepseek", "http://127.0.0.1:11434") is True
    assert _is_local_node("deepseek", "http://0.0.0.0:11434") is True
    assert _is_local_node("deepseek", "http://[::1]:11434") is True


def test_is_local_node_remote_url():
    assert _is_local_node("deepseek", "https://api.deepseek.com") is False
    assert _is_local_node("deepseek", "http://192.168.1.1:11434") is False
    assert _is_local_node("deepseek", None) is False


# -- _probe_active_llm_quick -------------------------------------------------

def test_probe_local_network_error_blocks():
    """Phase E: a local node (Ollama) with network_error must block queueing."""
    with patch(
        "resualign.api.services.jobs.api_module._llm_nodes.get_active_node",
        return_value={
            "provider": "ollama",
            "api_key": None,
            "model": "qwen2.5:7b",
            "base_url": "http://localhost:11434",
        },
    ), patch(
        "resualign.api.routers.settings.probe_llm_connection",
        return_value={
            "ok": False,
            "status": "network_error",
            "latency_ms": 500,
            "message": "连接被拒绝：Ollama 未启动",
        },
    ):
        ok, msg = _probe_active_llm_quick("test-tenant")
    assert ok is False
    assert "Ollama" in msg or "连接" in msg


def test_probe_local_timeout_blocks():
    """Phase E: a local node timeout must also block."""
    with patch(
        "resualign.api.services.jobs.api_module._llm_nodes.get_active_node",
        return_value={
            "provider": "ollama",
            "api_key": None,
            "model": "qwen2.5:7b",
            "base_url": "http://localhost:11434",
        },
    ), patch(
        "resualign.api.routers.settings.probe_llm_connection",
        return_value={
            "ok": False,
            "status": "timeout",
            "latency_ms": 5000,
            "message": "连接超时（5 秒）：请检查服务是否启动",
        },
    ):
        ok, msg = _probe_active_llm_quick("test-tenant")
    assert ok is False
    assert "超时" in msg


def test_probe_remote_network_error_non_blocking():
    """Phase E: a remote node with network_error must NOT block."""
    with patch(
        "resualign.api.services.jobs.api_module._llm_nodes.get_active_node",
        return_value={
            "provider": "deepseek",
            "api_key": "sk-test",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    ), patch(
        "resualign.api.routers.settings.probe_llm_connection",
        return_value={
            "ok": False,
            "status": "network_error",
            "latency_ms": 500,
            "message": "网络错误：无法连接",
        },
    ):
        ok, msg = _probe_active_llm_quick("test-tenant")
    assert ok is True, "remote network_error must be non-blocking"


def test_probe_http_402_blocks():
    """Phase A1: HTTP 402 still blocks on any node."""
    with patch(
        "resualign.api.services.jobs.api_module._llm_nodes.get_active_node",
        return_value={
            "provider": "deepseek",
            "api_key": "sk-test",
            "model": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
        },
    ), patch(
        "resualign.api.routers.settings.probe_llm_connection",
        return_value={
            "ok": False,
            "status": "http_402",
            "latency_ms": 500,
            "message": "模型账户欠费或余额不足，请充值后重试",
        },
    ):
        ok, msg = _probe_active_llm_quick("test-tenant")
    assert ok is False
    assert "欠费" in msg


# -- all-noop -----------------------------------------------------------------

def test_all_noop_still_succeeded():
    """Phase E: a report with only noop diffs must still succeed
    with 0 usable diffs and the noops in invalid_diffs."""
    job = _create_job()
    resume = _create_resume()
    noop = DiffItem(
        type="modify",
        original="Python developer.",
        proposed="Python developer.",
        reason="no measurable outcomes",
        confidence="high",
        provenance="Python developer.",
    )
    report = Report(
        score=84,
        skills=["Python"],
        model="test-model",
        jd_profile=JDProfile(must_have_skills=["Python"]),
        gap_report=GapReport(missing_keywords=["Redis"]),
        tailored_resume=TailoredResume(
            sections={"experience": "Built FastAPI"},
            diffs=[noop],
        ),
        diffs=[noop],
    )
    with patch("resualign.api._run_job"), patch(
        "resualign.api.build_config", return_value=_config()
    ):
        queued = client.post(
            f"/api/jobs/{job['job_id']}/workbench",
            json={"master_resume_id": resume["resume_id"]},
            headers=_auth_headers(),
        )
    assert queued.status_code == 202
    analysis_job_id = queued.json()["job_id"]
    with patch("resualign.api.build_config", return_value=_config()), patch(
        "resualign.api.run", return_value=report
    ):
        api_module._run_job(analysis_job_id)
    persisted = client.get(
        f"/api/jobs/{job['job_id']}", headers=_auth_headers()
    ).json()
    assert persisted["alignment_status"] == "succeeded"
    assert len(persisted["diffs"]) == 0, "noop-only must produce 0 usable diffs"
    assert len(persisted["invalid_diffs"]) == 1
    assert persisted["invalid_diffs"][0]["original"] == "Python developer."


# -- per-tenant concurrency gate ---------------------------------------------

def test_get_tenant_run_gate_identity():
    """Phase E: same tenant returns the same Lock; different tenants differ."""
    gate_a1 = _get_tenant_run_gate("tenant-a")
    gate_a2 = _get_tenant_run_gate("tenant-a")
    gate_b = _get_tenant_run_gate("tenant-b")
    assert gate_a1 is gate_a2, "same tenant must share the same gate"
    assert gate_a1 is not gate_b, "different tenants must have different gates"


def test_tenant_gate_serializes_concurrent_runs():
    """Phase E: two alignments for the same tenant never run concurrently."""
    import threading
    from unittest.mock import patch as _patch

    tenant_id = "gate-tenant"
    for job_id in ("job-a", "job-b"):
        api_module._payloads[job_id] = (
            {"library_job_id": job_id},
            _config(),
            None,
            tenant_id,
        )

    entered = threading.Event()
    release = threading.Event()
    concurrency = []
    lock = threading.Lock()

    def fake_run(job_id):
        with lock:
            concurrency.append(job_id)
            if len(concurrency) > 1:
                raise AssertionError("two runs for one tenant entered at once")
        entered.set()
        release.wait(timeout=5)
        with lock:
            concurrency.remove(job_id)

    with _patch(
        "resualign.api.services.jobs._run_job_holding_gate", side_effect=fake_run
    ):
        t1 = threading.Thread(target=_run_job, args=("job-a",), daemon=True)
        t2 = threading.Thread(target=_run_job, args=("job-b",), daemon=True)
        t1.start()
        t2.start()
        assert entered.wait(timeout=5), "first run should start"
        # Give the second thread a chance to (wrongly) enter too.
        time.sleep(0.2)
        assert len(concurrency) == 1, "second run must wait on the tenant gate"
        release.set()
        t1.join(timeout=5)
        t2.join(timeout=5)
        assert not t1.is_alive() and not t2.is_alive()
    assert len(concurrency) == 0
