#!/usr/bin/env python3
"""Local fault injection for the LLM node breaker and role fallback.

The experiment uses two local OpenAI-compatible HTTP servers:

- the primary node returns HTTP 503 until it is explicitly recovered;
- the fallback node always returns a valid JSON chat completion.

Every trial drives the real ``OpenAIClient -> role_router -> LLMNodeStore``
path, trips the primary breaker after three counted failures, verifies that
the fallback takes over, verifies that the disabled primary is skipped, then
recovers the primary with a successful connectivity probe.

No external model, credential, or network access is required.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from resualign.api.services.llm_probe import probe_llm_connection
from resualign.engine.llm_nodes import LLMNodeStore
from resualign.engine.role_router import call_with_role


class _FakeUpstream:
    """Small OpenAI-compatible server whose failure mode can be toggled."""

    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.requests = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="degradation-fake-upstream",
            daemon=True,
        )

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def set_fail(self, fail: bool) -> None:
        with self._lock:
            self.fail = fail

    def request_count(self) -> int:
        with self._lock:
            return self.requests

    def _handler(self):
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.1 + explicit Content-Length keeps the connection alive so
            # the client's pool never reuses a socket the server already
            # closed (HTTP/1.0 default caused intermittent WinError 10053).
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 - stdlib handler API
                # Drain the request body; otherwise the leftover bytes are
                # parsed as the next request line on a kept-alive connection.
                length = int(self.headers.get("Content-Length") or 0)
                if length:
                    self.rfile.read(length)
                with upstream._lock:
                    upstream.requests += 1
                    fail = upstream.fail
                if fail:
                    body = b'{"error":{"message":"injected upstream failure"}}'
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": '{"result":"fallback-ok"}'
                                },
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format, *args):
                return

        return Handler


def _run_trial(index: int) -> dict[str, Any]:
    bad = _FakeUpstream(fail=True)
    good = _FakeUpstream(fail=False)
    bad.start()
    good.start()
    try:
        with tempfile.TemporaryDirectory(
            prefix="resualign-degradation-", ignore_cleanup_errors=True
        ) as tmp:
            store = LLMNodeStore(db_path=Path(tmp) / "nodes.db")
            try:
                tenant = "degradation"
                bad_node = store.create_node(
                    tenant,
                    name="injected-bad",
                    provider="deepseek",
                    model="bad-model",
                    base_url=bad.base_url,
                    api_key="sk-local-fault",
                )
                store.create_node(
                    tenant,
                    name="healthy-fallback",
                    provider="deepseek",
                    model="good-model",
                    base_url=good.base_url,
                    api_key="sk-local-fault",
                    is_active=True,
                )
                assert store.set_role_binding(tenant, "editor", bad_node["node_id"])

                def call_once():
                    return call_with_role(
                        "editor",
                        lambda client: client.chat_json("system", "user"),
                        store,
                        tenant,
                    )

                failure_events: list[int] = []
                for _ in range(3):
                    result, meta = call_once()
                    assert result == {"result": "fallback-ok"}
                    assert meta["fallback_used"] is True
                    assert meta["fallback_node_name"] == "healthy-fallback"
                    failure_events.append(
                        int(
                            store.get_node(tenant, bad_node["node_id"])[
                                "consecutive_failures"
                            ]
                        )
                    )

                row_after_trip = store.get_node(tenant, bad_node["node_id"])
                assert row_after_trip is not None
                assert row_after_trip["auto_disabled"] is True
                assert row_after_trip["consecutive_failures"] == 3
                requests_at_trip = bad.request_count()

                result, meta = call_once()
                assert result == {"result": "fallback-ok"}
                assert meta["fallback_used"] is False
                assert meta["node_name"] == "good-model"
                requests_after_disabled_call = bad.request_count()
                assert requests_after_disabled_call == requests_at_trip

                bad.set_fail(False)
                recovery_start = time.monotonic()
                probe = probe_llm_connection(
                    provider="deepseek",
                    api_key="sk-local-fault",
                    model="bad-model",
                    base_url=bad.base_url,
                    timeout=5.0,
                )
                assert probe["ok"] is True
                store.record_node_health(
                    tenant,
                    bad_node["node_id"],
                    probe["status"],
                    probe["latency_ms"],
                )
                recovery_ms = (time.monotonic() - recovery_start) * 1000
                recovered = store.get_node(tenant, bad_node["node_id"])
                assert recovered is not None
                assert recovered["auto_disabled"] is False
                assert recovered["consecutive_failures"] == 0

                result, meta = call_once()
                assert result == {"result": "fallback-ok"}
                assert meta["fallback_used"] is False
                assert meta["node_name"] == "bad-model"
                assert bad.request_count() > requests_after_disabled_call

                return {
                    "trial": index,
                    "failure_events": failure_events,
                    "trip_after_counted_failures": 3,
                    "fallback_took_over": True,
                    "disabled_node_skipped": True,
                    "recovered": True,
                    "recovery_ms": round(recovery_ms, 3),
                    "bad_requests_at_trip": requests_at_trip,
                    "bad_requests_after_disabled_call": requests_after_disabled_call,
                    "bad_requests_after_recovery": bad.request_count(),
                }
            finally:
                store.close_all_connections()
    finally:
        bad.stop()
        good.stop()


def run_trials(trials: int) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    for index in range(1, trials + 1):
        try:
            results.append(_run_trial(index))
        except Exception as exc:  # noqa: BLE001 - preserve all trial failures
            failures.append(f"trial {index}: {exc.__class__.__name__}: {exc}")

    passed = len(failures) == 0 and len(results) == trials
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "command": " ".join(sys.argv),
        "trials_requested": trials,
        "trials": results,
        "verdict": {"passed": passed, "failures": failures},
    }


def _git_sha() -> str:
    try:
        import subprocess

        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            )
            .strip()
        )
    except Exception:  # noqa: BLE001 - artifact remains useful without git
        return ""


def _write_json(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=5)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)
    if args.trials < 1:
        parser.error("--trials must be positive")

    payload = run_trials(args.trials)
    _write_json(args.json_out, payload)
    for trial in payload["trials"]:
        print(
            f"trial {trial['trial']}: failures={trial['failure_events']} "
            f"recovery_ms={trial['recovery_ms']:.3f} passed"
        )
    for failure in payload["verdict"]["failures"]:
        print(f"FAIL: {failure}", file=sys.stderr)
    print(
        "degradation benchmark: "
        f"{len(payload['trials'])}/{args.trials} trials passed"
    )
    return 0 if payload["verdict"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
