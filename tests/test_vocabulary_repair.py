"""B1: classification vocabulary whitelist repair and validation."""

import json
import time

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.api import app
from resualign.job_library import JOB_STATUSES
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


@pytest.fixture(autouse=True)
def temp_stores(tmp_path):
    global _auth_cache
    saved = {
        "registry": api_module._registry,
        "users": api_module._users,
        "resumes": getattr(api_module, "_resumes", None),
        "applications": getattr(api_module, "_applications", None),
        "jobs": getattr(api_module, "_jobs", None),
        "settings": getattr(api_module, "_settings_store", None),
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "vocab.db"
    api_module._registry = JobRegistry(db_path=db_path)
    api_module._users = UserStore(db_path=db_path)
    api_module._resumes = MasterResumeStore(db_path=db_path)
    api_module._applications = ApplicationStore(db_path=db_path)
    api_module._jobs = JobLibraryStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = False
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
        json={"email": "vocab@example.com", "password": "password-123"},
    )
    token = client.post(
        "/api/auth/login",
        json={"email": "vocab@example.com", "password": "password-123"},
    ).json()["token"]
    _auth_cache = {"Authorization": f"Bearer {token}"}
    return _auth_cache


def _corrupt_statuses(store, tenant_id, statuses):
    """Write a corrupted classification vocabulary row directly to SQLite."""
    with store._lock:
        store._ensure_initialized()
        with store._connect() as conn:
            conn.execute(
                "INSERT INTO user_settings ("
                "tenant_id, classification_vocabulary_json, updated_at"
                ") VALUES (?, ?, ?) "
                "ON CONFLICT(tenant_id) DO UPDATE SET "
                "classification_vocabulary_json = excluded."
                "classification_vocabulary_json, "
                "updated_at = excluded.updated_at",
                (
                    tenant_id,
                    json.dumps(
                        {
                            "job_functions": ["后端", "前端"],
                            "seniorities": ["高级"],
                            "statuses": statuses,
                        },
                        ensure_ascii=False,
                    ),
                    time.time(),
                ),
            )


def test_get_settings_repairs_invalid_statuses_to_builtin_five(tmp_path):
    store = SettingsStore(db_path=tmp_path / "s.db")
    tenant = "tenant-repair"
    # Corrupt row: partial + invalid statuses (the B1 audit case).
    _corrupt_statuses(store, tenant, ["待定", "已投递"])
    settings = store.get_settings(tenant)
    assert settings["classification_vocabulary"]["statuses"] == list(
        JOB_STATUSES
    )
    # The repair is durable: the next read no longer needs to rewrite.
    again = store.get_settings(tenant)
    assert again["classification_vocabulary"]["statuses"] == list(
        JOB_STATUSES
    )


def test_get_settings_backfills_missing_statuses(tmp_path):
    store = SettingsStore(db_path=tmp_path / "s.db")
    tenant = "tenant-backfill"
    _corrupt_statuses(store, tenant, ["已投递"])
    settings = store.get_settings(tenant)
    statuses = settings["classification_vocabulary"]["statuses"]
    assert "已投递" in statuses
    assert set(JOB_STATUSES) == set(statuses)
    assert len(statuses) == len(JOB_STATUSES)


def test_put_settings_rejects_invalid_statuses():
    r = client.put(
        "/api/settings",
        json={
            "classification_vocabulary": {
                "job_functions": ["后端"],
                "seniorities": ["高级"],
                "statuses": ["待定", "已投递"],
            }
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 422
    body = r.json()
    assert "非法" in body["detail"] or "待定" in body["detail"]


def test_put_settings_rejects_empty_job_functions():
    r = client.put(
        "/api/settings",
        json={
            "classification_vocabulary": {
                "job_functions": [],
                "seniorities": ["高级"],
                "statuses": ["已投递"],
            }
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_put_settings_accepts_valid_vocabulary():
    r = client.put(
        "/api/settings",
        json={
            "classification_vocabulary": {
                "job_functions": ["后端", "前端"],
                "seniorities": ["高级", "资深"],
                "statuses": ["已投递", "面试中"],
            }
        },
        headers=_auth_headers(),
    )
    assert r.status_code == 200
    body = r.json()
    statuses = body["classification_vocabulary"]["statuses"]
    # GET backfills missing canonical statuses while keeping the saved ones.
    assert statuses[:2] == ["已投递", "面试中"]
    assert set(statuses) == set(JOB_STATUSES)


def test_store_update_rejects_invalid_statuses_directly(tmp_path):
    store = SettingsStore(db_path=tmp_path / "s.db")
    with pytest.raises(api_module.UserStoreError, match="statuses"):
        store.update_settings(
            "tenant-1",
            {
                "classification_vocabulary": {
                    "job_functions": ["后端"],
                    "seniorities": ["高级"],
                    "statuses": ["待定", "已投递"],
                }
            },
        )
