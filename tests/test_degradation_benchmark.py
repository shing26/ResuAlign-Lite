"""Contract test for the local breaker/fallback evidence benchmark."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "benchmarks" / "degradation_benchmark.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "degradation_benchmark", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_degradation_benchmark_writes_verdict(tmp_path):
    module = _module()
    payload = module.run_trials(1)
    assert payload["schema_version"] == 1
    assert payload["verdict"] == {"passed": True, "failures": []}
    trial = payload["trials"][0]
    assert trial["failure_events"] == [1, 2, 3]
    assert trial["fallback_took_over"] is True
    assert trial["disabled_node_skipped"] is True
    assert trial["recovered"] is True
    assert trial["recovery_ms"] >= 0

    out = tmp_path / "degradation.json"
    module._write_json(str(out), payload)
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"]["passed"] is True
