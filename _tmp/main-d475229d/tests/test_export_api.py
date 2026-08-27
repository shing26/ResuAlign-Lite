"""API tests for the canonical final-draft export endpoint (MVP-03)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import (
    ApplicationStore,
    MasterResumeStore,
    UserStore,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": api_module._jobs,
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "export-api.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)


def _create_job(title="Backend Engineer", jd_text="Python backend."):
    r = client.post(
        "/api/jobs",
        json={"title": title, "jd_text": jd_text},
    )
    assert r.status_code == 201
    return r.json()


def _seed_accepted_draft(job):
    api_module._jobs.save_alignment(
        job["tenant_id"],
        job["job_id"],
        jd_profile={"must_have_skills": ["Python"]},
        gap_report={"missing_keywords": ["Redis"]},
        match_score=81.5,
        diffs=[
            {
                "diff_id": "d1",
                "type": "modify",
                "section": "experience",
                "original": "Python developer.",
                "proposed": "Python developer with Redis caching.",
                "reason": "JD match",
                "confidence": "high",
                "provenance": "Python developer.",
                "provenance_state": "verified",
            },
            {
                "diff_id": "d2",
                "type": "add",
                "section": "skills",
                "original": "",
                "proposed": "Redis cluster operations.",
                "reason": "Gap coverage",
                "confidence": "medium",
                "provenance_quote": "Redis",
                "provenance_state": "verified",
            },
        ],
        invalid_diffs=[],
        draft="# Experience\nPython developer with Redis caching.",
        model="test-model",
        prompt_version="engine.v1",
    )
    saved = client.post(
        f"/api/jobs/{job['job_id']}/final-draft",
        json={
            "draft": "# Experience\nPython developer with Redis caching.",
            "accepted_diff_ids": ["d1"],
        },
    )
    assert saved.status_code == 200


def test_export_markdown_contains_meta_and_accepted_diff():
    job = _create_job()
    _seed_accepted_draft(job)

    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "markdown"
    assert body["job_title"] == "Backend Engineer"
    assert body["final_draft_version"] == 1
    assert body["filename"] == "resualign-Backend-Engineer-v1.md"
    assert body["meta"]["model"] == "test-model"
    assert body["meta"]["prompt_version"] == "engine.v1"
    assert body["accepted_diff_ids"] == ["d1"]
    assert len(body["accepted_diffs"]) == 1
    assert body["accepted_diffs"][0]["diff_id"] == "d1"
    assert body["content"].startswith("# Backend Engineer")
    assert "engine.v1" in body["content"]
    assert "Python developer with Redis caching" in body["content"]


def test_export_json_is_canonical_and_ignores_client_diff_ids():
    job = _create_job()
    _seed_accepted_draft(job)

    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["format"] == "json"
    assert body["accepted_diff_ids"] == ["d1"]
    assert len(body["accepted_diffs"]) == 1
    assert body["content"].startswith("# Experience")
    assert body["filename"] == "resualign-Backend-Engineer-v1.json"


def test_export_pdf_returns_print_html_contract():
    job = _create_job()
    _seed_accepted_draft(job)

    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "pdf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["render"] == "print-html"
    assert body["print_target"] == "#print-root"
    assert "<article" in body["content"]
    assert "Python developer with Redis caching" in body["content"]
    assert "engine.v1" in body["content"]
    assert body["filename"] == "resualign-Backend-Engineer-v1.pdf"


def test_export_missing_job_returns_404():
    r = client.post(
        "/api/jobs/does-not-exist/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 404


def test_export_without_final_draft_returns_422():
    job = _create_job()
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 422
    assert "尚未保存定稿" in r.json()["detail"]


def test_export_unknown_format_returns_422():
    job = _create_job()
    _seed_accepted_draft(job)
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "docx"},
    )
    assert r.status_code == 422


def test_export_cross_tenant_returns_404():
    other = api_module._jobs.create_job(
        tenant_id="other-tenant",
        title="Other",
        jd_text="Other JD.",
    )
    api_module._jobs.save_final_draft(
        "other-tenant",
        other["job_id"],
        "Cross tenant draft",
    )
    r = client.post(
        f"/api/jobs/{other['job_id']}/exports",
        json={"format": "markdown"},
    )
    assert r.status_code == 404


def test_export_legacy_final_draft_without_alignment_meta():
    job = _create_job()
    api_module._jobs.save_final_draft(
        job["tenant_id"],
        job["job_id"],
        "Legacy final draft",
    )
    r = client.post(
        f"/api/jobs/{job['job_id']}/exports",
        json={"format": "json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["model"] is None
    assert body["meta"]["prompt_version"] is None
    assert body["meta"]["match_score"] is None
    assert body["accepted_diff_ids"] == []
    assert body["content"] == "Legacy final draft"
