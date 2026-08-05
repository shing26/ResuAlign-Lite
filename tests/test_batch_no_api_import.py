"""A2: resualign.batch must not cascade-import resualign.api."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BATCH_SOURCE = REPO_ROOT / "src" / "resualign" / "batch.py"


def test_batch_source_has_no_api_import():
    source = BATCH_SOURCE.read_text(encoding="utf-8")
    assert "import resualign.api" not in source
    assert "api_module" not in source


def test_importing_batch_does_not_import_api_in_fresh_interpreter():
    code = (
        "import sys\n"
        "import resualign.batch\n"
        "assert 'resualign.api' not in sys.modules, "
        "'resualign.api was cascade-imported by resualign.batch'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=dict(
            os.environ,
            PYTHONPATH=str(REPO_ROOT / "src"),
        ),
    )
    assert result.returncode == 0, result.stderr
