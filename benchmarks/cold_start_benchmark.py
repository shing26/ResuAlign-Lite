#!/usr/bin/env python3
"""Layered cold-start measurement for ResuAlign.

Three layers are recorded separately, never averaged together:

1. **Native** — a fresh ``python -m resualign.api`` process with a throwaway
   ``RESUALIGN_DATA_DIR``; the reported number is p50/p95 over ``--trials``.
2. **Image build** — ``docker build --no-cache`` wall time. Recorded only;
   build time is not a gate.
3. **Container** — a container started with an *empty* named data volume,
   timed from ``docker run`` to the first ``GET /health`` 200. The container
   UID is asserted to be 1000 (non-root).

``--check-baseline`` gates the container startup latency against the committed
snapshot (``benchmarks/baselines/cold-start-ci.json``); the gate is active only
on CI (or when ``RESUALIGN_BENCHMARK_STRICT=1``). ``--update-baseline`` is the
only way to move the thresholds.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

DEFAULT_BASELINE = REPO_ROOT / "benchmarks" / "baselines" / "cold-start-ci.json"
DEFAULT_IMAGE_TAG = "resualign:cold-start-evidence"
_READY_TIMEOUT_S = 90.0
_STARTUP_CEILING_MS = 5000.0


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


def _is_ci() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get(
        "RESUALIGN_BENCHMARK_STRICT"
    ) == "1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_health(port: int, timeout: float) -> float | None:
    """Return the monotonic timestamp when ``/health`` first answers 200."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return time.monotonic()
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.1)
    return None


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


def _native_cold_start() -> float:
    with tempfile.TemporaryDirectory(
        prefix="resualign-native-cold-", ignore_cleanup_errors=True
    ) as tmp:
        data_dir = Path(tmp) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC_DIR)
        env["RESUALIGN_PERSONAL_MODE"] = "1"
        env["RESUALIGN_DATA_DIR"] = str(data_dir)
        env["RESUALIGN_LOG_DIR"] = str(data_dir / "logs")
        env["RESUALIGN_JOB_MAX_RUNTIME_S"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        port = _free_port()
        start = time.monotonic()
        process = subprocess.Popen(
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
        try:
            ready_at = _wait_health(port, _READY_TIMEOUT_S)
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        if ready_at is None:
            raise TimeoutError("native server never answered /health")
        return (ready_at - start) * 1000


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=True,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _docker_build(image_tag: str) -> dict[str, Any]:
    start = time.monotonic()
    result = subprocess.run(
        ["docker", "build", "--no-cache", "-t", image_tag, "."],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    elapsed_ms = (time.monotonic() - start) * 1000
    tail = "\n".join((result.stdout or "").splitlines()[-15:])
    return {
        "ok": result.returncode == 0,
        "build_ms": round(elapsed_ms, 3),
        "returncode": result.returncode,
        "log_tail": tail,
    }


def _docker_container_start(image_tag: str) -> dict[str, Any]:
    name = f"resualign-cold-{uuid.uuid4().hex[:10]}"
    volume = f"resualign-cold-data-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(
        ["docker", "volume", "create", volume],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )
    try:
        start = time.monotonic()
        run = subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:8000",
                "-v",
                f"{volume}:/app/data",
                image_tag,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if run.returncode != 0:
            return {
                "ok": False,
                "startup_ms": None,
                "uid": None,
                "error": run.stdout.strip(),
            }
        ready_at = _wait_health(port, _READY_TIMEOUT_S)
        startup_ms = None if ready_at is None else (ready_at - start) * 1000
        uid = subprocess.run(
            ["docker", "exec", name, "id", "-u"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        uid_value = uid.stdout.strip()
        logs = ""
        if startup_ms is None:
            captured = subprocess.run(
                ["docker", "logs", name],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            logs = "\n".join((captured.stdout or "").splitlines()[-25:])
        return {
            "ok": startup_ms is not None and uid_value == "1000",
            "startup_ms": None if startup_ms is None else round(startup_ms, 3),
            "uid": uid_value,
            "non_root": uid_value == "1000",
            "logs_tail": logs,
        }
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["docker", "volume", "rm", volume],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def run_benchmark(trials: int, image_tag: str, skip_docker: bool) -> dict[str, Any]:
    native_samples: list[float] = []
    failures: list[str] = []
    for index in range(1, trials + 1):
        try:
            native_samples.append(_native_cold_start())
        except Exception as exc:  # noqa: BLE001
            failures.append(f"native trial {index}: {exc.__class__.__name__}: {exc}")

    ordered = sorted(native_samples)
    native = {
        "trials_requested": trials,
        "trials_ok": len(native_samples),
        "samples_ms": [round(value, 3) for value in native_samples],
        "p50_ms": round(_percentile(ordered, 0.50), 3),
        "p95_ms": round(_percentile(ordered, 0.95), 3),
        "success": len(native_samples) == trials,
    }

    docker_result: dict[str, Any] = {"skipped": True, "reason": "not requested"}
    if not skip_docker:
        if not _docker_available():
            docker_result = {"skipped": True, "reason": "docker unavailable"}
        else:
            build = _docker_build(image_tag)
            container = (
                _docker_container_start(image_tag)
                if build["ok"]
                else {"ok": False, "startup_ms": None, "uid": None}
            )
            docker_result = {
                "skipped": False,
                "build": build,
                "container": container,
                "success": bool(build["ok"] and container.get("ok")),
            }

    verdict_passed = native["success"] and failures == []
    if not docker_result.get("skipped", False):
        verdict_passed = verdict_passed and docker_result.get("success", False)

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "command": " ".join(sys.argv),
        "native": native,
        "docker": docker_result,
        "verdict": {"passed": verdict_passed, "failures": failures},
    }


def _baseline_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    container = payload["docker"].get("container") or {}
    return {
        "schema_version": payload["schema_version"],
        "generated_at": payload["generated_at"],
        "git_sha": payload["git_sha"],
        "platform": payload["platform"],
        "python": payload["python"],
        "command": payload["command"],
        "native_p50_ms": payload["native"]["p50_ms"],
        "native_p95_ms": payload["native"]["p95_ms"],
        "container_startup_ms": container.get("startup_ms"),
    }


def check_baseline(payload: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    container = payload["docker"].get("container") or {}
    startup = container.get("startup_ms")
    base = baseline.get("container_startup_ms")
    if startup is None:
        failures.append("container startup not measured")
    elif base:
        ceiling = max(2 * base, base + _STARTUP_CEILING_MS)
        if startup > ceiling:
            failures.append(
                f"container startup {startup}ms above ceiling "
                f"{round(ceiling, 3)}ms"
            )
    if container and container.get("uid") not in (None, "1000"):
        failures.append(f"container runs as UID {container['uid']}, expected 1000")
    return failures


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--image-tag", default=DEFAULT_IMAGE_TAG)
    parser.add_argument("--skip-docker", action="store_true")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--check-baseline", action="store_true")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials must be positive")

    payload = run_benchmark(args.trials, args.image_tag, args.skip_docker)
    if args.json_out:
        _write_json(Path(args.json_out), payload)

    native = payload["native"]
    print(
        f"native cold start: {native['trials_ok']}/{native['trials_requested']} ok "
        f"p50={native['p50_ms']:.1f}ms p95={native['p95_ms']:.1f}ms"
    )
    docker = payload["docker"]
    if docker.get("skipped"):
        print(f"docker: skipped ({docker.get('reason')})")
    else:
        build = docker["build"]
        container = docker["container"]
        print(
            f"image build (no-cache): {build['build_ms'] / 1000:.1f}s "
            f"(ok={build['ok']})"
        )
        startup = container.get("startup_ms")
        print(
            "container start -> /health: "
            f"{'n/a' if startup is None else f'{startup:.1f}ms'} "
            f"uid={container.get('uid')}"
        )
        if startup is None and container.get("logs_tail"):
            print("container logs (tail):")
            print(container["logs_tail"])

    for failure in payload["verdict"]["failures"]:
        print(f"FAIL: {failure}", file=sys.stderr)

    if args.update_baseline:
        _write_json(args.baseline, _baseline_snapshot(payload))
        print(f"baseline updated: {args.baseline}")
        return 0 if payload["verdict"]["passed"] else 1

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
            return 0 if payload["verdict"]["passed"] else 1
        if failures:
            return 1
        print("baseline check passed")

    return 0 if payload["verdict"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
