"""Convenience runner for the ResuAlign browser E2E suite.

Boots nothing by itself: the conftest starts the fake LLM + app servers and
tears them down after the session. This script only invokes pytest with the
``--e2e`` flag so Stage 1's plain ``pytest tests/`` stays browser-free.

Usage:
    python tests/e2e/run_e2e.py [extra pytest args...]
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
E2E_DIR = Path(__file__).resolve().parent


def main() -> int:
    env = os.environ.copy()
    old_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SRC) + os.pathsep + old_pythonpath
        if old_pythonpath
        else str(SRC)
    )
    cmd = [
        sys.executable, "-m", "pytest",
        str(E2E_DIR),
        "-v",
        "--e2e",
        "--tb=short",
        *sys.argv[1:],
    ]
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())
