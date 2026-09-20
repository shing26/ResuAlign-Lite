"""Build ResuAlign's internal import graph and detect coupling problems.

Read-only static analysis: parses each module with ``ast``, resolves relative
imports to absolute module paths, then reports:

  1. per-module fan-in / fan-out
  2. cycles
  3. layering violations (inner layers importing the API layer)

``--check`` turns the report into a ratchet: it compares the current violation
set and the ``api_module._`` reference set against ``layering-baseline.json``
and fails only when something *new* appears. Fixing a violation is always
allowed; run ``--update`` to tighten the baseline afterwards.

    python -m resualign.tools.modgraph            # human-readable report
    python -m resualign.tools.modgraph --check    # CI gate
    python -m resualign.tools.modgraph --update   # rewrite the baseline
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
PKG_NAME = "resualign"
BASELINE_PATH = Path(__file__).with_name("layering-baseline.json")

# Layer assignment by path prefix -- declared layering of the project.
LAYERS = [
    ("接入/入口", ("cli", "__main__")),
    ("API", ("api/",)),
    ("服务", ("api/services/",)),
    ("引擎", ("engine", "llm", "llm_nodes", "role_router", "tailor")),
    (
        "领域",
        (
            "match_scorer", "gap_analyzer", "jd_profiler", "jd_analysis",
            "evaluator", "classifier", "rules", "rule_diagnose",
            "local_fallback", "extractor", "parser", "resume_optimize",
            "batch", "config",
        ),
    ),
    (
        "存储",
        (
            "store_base", "job_library/", "workspace", "settings_store",
            "llm_usage", "cache", "secret_box", "alignment_lifecycle", "jobs",
        ),
    ),
    ("可观测", ("observability",)),
    ("模型", ("models", "schema_registry")),
    ("契约", ("contracts/",)),
]

# Layers that must not reach outward at all.
INNER = {"引擎", "领域", "存储", "模型", "可观测", "契约"}
OUTER = {"API", "服务", "接入/入口"}
# The service layer may use the inner layers (that is the point of the
# architecture) but must not reach back into the composition root. Before
# this rule existed, ``api/services/*`` importing ``resualign.api`` was
# invisible: the check only fired for the INNER source layers.
SERVICE = "服务"
SERVICE_FORBIDDEN = {"API", "接入/入口"}

_API_MODULE_REF = re.compile(r"\bapi_module\.(_[A-Za-z0-9_]+)")


def _path_matches(rel: str, prefix: str) -> bool:
    """Whether ``rel`` belongs to ``prefix``.

    A trailing slash means "this directory". A bare name means "this module
    or this package", never a longer sibling: ``engine_utils.py`` must not
    match the ``engine`` prefix.
    """
    if prefix.endswith("/"):
        return rel.startswith(prefix)
    return rel == f"{prefix}.py" or rel.startswith(f"{prefix}/")


def layer_of(rel: str) -> str:
    """Return the declared layer for a package-relative path.

    Longest prefix wins. The original first-match-wins version was silently
    broken: ``api/services/jobs.py`` matched the broader ``api/`` prefix, so
    the 服务 layer could never be returned.
    """
    rel = rel.replace("\\", "/")
    best_layer = "其他"
    best_len = -1
    for name, prefixes in LAYERS:
        for prefix in prefixes:
            if _path_matches(rel, prefix) and len(prefix) > best_len:
                best_layer = name
                best_len = len(prefix)
    return best_layer


def mod_name(path: Path) -> str:
    rel = path.relative_to(PKG).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join([PKG_NAME] + parts) if parts else PKG_NAME


def parse_imports(path: Path, this_mod: str) -> set[str]:
    """Return absolute intra-package module names imported by ``path``."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover
        print(f"  !! syntax error in {path}: {exc}")
        return set()

    pkg_parts = this_mod.split(".")
    is_pkg = path.name == "__init__.py"
    base = pkg_parts if is_pkg else pkg_parts[:-1]
    found: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith(PKG_NAME):
                    found.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and node.module.startswith(PKG_NAME):
                    found.add(node.module)
                continue
            # relative: climb (level-1) packages above the current package
            up = node.level - 1
            anchor = base[: len(base) - up] if up else base
            mod = ".".join(anchor + ([node.module] if node.module else []))
            found.add(mod)
            for a in node.names:  # `from . import X`
                if a.name != "*":
                    found.add(f"{mod}.{a.name}")
    return found


def build_edges(files: list[Path]) -> tuple[dict[str, set[str]], dict[str, Path]]:
    all_mods = {mod_name(p): p for p in files}
    edges: dict[str, set[str]] = {}
    for path in files:
        this = mod_name(path)
        raw = parse_imports(path, this)
        resolved = set()
        for r in raw:
            if r in all_mods:
                resolved.add(r)
                continue
            # a submodule import (from pkg import sub) -> pkg.sub
            for m in all_mods:
                if m.startswith(r + "."):
                    resolved.add(m)
                    break
        edges[this] = resolved
    return edges, all_mods


def layering_violations(
    edges: dict[str, set[str]], all_mods: dict[str, Path]
) -> list[tuple[str, str, str, str]]:
    """Return ``(source, source_layer, target, target_layer)`` violations."""
    violations: list[tuple[str, str, str, str]] = []
    for src, dsts in edges.items():
        srel = str(all_mods[src].relative_to(PKG)).replace("\\", "/")
        sl = layer_of(srel)
        if sl in INNER:
            forbidden = OUTER
        elif sl == SERVICE:
            forbidden = SERVICE_FORBIDDEN
        else:
            continue
        for dst in sorted(dsts):
            drel = str(all_mods[dst].relative_to(PKG)).replace("\\", "/")
            dl = layer_of(drel)
            if dl in forbidden:
                violations.append((src, sl, dst, dl))
    return violations


def api_module_refs(files: list[Path]) -> dict[str, int]:
    """Count private API-module reference sites as ``file::attr`` keys.

    Line numbers are deliberately excluded so the ratchet tracks coupling
    structure, not formatting churn.
    """
    counts: dict[str, int] = defaultdict(int)
    for path in files:
        rel = str(path.relative_to(PKG)).replace("\\", "/")
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            code = raw_line.split("#", 1)[0]
            for attr in _API_MODULE_REF.findall(code):
                counts[f"{rel}::{attr}"] += 1
    return dict(counts)


def violation_key(item: tuple[str, str, str, str]) -> str:
    src, sl, dst, dl = item
    return f"{src} [{sl}] -> {dst} [{dl}]"


def collect(files: list[Path]) -> dict:
    edges, all_mods = build_edges(files)
    violations = sorted(violation_key(v) for v in layering_violations(edges, all_mods))
    return {
        "edges": edges,
        "all_mods": all_mods,
        "violations": violations,
        "api_module_refs": api_module_refs(files),
        "cycles": sorted(cycle_key(c) for c in find_cycles(edges)),
    }


def cycle_key(cycle: list[str]) -> str:
    """A start-point-independent identity for a dependency cycle."""
    return " | ".join(sorted(cycle))


def find_cycles(edges: dict[str, set[str]]) -> list[list[str]]:
    """Return one representative path per distinct cycle."""
    cycles: list[list[str]] = []
    seen_sig: set[frozenset[str]] = set()

    def walk(node: str, stack: list[str], visited: set[str]) -> None:
        if node in stack:
            cyc = stack[stack.index(node):]
            sig = frozenset(cyc)
            if len(cyc) > 1 and sig not in seen_sig:
                seen_sig.add(sig)
                cycles.append(cyc)
            return
        if node in visited or len(stack) > 12:
            return
        stack.append(node)
        for nxt in sorted(edges.get(node, ())):
            walk(nxt, stack, visited)
        stack.pop()
        visited.add(node)

    for m in sorted(edges):
        walk(m, [], set())
    return cycles


def load_baseline(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "layering_violations": [], "api_module_refs": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_baseline(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _print_report(data: dict) -> None:
    edges: dict[str, set[str]] = data["edges"]
    all_mods: dict[str, Path] = data["all_mods"]
    fanin: dict[str, int] = defaultdict(int)
    for _src, dsts in edges.items():
        for d in dsts:
            fanin[d] += 1

    print("=" * 78)
    print("模块依赖图 — 扇出（该模块依赖了多少内部模块，越高越脆）")
    print("=" * 78)
    print(f"{'模块':<46}{'扇出':>6}{'扇入':>6}  层")
    rows = sorted(edges.items(), key=lambda kv: -len(kv[1]))
    for mod, dsts in rows:
        rel = str(all_mods[mod].relative_to(PKG)).replace("\\", "/")
        if len(dsts) == 0 and fanin[mod] == 0:
            continue
        print(f"{mod:<46}{len(dsts):>6}{fanin[mod]:>6}  {layer_of(rel)}")

    print()
    print("=" * 78)
    print("循环依赖检测")
    print("=" * 78)
    cycles = find_cycles(edges)

    if cycles:
        for c in cycles:
            print("  ✗ " + " → ".join(c + [c[0]]))
    else:
        print("  ✓ 无循环依赖")

    print()
    print("=" * 78)
    print("分层违规（内层/服务层反向依赖 API）")
    print("=" * 78)
    if data["violations"]:
        for key in data["violations"]:
            print(f"  ✗ {key}")
    else:
        print("  ✓ 无分层违规")

    print()
    print(f"api_module._ 引用站点: {sum(data['api_module_refs'].values())} 处 / "
          f"{len(data['api_module_refs'])} 个 (文件, 属性) 组合")
    print()
    print(
        f"模块总数: {len(all_mods)}  边数: "
        f"{sum(len(v) for v in edges.values())}"
    )


def check_against_baseline(data: dict, baseline: dict) -> int:
    """Return 0 when the tree is no worse than the baseline, else 1."""
    base_violations = set(baseline.get("layering_violations", []))
    actual_violations = set(data["violations"])
    new_violations = sorted(actual_violations - base_violations)
    fixed_violations = sorted(base_violations - actual_violations)

    base_cycles = set(baseline.get("cycles", []))
    actual_cycles = set(data["cycles"])
    new_cycles = sorted(actual_cycles - base_cycles)
    fixed_cycles = sorted(base_cycles - actual_cycles)

    base_refs = dict(baseline.get("api_module_refs", {}))
    actual_refs = data["api_module_refs"]
    new_refs = {
        key: count
        for key, count in sorted(actual_refs.items())
        if count > base_refs.get(key, 0)
    }
    tightened_refs = {
        key: base_refs[key]
        for key in sorted(base_refs)
        if actual_refs.get(key, 0) < base_refs[key]
    }

    if new_violations:
        print("✗ 新增分层违规（棘轮只允许减少）：")
        for key in new_violations:
            print(f"    + {key}")
    if new_cycles:
        print("✗ 新增循环依赖（棘轮只允许减少）：")
        for key in new_cycles:
            print(f"    + {key}")
    if new_refs:
        print("✗ api_module._ 引用站点增加（棘轮只允许减少）：")
        for key, count in new_refs.items():
            was = base_refs.get(key, 0)
            print(f"    + {key}: {was} -> {count}")
    if fixed_violations or fixed_cycles or tightened_refs:
        print("✓ 发现可收紧项，运行 `--update` 收紧 baseline：")
        for key in fixed_violations:
            print(f"    - {key}")
        for key in fixed_cycles:
            print(f"    - {key}")
        for key, count in tightened_refs.items():
            print(f"    - {key}: {count} -> {actual_refs.get(key, 0)}")
    if new_violations or new_cycles or new_refs:
        return 1
    print(
        f"✓ 分层棘轮通过（违规 {len(actual_violations)} 项，"
        f"循环 {len(actual_cycles)} 项，"
        f"api_module._ 站点 {sum(actual_refs.values())} 处）"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare against the baseline and fail on new coupling",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="rewrite the baseline with the current state",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE_PATH,
        help=f"baseline path (default: {BASELINE_PATH.name})",
    )
    args = parser.parse_args(argv)

    files = sorted(
        p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts
    )
    data = collect(files)

    if args.update:
        write_baseline(
            args.baseline,
            {
                "version": 1,
                "layering_violations": data["violations"],
                "cycles": data["cycles"],
                "api_module_refs": data["api_module_refs"],
            },
        )
        print(
            f"✓ baseline 已更新：违规 {len(data['violations'])} 项，"
            f"循环 {len(data['cycles'])} 项，"
            f"api_module._ 站点 {sum(data['api_module_refs'].values())} 处 "
            f"→ {args.baseline}"
        )
        return 0

    if args.check:
        return check_against_baseline(data, load_baseline(args.baseline))

    _print_report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
