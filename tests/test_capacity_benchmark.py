"""Contract tests for the capacity benchmark's pure helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "benchmarks" / "capacity_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("capacity_benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_build_plan_is_deterministic_mix():
    module = _module()
    plan = module._build_plan(200, 1337)
    assert len(plan) == 200
    endpoints = [request["endpoint"] for request in plan]
    assert endpoints.count("quick-eval") == 100
    assert endpoints.count("jobs") == 50
    assert endpoints.count("health") == 50
    # Same seed -> same order; different seed -> (almost surely) different.
    assert [r["path"] for r in module._build_plan(200, 1337)] == [
        r["path"] for r in plan
    ]
    assert [r["path"] for r in module._build_plan(200, 7)] != [
        r["path"] for r in plan
    ]
    quick = next(r for r in plan if r["endpoint"] == "quick-eval")
    assert quick["method"] == "POST"
    assert len(quick["json"]["jd_text"]) >= 30


def test_percentile_interpolates_and_handles_edges():
    module = _module()
    assert module._percentile([], 0.5) == 0.0
    assert module._percentile([5.0], 0.99) == 5.0
    values = [float(i) for i in range(1, 101)]
    assert module._percentile(values, 0.50) == 50.5
    assert module._percentile(values, 0.95) == 95.05
    assert module._percentile(values, 0.99) == 99.01


def test_knee_is_first_level_below_threshold():
    module = _module()
    levels = [
        {"concurrency": 1, "qps": 100.0},
        {"concurrency": 2, "qps": 150.0},  # +50%
        {"concurrency": 4, "qps": 160.0},  # +6.7% -> knee
        {"concurrency": 8, "qps": 300.0},
    ]
    assert module._knee(levels, 0.20) == 4
    growing = [
        {"concurrency": 1, "qps": 100.0},
        {"concurrency": 2, "qps": 200.0},
    ]
    assert module._knee(growing, 0.20) is None


def _level(concurrency, qps, p99, errors=0):
    return {
        "concurrency": concurrency,
        "qps": qps,
        "p50_ms": 1.0,
        "p95_ms": 2.0,
        "p99_ms": p99,
        "errors": errors,
    }


def test_check_baseline_passes_within_bounds():
    module = _module()
    payload = {"levels": [_level(1, 100.0, 50.0)]}
    baseline = {"levels": {"1": {"qps": 120.0, "p99_ms": 40.0}}}
    assert module.check_baseline(payload, baseline) == []


def test_check_baseline_flags_regressions():
    module = _module()
    baseline = {"levels": {"1": {"qps": 200.0, "p99_ms": 40.0}}}
    # QPS under 50% floor and P99 above the +100ms ceiling.
    payload = {"levels": [_level(1, 50.0, 300.0)]}
    failures = module.check_baseline(payload, baseline)
    assert any("QPS" in failure for failure in failures)
    assert any("P99" in failure for failure in failures)

    # HTTP errors and missing baseline entry also fail.
    payload_err = {"levels": [_level(2, 100.0, 10.0, errors=1)]}
    failures_err = module.check_baseline(payload_err, baseline)
    assert any("errors" in failure for failure in failures_err)
    assert any("missing" in failure for failure in failures_err)
