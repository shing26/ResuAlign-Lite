"""Contract tests for the cold-start benchmark's pure helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "benchmarks" / "cold_start_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location("cold_start_benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _payload(startup_ms, uid="1000"):
    return {
        "docker": {"container": {"startup_ms": startup_ms, "uid": uid}},
        "native": {"p50_ms": 1.0, "p95_ms": 2.0},
    }


def test_percentile_interpolates_and_handles_edges():
    module = _module()
    assert module._percentile([], 0.5) == 0.0
    assert module._percentile([10.0], 0.95) == 10.0
    values = [float(i) for i in range(1, 101)]
    assert module._percentile(values, 0.50) == 50.5
    assert module._percentile(values, 0.95) == 95.05


def test_baseline_snapshot_shape():
    module = _module()
    payload = {
        "schema_version": 1,
        "generated_at": "2026-09-21T00:00:00+00:00",
        "git_sha": "abc",
        "platform": "Linux",
        "python": "3.11.9",
        "command": "cold-start",
        "native": {"p50_ms": 800.0, "p95_ms": 900.0},
        "docker": {"container": {"startup_ms": 1200.0, "uid": "1000"}},
    }
    snapshot = module._baseline_snapshot(payload)
    assert snapshot["native_p50_ms"] == 800.0
    assert snapshot["native_p95_ms"] == 900.0
    assert snapshot["container_startup_ms"] == 1200.0


def test_check_baseline_passes_within_ceiling():
    module = _module()
    baseline = {"container_startup_ms": 1500.0}
    assert module.check_baseline(_payload(1400.0), baseline) == []
    # 2x ceiling still holds.
    assert module.check_baseline(_payload(2900.0), baseline) == []


def test_check_baseline_flags_slow_and_root():
    module = _module()
    baseline = {"container_startup_ms": 1500.0}
    # Above max(2x=3000, +5000=6500) -> fails.
    failures = module.check_baseline(_payload(7000.0), baseline)
    assert any("ceiling" in failure for failure in failures)
    # UID 0 is rejected.
    root_failures = module.check_baseline(_payload(1400.0, uid="0"), baseline)
    assert any("UID" in failure for failure in root_failures)
    # Missing measurement fails.
    missing = module.check_baseline(_payload(None), baseline)
    assert any("not measured" in failure for failure in missing)
