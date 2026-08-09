"""Invariants for the api.py -> api/ package split."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Iterator


def _iter_route_paths(routes) -> Iterator[str]:
    """Yield every concrete route path, expanding nested router wrappers.

    FastAPI 0.116+ wraps ``include_router`` in ``_IncludedRouter`` objects
    (which expose ``.routes`` but no ``.path``), so a plain
    ``route.path for route in app.routes`` crashes on modern FastAPI.
    """
    for route in routes:
        if hasattr(route, "path"):
            yield route.path
        elif hasattr(route, "routes"):
            yield from _iter_route_paths(route.routes)


def test_resualign_api_is_a_package():
    module = importlib.import_module("resualign.api")
    assert hasattr(module, "app")
    assert Path(module.__file__).name == "__init__.py"


def test_app_import_target_works():
    from resualign.api import app

    assert app.title == "ResuAlign API"
    assert app.version == "0.3.0"
    assert any(path == "/health" for path in _iter_route_paths(app.routes))


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
        "_crawl_tasks",
        "_PERSONAL_MODE",
        "_payloads",
        "_import_batches",
    ):
        assert hasattr(api_module, name), name


def test_legacy_single_file_is_removed():
    legacy = Path("src/resualign/api_legacy.py")
    assert not legacy.exists()
