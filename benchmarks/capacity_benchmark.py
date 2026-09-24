#!/usr/bin/env python3
"""Deterministic API capacity curve against an isolated uvicorn process.

The load generator never touches a real model, credential, or external
network. It boots ``resualign.api`` in a subprocess pointed at a throwaway
``RESUALIGN_DATA_DIR`` and replays a fixed request mix:

- 50% ``POST /api/quick-eval`` (deterministic rule-based scorer)
- 25% ``GET  /api/jobs``       (library list)
- 25% ``GET  /health``         (liveness/readiness probe)

For each concurrency level the mix is repeated ``--repeats`` times; the
reported QPS and latency percentiles are the median across repeats. The
capacity knee is the first level whose QPS growth over the previous level is
below ``--knee-threshold`` (default 20%).

``--check-baseline`` compares the run against the committed CI snapshot
(``benchmarks/baselines/capacity-ci.json``) and fails nonzero when any gate
breaks. ``--update-baseline`` rewrites that snapshot and is the only way to
move the thresholds.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import httpx  # noqa: E402

DEFAULT_BASELINE = REPO_ROOT / "benchmarks" / "baselines" / "capacity-ci.json"
DEFAULT_CONCURRENCY = "1,2,4,8,16,32"
_SEED = 1337

# A fixed, PII-free JD that clears the 30-char minimum and exercises the
# deterministic skill extraction path.
_QUICK_EVAL_JD = (
    "Hiring a Python backend engineer with FastAPI, Redis and PostgreSQL "
    "experience for a high-concurrency platform. Requirements: async "
    "endpoints, caching, Docker and Kubernetes deployment workflows."
)


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
    except Exception:  # noqa: BLE001 - artifact remains useful without git
        return ""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_plan(requests: int, seed: int) -> list[dict[str, Any]]:
    """Fixed 50/25/25 mix, deterministically shuffled per (level, repeat)."""
    quick_eval = requests // 2
    jobs = requests // 4
    health = requests - quick_eval - jobs
    plan: list[dict[str, Any]] = []
    plan += [
        {
            "method": "POST",
            "path": "/api/quick-eval",
            "json": {"jd_text": _QUICK_EVAL_JD},
            "endpoint": "quick-eval",
        }
    ] * quick_eval
    plan += [
        {"method": "GET", "path": "/api/jobs", "endpoint": "jobs"}
    ] * jobs
    plan += [
        {"method": "GET", "path": "/health", "endpoint": "health"}
    ] * health
    random.Random(seed).shuffle(plan)
    return plan


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


def _summarize(samples: list[tuple[str, float, int]]) -> dict[str, Any]:
    """Turn (endpoint, latency_ms, status) samples into QPS + percentiles."""
    latencies = sorted(sample[1] for sample in samples)
    return {
        "count": len(samples),
        "p50_ms": round(_percentile(latencies, 0.50), 3),
        "p95_ms": round(_percentile(latencies, 0.95), 3),
        "p99_ms": round(_percentile(latencies, 0.99), 3),
    }


def _run_repeat(
    base_url: str,
    concurrency: int,
    plan: list[dict[str, Any]],
    client: httpx.Client,
) -> dict[str, Any]:
    samples: list[tuple[str, float, int]] = []
    lock_errors: list[str] = []

    def issue(request: dict[str, Any]) -> None:
        start = time.monotonic()
        try:
            response = client.request(
                request["method"],
                base_url + request["path"],
                json=request.get("json"),
            )
            status = response.status_code
        except Exception as exc:  # noqa: BLE001 - record transport failures
            status = 0
            lock_errors.append(f"{request['path']}: {exc.__class__.__name__}: {exc}")
        latency_ms = (time.monotonic() - start) * 1000
        samples.append((request["endpoint"], latency_ms, status))

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(issue, plan))
    elapsed = time.monotonic() - start

    errors = sum(1 for sample in samples if sample[2] != 200)
    overall = _summarize(samples)
    overall["qps"] = round(len(samples) / elapsed, 3) if elapsed else 0.0
    overall["errors"] = errors

    per_endpoint: dict[str, Any] = {}
    for endpoint in ("quick-eval", "jobs", "health"):
        subset = [sample for sample in samples if sample[0] == endpoint]
        summary = _summarize(subset)
        summary["errors"] = sum(1 for sample in subset if sample[2] != 200)
        per_endpoint[endpoint] = summary

    return {
        "elapsed_s": round(elapsed, 4),
        "qps": overall["qps"],
        "p50_ms": overall["p50_ms"],
        "p95_ms": overall["p95_ms"],
        "p99_ms": overall["p99_ms"],
        "errors": errors,
        "per_endpoint": per_endpoint,
        "transport_errors": lock_errors,
    }


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _median_int(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _measure_level(
    base_url: str,
    concurrency: int,
    requests: int,
    repeats: int,
    seed: int,
) -> dict[str, Any]:
    limits = httpx.Limits(
        max_connections=max(concurrency * 2, 32),
        max_keepalive_connections=max(concurrency, 16),
    )
    timeout = httpx.Timeout(30.0)
    with httpx.Client(limits=limits, timeout=timeout) as client:
        runs = [
            _run_repeat(
                base_url,
                concurrency,
                _build_plan(requests, seed + concurrency * 100 + repeat),
                client,
            )
            for repeat in range(repeats)
        ]

    level = {
        "concurrency": concurrency,
        "repeats": repeats,
        "requests_per_repeat": requests,
        "qps": round(_median([run["qps"] for run in runs]), 3),
        "p50_ms": round(_median([run["p50_ms"] for run in runs]), 3),
        "p95_ms": round(_median([run["p95_ms"] for run in runs]), 3),
        "p99_ms": round(_median([run["p99_ms"] for run in runs]), 3),
        "errors": _median_int([run["errors"] for run in runs]),
        "max_errors": max(run["errors"] for run in runs),
        "per_endpoint": {
            endpoint: {
                "p50_ms": round(
                    _median([run["per_endpoint"][endpoint]["p50_ms"] for run in runs]),
                    3,
                ),
                "p95_ms": round(
                    _median([run["per_endpoint"][endpoint]["p95_ms"] for run in runs]),
                    3,
                ),
                "p99_ms": round(
                    _median([run["per_endpoint"][endpoint]["p99_ms"] for run in runs]),
                    3,
                ),
                "errors": _median_int(
                    [run["per_endpoint"][endpoint]["errors"] for run in runs]
                ),
            }
            for endpoint in ("quick-eval", "jobs", "health")
        },
        "transport_errors": [
            error for run in runs for error in run["transport_errors"]
        ],
    }
    return level


def _knee(levels: list[dict[str, Any]], threshold: float) -> int | None:
    """First concurrency whose QPS growth over the prior level < threshold."""
    for previous, current in zip(levels, levels[1:]):
        if previous["qps"] <= 0:
            continue
        growth = (current["qps"] - previous["qps"]) / previous["qps"]
        if growth < threshold:
            return int(current["concurrency"])
    return None


def _start_server(data_dir: Path, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env["RESUALIGN_PERSONAL_MODE"] = "1"
    env["RESUALIGN_DATA_DIR"] = str(data_dir)
    env["RESUALIGN_LOG_DIR"] = str(data_dir / "logs")
    env["RESUALIGN_JOB_MAX_RUNTIME_S"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "resualign.api",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_ready(port: int, timeout: float = 60.0) -> float:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return timeout - (deadline - time.monotonic())
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.25)
    raise TimeoutError(f"server did not become ready on port {port} within {timeout}s")


def run_benchmark(
    concurrency_levels: list[int],
    requests: int,
    repeats: int,
    seed: int,
    knee_threshold: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix="resualign-capacity-", ignore_cleanup_errors=True
    ) as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        port = _free_port()
        server = _start_server(data_dir, port)
        try:
            _wait_ready(port)
            base_url = f"http://127.0.0.1:{port}"
            levels = [
                _measure_level(base_url, level, requests, repeats, seed)
                for level in concurrency_levels
            ]
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=15)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "command": " ".join(sys.argv),
        "seed": seed,
        "requests_per_repeat": requests,
        "repeats": repeats,
        "knee_threshold": knee_threshold,
        "levels": levels,
        "knee_concurrency": _knee(levels, knee_threshold),
    }


def _baseline_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload["schema_version"],
        "generated_at": payload["generated_at"],
        "git_sha": payload["git_sha"],
        "platform": payload["platform"],
        "python": payload["python"],
        "command": payload["command"],
        "seed": payload["seed"],
        "requests_per_repeat": payload["requests_per_repeat"],
        "repeats": payload["repeats"],
        "knee_threshold": payload["knee_threshold"],
        "knee_concurrency": payload["knee_concurrency"],
        "levels": {
            str(level["concurrency"]): {
                "qps": level["qps"],
                "p50_ms": level["p50_ms"],
                "p95_ms": level["p95_ms"],
                "p99_ms": level["p99_ms"],
                "errors": level["errors"],
            }
            for level in payload["levels"]
        },
    }


def check_baseline(
    payload: dict[str, Any], baseline: dict[str, Any]
) -> list[str]:
    """Return gate failures; empty means the run is within the baseline."""
    failures: list[str] = []
    baseline_levels = baseline.get("levels", {})
    for level in payload["levels"]:
        concurrency = str(level["concurrency"])
        if level["errors"] != 0:
            failures.append(
                f"concurrency {concurrency}: {level['errors']} HTTP errors"
            )
        if not (level["p50_ms"] <= level["p95_ms"] <= level["p99_ms"]):
            failures.append(
                f"concurrency {concurrency}: percentiles not monotonic "
                f"(p50={level['p50_ms']} p95={level['p95_ms']} "
                f"p99={level['p99_ms']})"
            )
        base = baseline_levels.get(concurrency)
        if not base:
            failures.append(
                f"concurrency {concurrency}: missing from baseline snapshot"
            )
            continue
        qps_floor = 0.5 * base["qps"]
        if level["qps"] < qps_floor:
            failures.append(
                f"concurrency {concurrency}: QPS {level['qps']} below 50% "
                f"baseline floor {round(qps_floor, 3)}"
            )
        p99_ceiling = max(2 * base["p99_ms"], base["p99_ms"] + 100.0)
        if level["p99_ms"] > p99_ceiling:
            failures.append(
                f"concurrency {concurrency}: P99 {level['p99_ms']}ms above "
                f"ceiling {round(p99_ceiling, 3)}ms"
            )
    return failures


def _parse_levels(raw: str) -> list[int]:
    levels = [int(part) for part in raw.split(",") if part.strip()]
    if not levels or any(level < 1 for level in levels):
        raise ValueError("--concurrency must be a comma-separated list of positives")
    return levels


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _is_ci() -> bool:
    """Formal gate runs only on CI; local runs are non-gating cross-checks."""
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get(
        "RESUALIGN_BENCHMARK_STRICT"
    ) == "1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--concurrency", default=DEFAULT_CONCURRENCY)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=_SEED)
    parser.add_argument("--knee-threshold", type=float, default=0.20)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    levels = _parse_levels(args.concurrency)
    if args.requests < 1 or args.repeats < 1:
        parser.error("--requests and --repeats must be positive")

    payload = run_benchmark(
        levels, args.requests, args.repeats, args.seed, args.knee_threshold
    )
    if args.json_out:
        _write_json(Path(args.json_out), payload)

    for level in payload["levels"]:
        print(
            f"c={level['concurrency']:<3} qps={level['qps']:>9.1f} "
            f"p50={level['p50_ms']:>7.2f}ms p95={level['p95_ms']:>7.2f}ms "
            f"p99={level['p99_ms']:>7.2f}ms errors={level['errors']}"
        )
    knee = payload["knee_concurrency"]
    print(f"capacity knee: {knee if knee is not None else 'not reached'}")

    if args.update_baseline:
        snapshot = _baseline_snapshot(payload)
        _write_json(args.baseline, snapshot)
        print(f"baseline updated: {args.baseline}")
        return 0

    if args.check_baseline:
        if not args.baseline.exists():
            print(f"FAIL: baseline missing at {args.baseline}", file=sys.stderr)
            return 1
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        failures = check_baseline(payload, baseline)
        gating = _is_ci()
        for failure in failures:
            label = "FAIL" if gating else "ADVISORY"
            print(f"{label}: {failure}", file=sys.stderr)
        if not gating:
            print(
                "baseline check is advisory here (non-CI cross-validation); "
                "set GITHUB_ACTIONS=true or RESUALIGN_BENCHMARK_STRICT=1 to gate"
            )
            return 0
        if failures:
            return 1
        print("baseline check passed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
