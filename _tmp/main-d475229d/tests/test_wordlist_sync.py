"""Offline contract tests for classification vocabulary sync (A6/T6)."""

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign import job_library
from resualign.api import app
from resualign.settings_store import SettingsStore
from resualign.workspace import UserStore

client = TestClient(app)


@pytest.fixture(autouse=True)
def temp_settings_store(tmp_path):
    saved = {
        "users": api_module._users,
        "settings_store": api_module._settings_store,
        "personal_mode": api_module._PERSONAL_MODE,
    }
    db_path = tmp_path / "settings.db"
    api_module._users = UserStore(db_path=db_path)
    api_module._settings_store = SettingsStore(db_path=db_path)
    api_module._PERSONAL_MODE = True
    yield
    api_module._users = saved["users"]
    api_module._settings_store = saved["settings_store"]
    api_module._PERSONAL_MODE = saved["personal_mode"]


def test_settings_returns_default_vocabulary_structure():
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    vocabulary = body["classification_vocabulary"]
    assert set(vocabulary) == {"job_functions", "seniorities", "statuses"}
    assert vocabulary["job_functions"] == list(job_library.JOB_FUNCTIONS)
    assert vocabulary["seniorities"] == list(job_library.SENIORITIES)
    assert vocabulary["statuses"] == list(job_library.JOB_STATUSES)
    assert all(vocabulary[key] for key in vocabulary)


def test_settings_vocabulary_custom_words_are_persisted():
    custom = {
        "job_functions": ["架构", "后端"],
        "seniorities": ["资深", "高级"],
        "statuses": ["已投递", "已拿Offer"],
    }
    response = client.put(
        "/api/settings",
        json={"classification_vocabulary": custom},
    )
    assert response.status_code == 200
    saved = response.json()["classification_vocabulary"]
    # Tenant-editable lists round-trip exactly...
    assert saved["job_functions"] == ["架构", "后端"]
    assert saved["seniorities"] == ["资深", "高级"]
    # ...while statuses are a whitelist that gets backfilled to the built-in
    # five on read (B1), keeping the saved subset in front.
    assert saved["statuses"][:2] == ["已投递", "已拿Offer"]
    assert set(saved["statuses"]) == set(job_library.JOB_STATUSES)

    again = client.get("/api/settings").json()
    assert again["classification_vocabulary"]["job_functions"] == ["架构", "后端"]
    assert again["classification_vocabulary"]["seniorities"] == ["资深", "高级"]
    assert set(again["classification_vocabulary"]["statuses"]) == set(
        job_library.JOB_STATUSES
    )
