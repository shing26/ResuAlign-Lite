"""Invariants for the api.py -> api/ package split."""

from __future__ import annotations

import importlib
from pathlib import Path


def test_resualign_api_is_a_package():
    module = importlib.import_module("resualign.api")
    assert hasattr(module, "app")
    assert Path(module.__file__).name == "__init__.py"


def test_app_import_target_works():
    from fastapi.testclient import TestClient

    from resualign.api import app

    assert app.title == "ResuAlign API"
    assert app.version == "0.3.0"
    # Hit the route directly instead of scanning app.routes: modern FastAPI
    # wraps included routers in _IncludedRouter objects whose exact nesting
    # varies across versions, so a structural scan is version-fragile.
    assert TestClient(app).get("/health").status_code == 200


def test_patchable_state_names_remain_on_package():
    import resualign.api as api_module

    for name in (
        "_registry",
        "_users",
        "_resumes",
        "_applications",
        "_jobs",
        "_settings_store",
        "_session_store",
        "_PERSONAL_MODE",
        "_payloads",
        "_import_batches",
    ):
        assert hasattr(api_module, name), name


def test_legacy_single_file_is_removed():
    legacy = Path("src/resualign/api_legacy.py")
    assert not legacy.exists()
