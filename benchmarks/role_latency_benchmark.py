#!/usr/bin/env python3
"""Role-level latency calibration for ResuAlign.

The script reads a configured LLM node, copies it into a throwaway store,
and measures each role through the real ``role_router`` path. The throwaway
store is deliberate: calibration failures must never mutate the user's
breaker state.

The output follows the benchmark JSON shape used by ADR-0054. This script
needs a real model, so it is evidence tooling, not a CI gate.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resualign.engine.llm import diagnose_resume
from resualign.engine.llm_nodes import LLMNodeStore
from resualign.engine.role_router import call_with_role, role_timeouts
from resualign.engine.tailor import tailor_resume
from resualign.evaluator import evaluate
from resualign.gap_analyzer import analyze_gaps
from resualign.jd_profiler import profile_jd
from resualign.jobs import resolve_data_dir

ROLES = ("diagnose", "profiler", "gap_analyzer", "editor", "evaluator")

RESUME_TEXT = """# Backend Engineer
5 years building Python services with FastAPI, PostgreSQL, Redis, and Docker.
- Reduced checkout API p95 latency by 35%.
- Deployed services on Kubernetes with metrics and tracing.
- Led migration from a monolith to event-driven services.
"""

JD_TEXT = """Backend Engineer (High Concurrency Platform)
We need Python, FastAPI, PostgreSQL, Redis, Docker, and Kubernetes experience.
The role owns high-concurrency services, low-latency APIs, observability, and
production reliability. 5+ years of backend experience preferred.
"""

JD_PROFILE_TEXT = json.dumps(
    {
        "must_have_skills": [
            "Python",
            "FastAPI",
            "PostgreSQL",
            "Redis",
            "Docker",
            "Kubernetes",
        ],
        "nice_to_have_skills": ["observability"],
        "soft_skills": ["ownership"],
        "business_scenarios": ["high concurrency", "low latency"],
        "min_years_experience": 5,
        "education_requirements": [],
    },
    ensure_ascii=False,
)

GAP_REPORT_TEXT = json.dumps(
    {
        "missing_keywords": [
            "Redis caching for high concurrency",
            "Kubernetes production deployment",
        ],
        "misaligned_emphasis": [],
        "strength_matches": ["Python", "FastAPI", "PostgreSQL"],
    },
    ensure_ascii=False,
)

TAILORED_TEXT = """# Backend Engineer
5 years building Python FastAPI services with PostgreSQL and Redis caching.
- Reduced checkout API p95 latency by 35% on a high-concurrency platform.
- Deployed production services on Kubernetes with metrics and tracing.
"""


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except Exception:  # noqa: BLE001
        return ""


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = quantile * (len(sorted_values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _run_role(role: str, client: Any, tenant: str) -> Any:
    if role == "diagnose":
        return diagnose_resume(client, RESUME_TEXT, tenant=tenant)
    if role == "profiler":
        return profile_jd(client, JD_TEXT, tenant=tenant)
    if role == "gap_analyzer":
        return analyze_gaps(
            client, RESUME_TEXT, JD_PROFILE_TEXT, tenant=tenant
        )
    if role == "editor":
        return tailor_resume(
            client,
            RESUME_TEXT,
            GAP_REPORT_TEXT,
            granularity="medium",
            prompt_focus="balanced",
        )
    if role == "evaluator":
        return evaluate(client, RESUME_TEXT, TAILORED_TEXT, JD_TEXT)
    raise ValueError(f"unsupported role: {role}")


def _measure_role(
    store: LLMNodeStore,
    tenant: str,
    role: str,
    samples: int,
) -> dict[str, Any]:
    timeout_ms = role_timeouts()[role] * 1000
    latencies: list[float] = []
    failures: list[str] = []

    for index in range(1, samples + 1):
        started = time.monotonic()
        try:
            _, meta = call_with_role(
                role,
                lambda client, **kwargs: _run_role(role, client, tenant),
                store,
                tenant,
            )
            elapsed_ms = (time.monotonic() - started) * 1000
            if meta.get("fallback_used"):
                failures.append(
                    f"sample {index}: fallback used: {meta.get('error')}"
                )
            else:
                latencies.append(elapsed_ms)
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.monotonic() - started) * 1000
            failures.append(
                f"sample {index}: {exc.__class__.__name__}: {str(exc)[:240]}"
            )
            latencies.append(elapsed_ms)

    ordered = sorted(latencies)
    p50 = _percentile(ordered, 0.50)
    p95 = _percentile(ordered, 0.95)
    p99 = _percentile(ordered, 0.99)
    return {
        "role": role,
        "samples_requested": samples,
        "samples_measured": len(latencies),
        "timeout_ms": round(timeout_ms, 3),
        "p50_ms": round(p50, 3),
        "p95_ms": round(p95, 3),
        "p99_ms": round(p99, 3),
        "min_ms": round(min(latencies), 3) if latencies else None,
        "max_ms": round(max(latencies), 3) if latencies else None,
        "mean_ms": round(statistics.fmean(latencies), 3) if latencies else None,
        "headroom_ms": round(timeout_ms - p95, 3),
        "failures": failures,
        "verdict": "passed" if not failures and p95 <= timeout_ms else "failed",
    }


def _select_node(
    store: LLMNodeStore,
    tenant: str,
    node_id: str | None,
) -> dict[str, Any] | None:
    nodes = store.list_nodes(tenant)
    if node_id:
        return next((node for node in nodes if node["node_id"] == node_id), None)
    usable = [
        node
        for node in nodes
        if node.get("is_active") and not node.get("auto_disabled")
    ]
    if usable:
        return usable[0]
    active = [node for node in nodes if node.get("is_active")]
    if active:
        return active[0]
    return nodes[0] if nodes else None


def _copy_node_to_temp_store(node: dict[str, Any]) -> LLMNodeStore:
    temp_dir = tempfile.TemporaryDirectory(
        prefix="resualign-role-latency-", ignore_cleanup_errors=True
    )
    store = LLMNodeStore(db_path=Path(temp_dir.name) / "nodes.db")
    store.create_node(
        "calibration",
        name=node.get("name") or "calibration",
        provider=node.get("provider") or "custom",
        model=node.get("model") or "",
        base_url=node.get("base_url"),
        api_key=node.get("api_key"),
        is_active=True,
        disable_thinking=bool(node.get("disable_thinking", False)),
    )
    # Keep the temporary directory alive for the store's lifetime.
    store._calibration_temp_dir = temp_dir  # type: ignore[attr-defined]
    return store


def run_benchmark(
    store: LLMNodeStore,
    tenant: str,
    roles: list[str],
    samples: int,
) -> dict[str, Any]:
    results = [_measure_role(store, tenant, role, samples) for role in roles]
    failures: list[str] = []
    for result in results:
        failures.extend(
            f"{result['role']}: {failure}" for failure in result["failures"]
        )
        if result["p95_ms"] > result["timeout_ms"]:
            failures.append(
                f"{result['role']}: p95 {result['p95_ms']}ms exceeds "
                f"timeout {result['timeout_ms']}ms"
            )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "command": " ".join(sys.argv),
        "tenant": tenant,
        "samples_requested": samples,
        "roles": roles,
        "results": results,
        "verdict": {"passed": not failures, "failures": failures},
    }


def _build_temp_store_from_args(args: argparse.Namespace) -> LLMNodeStore:
    explicit = any(
        value
        for value in (
            args.provider,
            args.model,
            args.base_url,
            args.api_key,
        )
    )
    if explicit:
        if not args.model:
            raise SystemExit("--model is required with explicit node overrides")
        node = {
            "name": "explicit",
            "provider": args.provider or "custom",
            "model": args.model,
            "base_url": args.base_url,
            "api_key": args.api_key,
            "disable_thinking": False,
        }
        return _copy_node_to_temp_store(node)

    source = LLMNodeStore(db_path=Path(args.db))
    node = _select_node(source, args.tenant, args.node_id)
    if node is None:
        raise SystemExit(
            f"no LLM node found in {args.db} for tenant {args.tenant!r}"
        )
    return _copy_node_to_temp_store(node)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument(
        "--role",
        action="append",
        choices=ROLES,
        dest="roles",
        help="role to measure; repeat for multiple roles (default: all)",
    )
    parser.add_argument(
        "--db",
        default=str(resolve_data_dir() / "jobs.db"),
        help="LLM node SQLite database",
    )
    parser.add_argument("--tenant", default="local")
    parser.add_argument("--node-id", default=None)
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")
    roles = args.roles or list(ROLES)
    store = _build_temp_store_from_args(args)
    try:
        payload = run_benchmark(store, "calibration", roles, args.samples)
    finally:
        store.close_all_connections()

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if payload["verdict"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
