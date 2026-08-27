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
    "/api/jobs/{job_id}/workbench/accept",
    "/api/master-resumes",
    "/api/master-resumes/{resume_id}",
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


def _manifest() -> dict:
    return json.loads(INCREMENTAL_MANIFEST.read_text(encoding="utf-8"))


def _assert_additive_schema(
    golden: dict,
    current: dict,
    path: str,
    removed_props=frozenset(),
) -> None:
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
            if name in removed_props:
                continue
            assert name in current_props, f"{path}.properties.{name} removed"
            _assert_additive_schema(
                prop_schema,
                current_props[name],
                f"{path}.properties.{name}",
                removed_props,
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
    manifest = _manifest()
    removed_paths = set(manifest.get("removed_paths", []))
    current_paths = current["paths"]
    golden_paths = golden["paths"]
    missing_paths = (
        set(golden_paths) - set(current_paths) - removed_paths
    )
    assert not missing_paths, f"Golden routes removed: {sorted(missing_paths)}"
    for path, ops in golden_paths.items():
        if path in removed_paths:
            continue
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
    removed_props = manifest.get("removed_schema_properties", {})
    removed_schemas = set(manifest.get("removed_schemas", []))
    for name, schema in golden_schemas.items():
        if name in removed_schemas:
            continue
        assert name in current_schemas, f"Golden schema removed: {name}"
        _assert_additive_schema(
            schema,
            current_schemas[name],
            f"schemas.{name}",
            set(removed_props.get(name, [])),
        )


def test_openapi_current_snapshot_matches():
    current = app.openapi()
    snapshot = json.loads(OPENAPI_CURRENT.read_text(encoding="utf-8"))
    assert current == snapshot, (
        "OpenAPI drifted from contracts/openapi-current.json; regenerate "
        "the snapshot deliberately after adding routes or fields."
    )


def test_incremental_manifest_matches_openapi_diff():
    manifest = _manifest()
    current = app.openapi()
    golden = json.loads(OPENAPI_GOLDEN.read_text(encoding="utf-8"))
    new_paths = set(current["paths"]) - set(golden["paths"])
    new_schemas = (
        set(current["components"]["schemas"])
        - set(golden["components"]["schemas"])
    )
    removed_paths = set(golden["paths"]) - set(current["paths"])
    removed_schemas_set = (
        set(golden["components"]["schemas"])
        - set(current["components"]["schemas"])
    )
    removed_props: dict[str, list[str]] = {}
    for name, schema in golden["components"]["schemas"].items():
        if name not in current["components"]["schemas"]:
            continue
        golden_props = set((schema.get("properties") or {}).keys())
        current_props = set(
            (current["components"]["schemas"][name].get("properties") or {}).keys()
        )
        missing = sorted(golden_props - current_props)
        if missing:
            removed_props[name] = missing
    assert set(manifest["paths"]) == new_paths
    assert set(manifest["schemas"]) == new_schemas
    assert set(manifest["removed_paths"]) == removed_paths
    assert set(manifest.get("removed_schemas", [])) == removed_schemas_set
    declared_removed_props = manifest["removed_schema_properties"]
    for name, props in declared_removed_props.items():
        assert name in current["components"]["schemas"], (
            f"removed props declared for unknown schema {name}"
        )
        current_props = set(
            (current["components"]["schemas"][name].get("properties") or {}).keys()
        )
        for prop in props:
            assert prop not in current_props, f"{name}.properties.{prop} still present"
    for name, props in removed_props.items():
        assert declared_removed_props.get(name) == props
    assert manifest["operations"] == []
    break_types = [item["type"] for item in manifest["breaking_changes"]]
    assert break_types.count("remove_path") == len(manifest["removed_paths"])
    assert break_types.count("remove_schema") == len(
        manifest.get("removed_schemas", [])
    )
    assert break_types.count("remove_schema_property") == sum(
        len(props) for props in declared_removed_props.values()
    )
    for item in manifest["breaking_changes"]:
        if item["type"] == "remove_path":
            assert item["path"] in removed_paths
        elif item["type"] == "remove_schema":
            assert item["schema"] in removed_schemas_set
        elif item["type"] == "remove_schema_property":
            assert item["property"] in declared_removed_props.get(item["schema"], [])


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


def test_master_resume_contract():
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
    detail = client.get(
        f"/api/master-resumes/{resume_id}", headers=headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert {"resume_id", "title", "content", "current_version"} <= set(body)


def test_settings_contract():
    client = TestClient(app)
    headers = _auth_headers(client)
    r = client.get("/api/settings", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
