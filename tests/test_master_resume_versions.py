"""Sprint 4: API tests for master resume version history and rollback.

The resume center (frontend) renders a version timeline from
``GET /api/master-resumes/{resume_id}`` — the ``versions`` array where
each entry is ``{version, content, created_at}``. These tests lock that
roundtrip (v1/v2 both present with content and created_at), the rollback
switch semantics (current_version + content restored, full history kept),
and the 404 behavior for unknown resumes / versions.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.workspace import MasterResumeStore, UserStore

client = TestClient(app)
_auth_cache = None
_other_cache = None

V1_CONTENT = "# Python Developer\n\n5 years of backend experience."
V2_CONTENT = "# Python Developer\n\n5 years of backend experience.\n\nFastAPI + Redis."
V3_CONTENT = "# Python Developer\n\n5 years of backend experience.\n\nFastAPI + Docker."


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
        "settings_store": api_module._settings_store,
        "personal_mode": api_module._PERSONAL_MODE,
        "payloads": api_module._payloads,
    }
    db_path = tmp_path / "resumes.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = api_module.ApplicationStore(db_path=db_path)
    api_module._jobs = api_module.JobLibraryStore(db_path=db_path)
    api_module._settings_store = api_module.SettingsStore(db_path=db_path)
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
    for name, value in saved.items():
        setattr(api_module, name, value)
    _auth_cache = None
    _other_cache = None


def _auth_headers() -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    client.post(
        "/api/auth/signup",
        json={"email": "versions@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "versions@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _other_headers() -> dict[str, str]:
    global _other_cache
    if _other_cache is not None:
        return _other_cache
    client.post(
        "/api/auth/signup",
        json={"email": "other@example.com", "password": "other-password"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "other@example.com", "password": "other-password"},
    ).json()["token"]
    _other_cache = {"Authorization": f"Bearer {token}"}
    return _other_cache


def _create_resume(title: str = "Master Resume", content: str = V1_CONTENT) -> dict:
    r = client.post(
        "/api/master-resumes",
        json={"title": title, "content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 201
    return r.json()


def _update_resume(resume_id: str, content: str) -> dict:
    r = client.patch(
        f"/api/master-resumes/{resume_id}",
        json={"content": content},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    return r.json()


def _detail(resume_id: str) -> dict:
    r = client.get(
        f"/api/master-resumes/{resume_id}", headers=_auth_headers()
    )
    assert r.status_code == 200
    return r.json()


def test_master_resume_version_list_roundtrip_content_and_created_at():
    """Two versions roundtrip through the detail endpoint with full fields."""
    created = _create_resume()
    resume_id = created["resume_id"]
    assert created["current_version"] == 1

    updated = _update_resume(resume_id, V2_CONTENT)
    assert updated["current_version"] == 2

    detail = _detail(resume_id)
    assert detail["current_version"] == 2
    assert detail["content"] == V2_CONTENT

    versions = detail["versions"]
    assert [v["version"] for v in versions] == [1, 2]
    assert {tuple(sorted(v.keys())) for v in versions} == {
        ("content", "created_at", "version")
    }
    assert versions[0]["content"] == V1_CONTENT
    assert versions[1]["content"] == V2_CONTENT
    # created_at is a real timestamp and monotonically increasing.
    assert isinstance(versions[0]["created_at"], float)
    assert versions[0]["created_at"] <= versions[1]["created_at"]


def test_master_resume_rollback_switches_version_and_restores_content():
    created = _create_resume()
    resume_id = created["resume_id"]
    _update_resume(resume_id, V2_CONTENT)

    r = client.post(
        f"/api/master-resumes/{resume_id}/rollback",
        json={"version": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    rolled = r.json()
    assert rolled["current_version"] == 1
    assert rolled["content"] == V1_CONTENT


def test_master_resume_rollback_preserves_full_history():
    created = _create_resume()
    resume_id = created["resume_id"]
    _update_resume(resume_id, V2_CONTENT)

    client.post(
        f"/api/master-resumes/{resume_id}/rollback",
        json={"version": 1},
        headers=_auth_headers(),
    )

    detail = _detail(resume_id)
    assert detail["current_version"] == 1
    assert detail["content"] == V1_CONTENT
    # History is immutable: v2 still listed with its original content.
    versions = detail["versions"]
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[1]["content"] == V2_CONTENT


def test_master_resume_update_after_rollback_creates_next_version():
    created = _create_resume()
    resume_id = created["resume_id"]
    _update_resume(resume_id, V2_CONTENT)
    client.post(
        f"/api/master-resumes/{resume_id}/rollback",
        json={"version": 1},
        headers=_auth_headers(),
    )

    updated = _update_resume(resume_id, V3_CONTENT)
    assert updated["current_version"] == 3
    assert updated["content"] == V3_CONTENT

    detail = _detail(resume_id)
    assert [v["version"] for v in detail["versions"]] == [1, 2, 3]
    assert detail["versions"][2]["content"] == V3_CONTENT


def test_master_resume_rollback_missing_version_returns_404():
    created = _create_resume()
    resume_id = created["resume_id"]

    r = client.post(
        f"/api/master-resumes/{resume_id}/rollback",
        json={"version": 99},
        headers=_auth_headers(),
    )
    assert r.status_code == 404

    # Current version untouched by a failed rollback.
    assert _detail(resume_id)["current_version"] == 1


def test_master_resume_rollback_missing_resume_returns_404():
    r = client.post(
        "/api/master-resumes/does-not-exist/rollback",
        json={"version": 1},
        headers=_auth_headers(),
    )
    assert r.status_code == 404


def test_master_resume_versions_are_tenant_scoped():
    """Another user cannot read or roll back a resume they do not own."""
    created = _create_resume()
    resume_id = created["resume_id"]
    _update_resume(resume_id, V2_CONTENT)

    foreign = client.get(
        f"/api/master-resumes/{resume_id}", headers=_other_headers()
    )
    assert foreign.status_code == 404

    foreign_rollback = client.post(
        f"/api/master-resumes/{resume_id}/rollback",
        json={"version": 1},
        headers=_other_headers(),
    )
    assert foreign_rollback.status_code == 404

    # Owner's history remains intact.
    assert _detail(resume_id)["current_version"] == 2
