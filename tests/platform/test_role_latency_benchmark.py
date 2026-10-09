"""Contract tests for the P4 role-latency calibration harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "benchmarks" / "role_latency_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "role_latency_benchmark", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_role_latency_benchmark_schema_and_percentiles():
    module = _module()
    with patch.object(
        module,
        "call_with_role",
        return_value=({"ok": True}, {}),
    ):
        payload = module.run_benchmark(
            object(), "calibration", ["diagnose"], samples=3
        )

    assert payload["schema_version"] == 1
    assert payload["roles"] == ["diagnose"]
    result = payload["results"][0]
    assert result["role"] == "diagnose"
    assert result["samples_requested"] == 3
    assert result["p50_ms"] >= 0
    assert result["p95_ms"] >= result["p50_ms"]
    assert result["p99_ms"] >= result["p95_ms"]
    assert payload["verdict"] == {"passed": True, "failures": []}


def test_role_latency_benchmark_reports_failures():
    module = _module()
    with patch.object(
        module,
        "call_with_role",
        side_effect=RuntimeError("upstream down"),
    ):
        payload = module.run_benchmark(
            object(), "calibration", ["profiler"], samples=2
        )

    assert payload["verdict"]["passed"] is False
    assert len(payload["verdict"]["failures"]) == 2
    assert "upstream down" in payload["verdict"]["failures"][0]


def test_role_latency_benchmark_redacts_api_key_from_command():
    module = _module()
    rendered = module._safe_command(
        [
            "role_latency_benchmark.py",
            "--api-key",
            "secret-value",
            "--samples",
            "5",
        ]
    )
    assert "secret-value" not in rendered
    assert "--api-key ***" in rendered

    rendered_equals = module._safe_command(
        ["role_latency_benchmark.py", "--api-key=secret-value"]
    )
    assert "secret-value" not in rendered_equals
    assert "--api-key=***" in rendered_equals
