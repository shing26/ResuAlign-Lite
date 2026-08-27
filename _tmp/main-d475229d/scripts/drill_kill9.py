"""Ticket #13 — kill -9 / force-kill recovery drill.

Starts a real uvicorn process against a throwaway data dir, plus a local
HTTP server that accepts the app's LLM requests but never answers (so an
analysis job stays ``running``), queues one analysis job, force-kills the app
process (``TerminateProcess`` on Windows, ``SIGKILL`` elsewhere), restarts it,
and verifies the interrupted job is requeued and reclaimed, with
``job.requeued`` in the structured log.

Run from the repo root:

    python scripts/drill_kill9.py

Exit code 0 = PASS, 1 = FAIL. Prints a drill record suitable for the
runbook's incident log. Requires: repo dev dependencies (uvicorn).
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"


class _HangHandler:
    """Accept connections and never respond, so httpx blocks until timeout."""

    def __init__(self, port: int) -> None:
        self._port = port
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._serve, name="drill-hang-server", daemon=True
        )

    def _serve(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self._port))
            listener.listen(8)
            listener.settimeout(0.2)
            while not self._stop.is_set():
                try:
                    conn, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                # Hold the connection open; the client waits for headers.
                threading.Thread(
                    target=self._hold, args=(conn,), daemon=True
                ).start()

    @staticmethod
    def _hold(conn: socket.socket) -> None:
        try:
            conn.recv(8192)
            time.sleep(600)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _app_env(tmp: Path, hang_port: int, app_port: int) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR)
    env["RESUALIGN_DATA_DIR"] = str(tmp / "data")
    env["RESUALIGN_JOB_DB"] = str(tmp / "data" / "jobs.db")
    env["RESUALIGN_LOG_DIR"] = str(tmp / "logs")
    env["RESUALIGN_PERSONAL_MODE"] = "1"
    env["RESUALIGN_LOG_SAMPLE_RATE"] = "1"
    env["DEEPSEEK_API_KEY"] = "sk-drill-dummy"
    env["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{hang_port}/v1"
    env["RESUALIGN_PORT"] = str(app_port)
    return env


def _start_app(tmp: Path, hang_port: int, app_port: int, tag: str) -> subprocess.Popen:
    log_path = tmp / f"uvicorn-{tag}.log"
    log_file = open(log_path, "w", encoding="utf-8")
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "resualign.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(app_port),
            "--app-dir",
            str(SRC_DIR),
        ],
        cwd=REPO_ROOT,
        env=_app_env(tmp, hang_port, app_port),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )


def _http_json(method: str, url: str, payload: dict | None = None, timeout: float = 5.0):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _wait_health(app_port: int, proc: subprocess.Popen, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{app_port}/health", timeout=1.0
            ) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.3)
    return False


def _poll_status(app_port: int, job_id: str, wanted: set[str], timeout: float) -> list[str]:
    """Poll the job status, returning every distinct status observed."""
    seen: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            body = _http_json("GET", f"http://127.0.0.1:{app_port}/api/jobs/{job_id}")
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
            continue
        status = body.get("status")
        if status not in seen:
            seen.append(status)
        if status in wanted:
            return seen
        time.sleep(0.2)
    return seen


def _db_status(db_path: Path, job_id: str) -> str | None:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _log_contains(tmp: Path, needle: str) -> bool:
    log_file = tmp / "logs" / "app.log"
    if not log_file.exists():
        return False
    return needle in log_file.read_text(encoding="utf-8")


def _dump_uvicorn_logs(tmp: Path) -> None:
    for log_path in sorted(tmp.glob("uvicorn-*.log")):
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        print(f"--- tail {log_path.name} ---")
        print(tail)


def main() -> int:
    print("[drill] kill -9 / force-kill recovery drill")
    results: list[tuple[str, bool, str]] = []
    hang_port = _free_port()
    hang = _HangHandler(hang_port)
    hang.start()

    with tempfile.TemporaryDirectory(prefix="resualign-kill9-") as tmp_dir:
        tmp = Path(tmp_dir)
        (tmp / "data").mkdir()
        (tmp / "logs").mkdir()
        app_port = _free_port()
        proc: subprocess.Popen | None = None
        try:
            proc = _start_app(tmp, hang_port, app_port, "first")
            if not _wait_health(app_port, proc):
                _dump_uvicorn_logs(tmp)
                print(f"[drill] FAIL: app did not become healthy (uvicorn exit={proc.poll()})")
                return 1
            print(f"[drill] app healthy on 127.0.0.1:{app_port} (pid {proc.pid})")

            body = _http_json(
                "POST",
                f"http://127.0.0.1:{app_port}/api/analyze",
                {
                    "resume_text": "Python developer with 5 years of backend experience.",
                    "jd_text": "招聘 Python 后端工程师，要求熟悉 FastAPI 与 SQLite。",
                },
            )
            job_id = body["job_id"]
            print(f"[drill] queued analysis job {job_id}")

            seen = _poll_status(app_port, job_id, {"running"}, timeout=15.0)
            if "running" not in seen:
                print(f"[drill] FAIL: job never reached running (statuses={seen})")
                return 1
            print(f"[drill] job running (statuses={seen})")

            print(f"[drill] force-killing uvicorn pid {proc.pid} (kill -9 / TerminateProcess)")
            proc.kill()
            proc.wait(timeout=10)
            proc = None
            results.append(("force-kill", True, "uvicorn pid terminated"))

            orphan = _db_status(tmp / "data" / "jobs.db", job_id)
            print(f"[drill] orphaned DB row after kill: status={orphan}")
            if orphan != "running":
                print(f"[drill] FAIL: expected orphaned status 'running', got {orphan!r}")
                return 1

            proc = _start_app(tmp, hang_port, app_port, "second")
            if not _wait_health(app_port, proc):
                _dump_uvicorn_logs(tmp)
                print("[drill] FAIL: restart did not become healthy")
                return 1
            print(f"[drill] restarted app healthy (pid {proc.pid})")

            seen = _poll_status(app_port, job_id, {"running", "queued"}, timeout=15.0)
            requeued = _log_contains(tmp, '"job.requeued"')
            http_sampled = _log_contains(tmp, '"http.request"')
            print(f"[drill] post-restart statuses={seen} job.requeued={requeued} http.request={http_sampled}")
            if "running" not in seen:
                print(f"[drill] FAIL: job was not reclaimed after restart (statuses={seen})")
                return 1
            if not requeued:
                print("[drill] FAIL: 'job.requeued' event missing from app.log")
                return 1
            if not http_sampled:
                print("[drill] FAIL: 'http.request' event missing from app.log (sampling rate=1)")
                return 1
            results.append(("requeue", True, f"job {job_id} requeued + reclaimed"))
            results.append(("log", True, "job.requeued / http.request present in app.log"))
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)

    hang.stop()

    print("\n[drill] RESULT")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if all(ok for _, ok, _ in results):
        print("[drill] PASS — interrupted job recovered via startup requeue")
        return 0
    print("[drill] FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(main())
