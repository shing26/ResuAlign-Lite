"""A9: input caps on text fields and request-body size guard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JobLibraryStore
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    """Isolate stores for endpoint-level tests (personal mode writes)."""
    saved = {
        name: getattr(api_module, name)
        for name in ("_users", "_jobs", "_settings_store", "_PERSONAL_MODE")
    }
    db_path = tmp_path / "limits.db"
    api_module._users = UserStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    yield
    for name, value in saved.items():
        setattr(api_module, name, value)


def test_oversized_jd_text_rejected_with_422():
    payload = {
        "title": "Backend role",
        "jd_text": "x" * 100_001,
        "company": "Acme",
    }
    r = client.post("/api/jobs", json=payload)
    assert r.status_code == 422
    assert any(
        "100000" in str(err)
        for err in r.json()["detail"]
        if isinstance(err, dict)
    )


def test_oversized_resume_text_rejected_with_422():
    r = client.post("/api/analyze", json={"resume_text": "x" * 200_001})
    assert r.status_code == 422


def test_oversized_draft_rejected_with_422():
    r = client.post(
        "/api/jobs/does-not-exist/final-draft",
        json={"draft": "x" * 200_001},
    )
    assert r.status_code == 422


def test_oversized_custom_prompt_rejected_with_422():
    r = client.patch(
        "/api/jobs/some-job",
        json={"custom_prompt": "y" * 4_001},
    )
    assert r.status_code == 422


def test_oversized_csv_text_rejected_with_422():
    r = client.post(
        "/api/jobs/import",
        json={"csv_text": "z" * 2_000_001},
    )
    assert r.status_code == 422


def test_at_limit_jd_text_still_accepted_without_llm(monkeypatch):
    """100_000 chars is the boundary: exactly at the limit must not 422."""
    import resualign.api as api_module

    monkeypatch.setattr(
        api_module, "_classify_job", lambda *a, **k: {}
    )
    payload = {
        "title": "Boundary role",
        "jd_text": "d" * 100_000,
    }
    r = client.post("/api/jobs", json=payload)
    # Classification is mocked; only validation and storage run.
    assert r.status_code == 201, r.text


def test_body_size_middleware_rejects_oversized_content_length():
    import asyncio

    class _FakeRequest:
        headers = {"content-length": str(api_module._MAX_BODY_BYTES + 1)}

    response = asyncio.run(
        api_module._limit_request_body_size(_FakeRequest(), None)
    )
    assert response.status_code == 413


def test_body_size_middleware_passes_small_requests():
    import asyncio

    class _FakeRequest:
        headers = {"content-length": "1024"}

    async def _call_next(_request):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=200, content={"ok": True})

    response = asyncio.run(
        api_module._limit_request_body_size(_FakeRequest(), _call_next)
    )
    assert response.status_code == 200


def test_oversized_body_rejected_with_413_end_to_end():
    body = b"x" * (api_module._MAX_BODY_BYTES + 1024)
    r = client.post(
        "/api/analyze",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413
    assert "Request body too large" in r.json()["detail"]
