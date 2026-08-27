"""API tests for the Job Library endpoints."""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.api.services.jobs import _derive_title, _extract_company_location
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
_other_cache = None


def _classify(jd_text, job_functions=None, seniorities=None, **kwargs):
    return {
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Python", "FastAPI"],
    }


def _wait_import(import_id, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/jobs/import/{import_id}")
        assert r.status_code == 200
        body = r.json()
        if not body["queued"]:
            return body
        time.sleep(0.01)
    raise AssertionError(f"import {import_id} did not finish")


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache, _other_cache
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
    db_path = tmp_path / "job-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
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


def test_create_job_from_paste_text():
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer. 20-30K",
                "company": "Acme",
                "location": "Shanghai",
            },
        )
    assert r.status_code == 201
    job = r.json()
    assert job["title"] == "Backend Engineer"
    assert job["company"] == "Acme"
    assert job["job_function"] == "后端"
    assert job["seniority"] == "高级"
    assert job["tech_tags"] == ["Python", "FastAPI"]
    # De-bloat: salary is no longer auto-extracted from JD text; the field
    # stays populated only when explicitly provided.
    assert job["salary_min"] is None
    assert job["salary_max"] is None
    assert job["source_type"] == "paste"
    assert job["classification_pending"] == 0


def test_create_job_derives_title_from_first_line():
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={"jd_text": "Senior Java Developer\nJava, Spring Boot."},
        )
    assert r.status_code == 201
    assert r.json()["title"] == "Senior Java Developer"


def test_create_job_from_url_without_text_rejected():
    """De-bloat: backend crawling retired; a URL-only create is rejected
    with a pointer to paste / userscript ingestion."""
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_url": "https://example.com/job/1",
            },
        )
    assert r.status_code == 422
    assert "粘贴" in r.json()["detail"] or "油猴插件" in r.json()["detail"]


def test_create_job_prefers_provided_jd_text_over_url():
    with patch(
        "resualign.api._classify_job", side_effect=_classify
    ):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer. 20-30K",
                "jd_url": "https://example.com/job/1",
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert body["jd_text"] == "Python backend engineer. 20-30K"
    assert body["source_url"] == "https://example.com/job/1"


def test_create_job_uses_provided_tech_tags():
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer. 20-30K",
                "tech_tags": ["React"],
            },
        )
    assert r.status_code == 201
    assert r.json()["tech_tags"] == ["React"]


def test_create_job_accepts_custom_vocabulary_function():
    with patch("resualign.api._classify_job", return_value={}):
        settings = client.put(
            "/api/settings",
            json={
                "classification_vocabulary": {
                    "job_functions": ["AI 应用"],
                    "seniorities": ["P7"],
                }
            },
        )
        assert settings.status_code == 200
        r = client.post(
            "/api/jobs",
            json={
                "title": "AI Engineer",
                "jd_text": "AI application engineer",
                "job_function": "AI 应用",
                "seniority": "P7",
            },
        )
    assert r.status_code == 201
    assert r.json()["job_function"] == "AI 应用"
    assert r.json()["seniority"] == "P7"


def test_create_job_requires_text_or_url():
    r = client.post("/api/jobs", json={"title": "No source"})
    assert r.status_code == 422


def test_create_duplicate_returns_409():
    with patch("resualign.api._classify_job", return_value={}):
        first = client.post(
            "/api/jobs",
            json={"title": "Backend", "jd_text": "Python backend."},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/jobs",
            json={"title": "Backend again", "jd_text": "python backend."},
        )
    assert second.status_code == 409
    assert "Duplicate job" in second.json()["detail"]


def test_job_list_filter_get_patch_delete():
    with patch("resualign.api._classify_job", return_value={}):
        client.post(
            "/api/jobs",
            json={
                "title": "Backend",
                "jd_text": "Java backend.",
                "job_function": "后端",
            },
        )
        client.post(
            "/api/jobs",
            json={
                "title": "Frontend",
                "jd_text": "React frontend.",
                "job_function": "前端",
            },
        )

    r = client.get("/api/jobs?job_function=后端")
    assert len(r.json()) == 1
    job_id = r.json()[0]["job_id"]

    r = client.get(f"/api/jobs/{job_id}")
    assert r.status_code == 200
    assert "classification_pending" in r.json()

    r = client.patch(
        f"/api/jobs/{job_id}",
        json={"status": "已投递", "seniority": "高级", "salary_min": 30000},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "applied"  # Bug-12 canonical
    assert r.json()["status_label"] == "已投递"
    assert r.json()["salary_min"] == 30000
    assert r.json()["classification_pending"] == 0

    r = client.get("/api/jobs?status=已投递")
    assert len(r.json()) == 1

    r = client.delete(f"/api/jobs/{job_id}")
    assert r.status_code == 204
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_job_import_json_batch():
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs/import",
            json={
                "jobs": [
                    {
                        "title": "Backend",
                        "jd_text": "Python backend.",
                        "location": "Shanghai",
                    },
                    {
                        "title": "Frontend",
                        "jd_text": "React frontend.",
                    },
                    {
                        "title": "Backend duplicate",
                        "jd_text": "python backend.",
                    },
                    {"jd_text": ""},
                ]
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["queued"] is True
        final = _wait_import(body["import_id"])
    assert final["created"] == 2
    assert final["skipped"] == 2
    assert len(final["errors"]) == 2


def test_job_import_csv():
    csv_text = (
        "title,jd_text,location\n"
        "Backend,Python backend.,Shanghai\n"
        "Frontend,React frontend.,Beijing\n"
    )
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs/import",
            json={"csv_text": csv_text},
        )
        assert r.status_code == 200
        body = r.json()
        final = _wait_import(body["import_id"])
    assert final["created"] == 2
    assert final["errors"] == []


def test_job_import_csv_quoted_fields():
    csv_text = (
        "title,jd_text,location\n"
        '"Backend, Senior","Python, FastAPI, Redis","Shanghai"\n'
    )
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs/import",
            json={"csv_text": csv_text},
        )
        assert r.status_code == 200
        final = _wait_import(r.json()["import_id"])
    assert final["created"] == 1
    jobs = client.get("/api/jobs").json()
    assert jobs[0]["title"] == "Backend, Senior"
    assert "Python, FastAPI, Redis" in jobs[0]["jd_text"]


def test_job_import_marks_done_on_unexpected_error():
    with patch(
        "resualign.api._create_job_from_source",
        side_effect=ValueError("boom"),
    ):
        r = client.post(
            "/api/jobs/import",
            json={"jobs": [{"title": "T", "jd_text": "JD text"}]},
        )
    assert r.status_code == 200
    body = _wait_import(r.json()["import_id"])
    assert body["queued"] is False
    assert body["created"] == 0
    assert any("Import batch failed" in error for error in body["errors"])


def test_job_tenant_isolation():
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={"title": "Backend", "jd_text": "Python backend."},
        )
        job_id = r.json()["job_id"]

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

    assert (
        client.get(f"/api/jobs/{job_id}", headers=other_headers).status_code
        == 404
    )
    assert client.get("/api/jobs", headers=other_headers).json() == []


def test_job_import_rejects_oversized_batch():
    rows = [
        {"title": f"Job {i}", "jd_text": f"Python backend {i}."}
        for i in range(201)
    ]
    r = client.post("/api/jobs/import", json={"jobs": rows})

    assert r.status_code == 422
    assert "maximum" in r.json()["detail"]


def test_job_list_pagination():
    with patch("resualign.api._classify_job", return_value={}):
        for i in range(5):
            client.post(
                "/api/jobs",
                json={
                    "title": f"Job {i}",
                    "jd_text": f"Python backend {i}.",
                },
            )

    page = client.get("/api/jobs?limit=2&offset=2").json()
    assert len(page) == 2
    assert page[0]["title"] == "Job 2"

    all_jobs = client.get("/api/jobs?limit=500").json()
    assert len(all_jobs) == 5


def test_update_job_recomputes_dedupe_key():
    with patch("resualign.api._classify_job", return_value={}):
        first = client.post(
            "/api/jobs",
            json={"title": "Backend", "jd_text": "Python backend."},
        ).json()
        second = client.post(
            "/api/jobs",
            json={"title": "Frontend", "jd_text": "React frontend."},
        ).json()

    r = client.patch(
        f"/api/jobs/{second['job_id']}",
        json={"jd_text": "python backend."},
    )
    assert r.status_code == 409
    assert "Duplicate job" in r.json()["detail"]

    r = client.patch(
        f"/api/jobs/{second['job_id']}",
        json={"jd_text": "Go backend."},
    )
    assert r.status_code == 200
    assert r.json()["jd_text"] == "Go backend."
    assert client.get(
        f"/api/jobs/{first['job_id']}"
    ).status_code == 200


def test_derive_title_skips_company_line():
    text = "美团\n高级后端工程师\n岗位职责：负责服务端开发"
    assert _derive_title(text) == "高级后端工程师"


def test_derive_title_skips_recruit_bracket_line():
    text = "【招聘】字节跳动-北京\n算法工程师（推荐方向）\n工作内容：..."
    assert _derive_title(text) == "算法工程师（推荐方向）"


def test_derive_title_strips_salary_and_city():
    text = "Java开发工程师 15-25K·14薪 北京\n岗位职责：..."
    assert _derive_title(text) == "Java开发工程师"


def test_derive_title_skips_company_intro_and_role_prefix():
    text = "公司简介：xxx科技有限公司\n岗位：Java工程师\n任职要求：..."
    assert _derive_title(text) == "Java工程师"


def test_derive_title_skips_salary_first_line():
    text = "15-25K\nPython\n\n高级工程师"
    assert _derive_title(text) == "高级工程师"


def test_derive_title_keeps_english_first_line():
    text = "Senior Backend Engineer\nPython and FastAPI required"
    assert _derive_title(text) == "Senior Backend Engineer"


def test_derive_title_strips_generic_bracket_prefix():
    text = "【测试岗位】高级数据分析师\n岗位职责：负责数据建模"
    assert _derive_title(text) == "高级数据分析师"


def test_derive_title_keeps_recruit_line_with_role_keyword():
    text = "【招聘】高级数据分析师，岗位职责：负责数据建模，任职要求：..."
    assert _derive_title(text) == "高级数据分析师"


def test_derive_title_strips_company_recruit_prefix():
    text = "公司招聘高级数据分析师 岗位职责：负责数据建模"
    assert _derive_title(text) == "高级数据分析师"


def test_derive_title_truncates_single_line_jd():
    text = "公司：XX科技，地点：上海，高级数据分析师，负责数据建模，任职要求：..."
    assert _derive_title(text) == "高级数据分析师"


def test_derive_title_truncates_single_line_jd_without_separator():
    text = "高级数据分析师岗位职责：负责数据建模任职要求：本科"
    assert _derive_title(text) == "高级数据分析师"


def test_extract_company_location_from_labeled_jd():
    company, location = _extract_company_location(
        "公司：XX科技，地点：上海\n高级数据分析师\n岗位职责：..."
    )
    assert company == "XX科技"
    assert location == "上海"


def test_create_job_extracts_company_location_from_jd():
    with patch("resualign.api._classify_job", return_value={}):
        r = client.post(
            "/api/jobs",
            json={
                "jd_text": (
                    "公司：XX科技，地点：上海\n"
                    "高级数据分析师\n"
                    "岗位职责：负责数据建模"
                )
            },
        )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "高级数据分析师"
    assert body["company"] == "XX科技"
    assert body["location"] == "上海"


def test_derive_title_fallback_when_all_noise():
    assert _derive_title("【招聘】\n薪资面议\nhttps://example.com") == "未命名岗位"


def test_delete_job_cascades_to_pinned_analysis_job():
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer. 20-30K",
                "company": "Acme",
            },
        )
    assert r.status_code == 201
    job = r.json()

    analysis = api_module._registry.create(
        {"jd_text": "Python backend engineer."}, None, tenant_id="local"
    )
    api_module._jobs.update_job(
        "local", job["job_id"], workbench_job_id=analysis.job_id
    )

    r = client.delete(f"/api/jobs/{job['job_id']}")
    assert r.status_code == 204
    assert client.get(f"/api/jobs/{job['job_id']}").status_code == 404
    assert api_module._registry.get(analysis.job_id) is None
    assert api_module._registry.get_payload(analysis.job_id) is None


def test_delete_job_keeps_other_tenants_analysis_job():
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Backend Engineer",
                "jd_text": "Python backend engineer. 20-30K",
                "company": "Acme",
            },
        )
    assert r.status_code == 201
    job = r.json()

    analysis = api_module._registry.create(
        {"jd_text": "Python backend engineer."}, None, tenant_id="other"
    )
    api_module._jobs.update_job(
        "local", job["job_id"], workbench_job_id=analysis.job_id
    )

    r = client.delete(f"/api/jobs/{job['job_id']}")
    assert r.status_code == 204
    assert api_module._registry.get(analysis.job_id) is not None


def test_analysis_status_reports_expired_without_404():
    r = client.get("/api/jobs/missing-analysis/analysis-status")
    assert r.status_code == 200
    assert r.json() == {
        "job_id": "missing-analysis",
        "status": "expired",
    }

    analysis = api_module._registry.create(
        {"jd_text": "Python backend engineer."}, None, tenant_id="local"
    )
    r = client.get(f"/api/jobs/{analysis.job_id}/analysis-status")
    assert r.status_code == 200
    assert r.json()["job_id"] == analysis.job_id
    assert r.json()["status"] == "queued"


def _create_personal_job() -> dict:
    with patch("resualign.api._classify_job", side_effect=_classify):
        r = client.post(
            "/api/jobs",
            json={
                "title": "Followup Engineer",
                "jd_text": "Python backend engineer. 20-30K",
            },
        )
    assert r.status_code == 201
    return r.json()


def test_mark_applied_keeps_manual_followup_schedule():
    """De-bloat: no auto-followup reminder is created on applied; an explicit
    next-step schedule supplied by the user is still persisted unchanged."""
    job = _create_personal_job()
    r = client.patch(
        f"/api/jobs/{job['job_id']}",
        json={
            "status": "applied",
            "applied_at": "2026-08-10",
            "next_step": "准备面试",
            "next_step_due_at": "2026-08-20T10:00:00",
        },
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["status_canonical"] == "applied"
    assert updated["next_step"] == "准备面试"
    assert updated["next_step_due_at"] == "2026-08-20T10:00:00"
