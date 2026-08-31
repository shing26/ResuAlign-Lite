"""POST /api/quick-eval — rule-based JD evaluation (zero LLM)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    JobLibraryStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)
_auth_cache = None

RESUME = """陈振成 后端开发工程师
技能：Java, Spring Boot, MySQL, Redis, Kafka
经历：某电商公司后端开发，负责订单与库存服务
"""

JD = """高级后端工程师
职责：负责订单交易系统设计与开发。
要求：精通 Java 与 Spring Boot；熟悉 MySQL、Redis、Kafka；
有高并发交易系统经验；了解 Kubernetes 与 Service Mesh 者优先。
"""


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    """Isolate quick-eval tests on a throwaway database (dashboard 模式）。"""
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
            "_PERSONAL_MODE",
            "_payloads",
            "_import_batches",
        )
    }
    db_path = tmp_path / "quick-eval.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    api_module._import_batches = {}
    _auth_cache = None
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None


def _auth_headers():
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "quick-eval@example.com", "password": "password-123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "quick-eval@example.com", "password": "password-123"},
    )
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_quick_eval_requires_auth():
    assert client.post("/api/quick-eval", json={"jd_text": JD}).status_code in (401, 403)


def test_quick_eval_rejects_short_jd():
    r = client.post(
        "/api/quick-eval",
        json={"jd_text": "太短"},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_quick_eval_scores_with_rules():
    resume = client.post(
        "/api/master-resumes",
        json={"title": "主简历", "content": RESUME},
        headers=_auth_headers(),
    ).json()
    r = client.post(
        "/api/quick-eval",
        json={"jd_text": JD, "master_resume_id": resume["resume_id"]},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    evaluation = body["evaluation"]
    assert evaluation["rule_based"] is True
    # 简历明确提到 Java/Spring Boot/MySQL/Redis/Kafka —— 命中应计入
    assert evaluation["total"] is not None and 0 <= evaluation["total"] <= 100
    assert isinstance(evaluation["missing_top"], list)
    assert len(evaluation["missing_top"]) <= 3
    assert evaluation["keyword_coverage"] is not None
    assert evaluation["recommendation"]
    assert body["existing_job_id"] is None


def test_quick_eval_flags_existing_job_by_dedupe():
    tenant = client.get("/api/auth/me", headers=_auth_headers()).json()["user_id"]
    existing = api_module._jobs.create_job(
        tenant, title="已入库岗位", jd_text=JD
    )
    r = client.post(
        "/api/quick-eval",
        json={"jd_text": JD},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    assert r.json()["existing_job_id"] == existing["job_id"]
