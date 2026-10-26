"""ADR-0065: ranking storage and services must never reach the gate."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "resualign"
MODULES = (
    SRC / "vector_index.py",
    SRC / "engine" / "embeddings.py",
    SRC / "api" / "services" / "resume_ranking.py",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_ranking_modules_do_not_import_gate():
    for path in MODULES:
        assert path.exists(), path
        imported = _imports(path)
        offenders = [
            name for name in imported
            if name == "gate" or name.endswith(".gate")
        ]
        assert not offenders, (path.name, offenders)


def test_ranking_modules_stay_off_llm_chat():
    """Ranking path is deterministic: no role router / chat client imports."""
    forbidden = ("engine.llm", "engine.role_router", "engine.llm_nodes")
    for path in MODULES:
        imported = _imports(path)
        assert not any(
            any(name.endswith(suffix) for suffix in forbidden) for name in imported
        ), path.name
