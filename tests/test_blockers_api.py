"""API tests for the Sprint 3 automation rules / blockers / fetch-url routes."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.crawler import CrawlError
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
        "tech_tags": ["Python"],
    }


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
        "settings": getattr(api_module, "_settings_store", None),
    }
    db_path = tmp_path / "blockers-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    _other_cache = None
    yield
    for key, value in saved.items():
        setattr(api_module, key, value)
    for limiter in (
        api_module._auth_rate_limiter,
        api_module._analyze_rate_limiter,
        api_module._import_rate_limiter,
    ):
        limiter.reset()
    _auth_cache = None
    _other_cache = None


def _auth_headers(cache_name="primary"):
    global _auth_cache, _other_cache
    cache = _auth_cache if cache_name == "primary" else _other_cache
    if cache is not None:
        return cache
    email = f"{cache_name}-blockers@example.com"
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": email, "password": "password-123"},
        ).status_code
        == 201
    )
    token = client.post(
        "/api/auth/login",
        json={"email": email, "password": "password-123"},
    ).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    if cache_name == "primary":
        _auth_cache = headers
    else:
        _other_cache = headers
    return headers


def _crawl_ok(text="负责后端服务开发。月薪 25-35K，双休。", city="上海"):
    def _fetch(url, meta=None, **kwargs):
        if meta is not None:
            meta["title"] = "后端开发工程师"
            meta["company"] = "Acme"
            meta["city"] = city
        return text
    return _fetch


# -- /api/automation/rules ---------------------------------------------------


def test_rules_require_auth():
    assert client.get("/api/automation/rules").status_code == 401


def test_automation_rule_crud_flow():
    headers = _auth_headers()
    created = client.post(
        "/api/automation/rules",
        json={"rule_type": "blacklist", "value": "外包，单休", "label": "外包拦截"},
        headers=headers,
    )
    assert created.status_code == 201
    rule = created.json()
    assert rule["rule_type"] == "blacklist"
    assert rule["enabled"] is True
    assert rule["value"] == "外包，单休"

    listed = client.get("/api/automation/rules", headers=headers)
    assert listed.status_code == 200
    assert [r["rule_id"] for r in listed.json()] == [rule["rule_id"]]

    updated = client.put(
        f"/api/automation/rules/{rule['rule_id']}",
        json={"enabled": False, "value": "单休"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is False
    assert updated.json()["value"] == "单休"

    deleted = client.delete(
        f"/api/automation/rules/{rule['rule_id']}", headers=headers
    )
    assert deleted.status_code == 204
    assert client.get("/api/automation/rules", headers=headers).json() == []


def test_automation_rule_validation_errors():
    headers = _auth_headers()
    bad_type = client.post(
        "/api/automation/rules",
        json={"rule_type": "nope", "value": "外包"},
        headers=headers,
    )
    assert bad_type.status_code == 422
    empty_value = client.post(
        "/api/automation/rules",
        json={"rule_type": "blacklist", "value": "  "},
        headers=headers,
    )
    assert empty_value.status_code == 422
    bad_salary = client.post(
        "/api/automation/rules",
        json={"rule_type": "min_salary", "value": "abc"},
        headers=headers,
    )
    assert bad_salary.status_code == 422


def test_automation_rule_404_on_missing():
    headers = _auth_headers()
    assert (
        client.put(
            "/api/automation/rules/missing",
            json={"enabled": False},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.delete(
            "/api/automation/rules/missing", headers=headers
        ).status_code
        == 404
    )


def test_automation_rules_tenant_isolation():
    primary = _auth_headers("primary")
    other = _auth_headers("other")
    rule = client.post(
        "/api/automation/rules",
        json={"rule_type": "blacklist", "value": "外包"},
        headers=primary,
    ).json()
    assert client.get("/api/automation/rules", headers=other).json() == []
    assert (
        client.delete(f"/api/automation/rules/{rule['rule_id']}", headers=other).status_code
        == 404
    )


# -- /api/jobs/fetch-url -----------------------------------------------------


def test_fetch_url_requires_auth():
    assert (
        client.post("/api/jobs/fetch-url", json={"url": "https://x"}).status_code
        == 401
    )


def test_fetch_url_created():
    headers = _auth_headers()
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()), patch.object(
        api_module, "_classify_job", side_effect=_classify
    ):
        r = client.post(
            "/api/jobs/fetch-url",
            json={"url": "https://example.com/jobs/1"},
            headers=headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "created"
    assert body["job_id"]
    job = client.get(f"/api/jobs/{body['job_id']}", headers=headers)
    assert job.status_code == 200
    assert job.json()["source_url"] == "https://example.com/jobs/1"


def test_fetch_url_duplicate():
    headers = _auth_headers()
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok()), patch.object(
        api_module, "_classify_job", side_effect=_classify
    ):
        first = client.post(
            "/api/jobs/fetch-url",
            json={"url": "https://example.com/jobs/1"},
            headers=headers,
        ).json()
        second = client.post(
            "/api/jobs/fetch-url",
            json={"url": "https://example.com/jobs/1/"},
            headers=headers,
        ).json()
    assert first["status"] == "created"
    assert second["status"] == "duplicate"
    assert second["job_id"] == first["job_id"]


def test_fetch_url_rule_rejected():
    headers = _auth_headers()
    client.post(
        "/api/automation/rules",
        json={"rule_type": "city_whitelist", "value": "上海"},
        headers=headers,
    )
    with patch.object(api_module, "crawl_jd", side_effect=_crawl_ok(city="北京")), patch.object(
        api_module, "_classify_job", side_effect=_classify
    ):
        r = client.post(
            "/api/jobs/fetch-url",
            json={"url": "https://example.com/jobs/1"},
            headers=headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rule_rejected"
    assert body["rule_type"] == "city_whitelist"
    assert body["blocker_id"]


def test_fetch_url_crawl_blocked():
    headers = _auth_headers()
    with patch.object(
        api_module,
        "crawl_jd",
        side_effect=CrawlError(
            "Failed to fetch https://x: HTTP 403", category="http"
        ),
    ):
        r = client.post(
            "/api/jobs/fetch-url",
            json={"url": "https://example.com/jobs/1"},
            headers=headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["category"] == "login_required"
    assert body["blocker_id"]


def test_fetch_url_invalid_url_blocked():
    headers = _auth_headers()
    r = client.post(
        "/api/jobs/fetch-url",
        json={"url": "not-a-url"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["category"] == "invalid_url"


# -- /api/blockers -----------------------------------------------------------


def test_blockers_require_auth():
    assert client.get("/api/blockers").status_code == 401


def test_list_blockers_status_filter():
    headers = _auth_headers()
    client.post(
        "/api/jobs/fetch-url", json={"url": "not-a-url"}, headers=headers
    )
    pending = client.get("/api/blockers?status=pending", headers=headers)
    assert pending.status_code == 200
    assert len(pending.json()) == 1
    assert pending.json()[0]["category"] == "invalid_url"
    assert client.get("/api/blockers?status=resolved", headers=headers).json() == []


def test_ignore_blocker_endpoint():
    headers = _auth_headers()
    body = client.post(
        "/api/jobs/fetch-url", json={"url": "not-a-url"}, headers=headers
    ).json()
    blocker_id = body["blocker_id"]
    r = client.post(f"/api/blockers/{blocker_id}/ignore", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
    assert client.get("/api/blockers?status=pending", headers=headers).json() == []
    assert client.get("/api/blockers?status=ignored", headers=headers).json() != []


def test_ignore_blocker_404():
    headers = _auth_headers()
    assert (
        client.post("/api/blockers/missing/ignore", headers=headers).status_code
        == 404
    )


def test_resolve_blocker_endpoint():
    headers = _auth_headers()
    body = client.post(
        "/api/jobs/fetch-url", json={"url": "not-a-url"}, headers=headers
    ).json()
    blocker_id = body["blocker_id"]
    with patch.object(api_module, "_classify_job", side_effect=_classify):
        r = client.post(
            f"/api/blockers/{blocker_id}/resolve",
            json={"manual_text": "负责后端开发。月薪 20-30K。"},
            headers=headers,
        )
    assert r.status_code == 200
    result = r.json()
    assert result["blocker"]["status"] == "resolved"
    assert result["blocker"]["job_id"] == result["job"]["job_id"]
    # The resolved blocker leaves the pending queue.
    assert client.get("/api/blockers?status=pending", headers=headers).json() == []


def test_resolve_blocker_empty_text_keeps_pending():
    headers = _auth_headers()
    body = client.post(
        "/api/jobs/fetch-url", json={"url": "not-a-url"}, headers=headers
    ).json()
    blocker_id = body["blocker_id"]
    r = client.post(
        f"/api/blockers/{blocker_id}/resolve",
        json={"manual_text": "   "},
        headers=headers,
    )
    assert r.status_code == 422
    pending = client.get("/api/blockers?status=pending", headers=headers).json()
    assert [b["blocker_id"] for b in pending] == [blocker_id]


def test_blocker_tenant_isolation():
    primary = _auth_headers("primary")
    other = _auth_headers("other")
    body = client.post(
        "/api/jobs/fetch-url", json={"url": "not-a-url"}, headers=primary
    ).json()
    blocker_id = body["blocker_id"]
    assert client.get("/api/blockers", headers=other).json() == []
    assert (
        client.post(
            f"/api/blockers/{blocker_id}/ignore", headers=other
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/blockers/{blocker_id}/resolve",
            json={"manual_text": "负责后端开发"},
            headers=other,
        ).status_code
        == 404
    )
