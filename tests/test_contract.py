"""Contract freeze tests for the ResuAlign public HTTP API.

`contracts/openapi-v1.json` is an immutable v1 baseline. Additive changes are
allowed and must be captured in `contracts/openapi-current.json`; removing or
renaming routes, or dropping required fields, fails the additive checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.jobs import JobRegistry
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore

CONTRACTS_DIR = Path(__file__).resolve().parents[1] / "contracts"
OPENAPI_GOLDEN = CONTRACTS_DIR / "openapi-v1.json"
OPENAPI_CURRENT = CONTRACTS_DIR / "openapi-current.json"
INCREMENTAL_MANIFEST = CONTRACTS_DIR / "incremental" / "manifest.json"

CRITICAL_ROUTES = {
    "/health",
    "/api/analyze",
    "/api/jobs",
    "/api/jobs/parse-jd",
    "/api/jobs/import",
    "/api/jobs/{job_id}",
    "/api/jobs/{job_id}/workbench",
    "/api/jobs/{job_id}/appraisal",
    "/api/jobs/{job_id}/workbench/accept",
    "/api/master-resumes",
    "/api/master-resumes/{resume_id}",
    "/api/applications",
    "/api/settings",
}

_auth_cache: dict[str, str] | None = None


@pytest.fixture(autouse=True)
def temp_api_state(tmp_path):
    global _auth_cache
    saved_registry = api_module._registry
    saved_users = api_module._users
    saved_resumes = api_module._resumes
    saved_applications = api_module._applications
    saved_jobs = api_module._jobs
    saved_settings = api_module._settings_store
    saved_personal_mode = api_module._PERSONAL_MODE
    db_path = tmp_path / "contract.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = api_module.MasterResumeStore(db_path=db_path)
    api_module._applications = api_module.ApplicationStore(db_path=db_path)
    api_module._jobs = api_module.JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
    api_module._payloads = {}
    _auth_cache = None
    yield
    api_module._registry = saved_registry
    api_module._users = saved_users
    api_module._resumes = saved_resumes
    api_module._applications = saved_applications
    api_module._jobs = saved_jobs
    api_module._settings_store = saved_settings
    api_module._PERSONAL_MODE = saved_personal_mode
    _auth_cache = None


def _auth_headers(client: TestClient) -> dict[str, str]:
    global _auth_cache
    if _auth_cache is not None:
        return _auth_cache
    assert (
        client.post(
            "/api/auth/signup",
            json={"email": "contract@example.com", "password": "password-123"},
        ).status_code
        == 201
    )
    r = client.post(
        "/api/auth/login",
        json={"email": "contract@example.com", "password": "password-123"},
    )
    assert r.status_code == 200
    _auth_cache = {"Authorization": f"Bearer {r.json()['token']}"}
    return _auth_cache


def _assert_additive_schema(golden: dict, current: dict, path: str) -> None:
    if not isinstance(golden, dict) or not isinstance(current, dict):
        return
    if "required" in golden:
        missing_required = set(golden["required"]) - set(current.get("required", []))
        assert not missing_required, (
            f"{path} dropped required fields: {sorted(missing_required)}"
        )
    golden_props = golden.get("properties")
    if isinstance(golden_props, dict):
        current_props = current.get("properties", {})
        for name, prop_schema in golden_props.items():
            assert name in current_props, f"{path}.properties.{name} removed"
            _assert_additive_schema(
                prop_schema,
                current_props[name],
                f"{path}.properties.{name}",
            )
    if "items" in golden:
        _assert_additive_schema(golden["items"], current.get("items", {}), f"{path}.items")
    for key in ("allOf", "anyOf", "oneOf"):
        if key in golden:
            assert len(current.get(key, [])) >= len(golden[key]), (
                f"{path}.{key} shrank"
            )


def test_openapi_is_additive_over_golden():
    current = app.openapi()
    golden = json.loads(OPENAPI_GOLDEN.read_text(encoding="utf-8"))
    current_paths = current["paths"]
    golden_paths = golden["paths"]
    missing_paths = set(golden_paths) - set(current_paths)
    assert not missing_paths, f"Golden routes removed: {sorted(missing_paths)}"
    for path, ops in golden_paths.items():
        for method, op in ops.items():
            if method.lower() not in {
                "get", "post", "put", "patch", "delete",
            }:
                continue
            assert method.lower() in current_paths[path], (
                f"Golden operation removed: {method.upper()} {path}"
            )
            current_op = current_paths[path][method.lower()]
            if "operationId" in op:
                assert current_op.get("operationId") == op["operationId"], (
                    f"operationId renamed: {method.upper()} {path} "
                    f"({op['operationId']} -> {current_op.get('operationId')})"
                )
    golden_schemas = golden["components"]["schemas"]
    current_schemas = current["components"]["schemas"]
    for name, schema in golden_schemas.items():
        assert name in current_schemas, f"Golden schema removed: {name}"
        _assert_additive_schema(schema, current_schemas[name], f"schemas.{name}")


def test_openapi_current_snapshot_matches():
    current = app.openapi()
    snapshot = json.loads(OPENAPI_CURRENT.read_text(encoding="utf-8"))
    assert current == snapshot, (
        "OpenAPI drifted from contracts/openapi-current.json; regenerate "
        "the snapshot deliberately after adding routes or fields."
    )


def test_incremental_manifest_matches_openapi_diff():
    manifest = json.loads(INCREMENTAL_MANIFEST.read_text(encoding="utf-8"))
    current = app.openapi()
    golden = json.loads(OPENAPI_GOLDEN.read_text(encoding="utf-8"))
    new_paths = set(current["paths"]) - set(golden["paths"])
    new_schemas = (
        set(current["components"]["schemas"])
        - set(golden["components"]["schemas"])
    )
    assert set(manifest["paths"]) == new_paths
    assert set(manifest["schemas"]) == new_schemas
    assert manifest["operations"] == []
    assert manifest["breaking_changes"] == []


def test_critical_routes_exist():
    paths = set(app.openapi()["paths"])
    missing = CRITICAL_ROUTES - paths
    assert not missing, f"Critical routes missing from OpenAPI: {sorted(missing)}"


def test_health_contract():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"db", "cache"}


def test_job_library_response_shape_is_additive():
    client = TestClient(app)
    headers = _auth_headers(client)
    created = client.post(
        "/api/jobs",
        json={
            "title": "Contract backend role",
            "jd_text": "Python backend engineer with FastAPI.",
            "company": "ContractCo",
        },
        headers=headers,
    )
    assert created.status_code == 201
    job = created.json()
    required = {
        "job_id",
        "tenant_id",
        "title",
        "jd_text",
        "company",
        "status",
        "source_type",
        "created_at",
        "updated_at",
    }
    assert required <= set(job)
    listing = client.get("/api/jobs", headers=headers)
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)
    assert all(required <= set(item) for item in listing.json())


def test_master_resume_and_application_contract():
    client = TestClient(app)
    headers = _auth_headers(client)
    resume = client.post(
        "/api/master-resumes",
        json={
            "title": "Master contract resume",
            "content": "# Experience\nPython backend engineer.",
        },
        headers=headers,
    )
    assert resume.status_code == 201
    resume_id = resume.json()["resume_id"]
    application = client.post(
        "/api/applications",
        json={
            "title": "Contract application",
            "master_resume_id": resume_id,
            "jd_text": "FastAPI backend role",
        },
        headers=headers,
    )
    assert application.status_code == 201
    app_body = application.json()
    assert {"application_id", "status", "master_resume_id", "created_at"} <= set(
        app_body
    )


def test_settings_contract():
    client = TestClient(app)
    headers = _auth_headers(client)
    r = client.get("/api/settings", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
