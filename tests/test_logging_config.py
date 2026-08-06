"""Ticket #13: log governance - dictConfig idempotency, rotation, redaction,
sampling, and file output.

Logging is configured at import time in ``resualign.api``, so assertions
about the installed handler graph run in fresh subprocesses (mirroring
``test_state_module.py``); the pure helpers (``redact_fields``,
``should_sample``, ``log_sample_rate``) are tested in-process.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import resualign.api as api_module
from resualign.jobs import JobRegistry
from resualign.observability import (
    log_sample_rate,
    redact_fields,
    should_sample,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_child(code: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run code in a fresh interpreter with isolated log/data dirs."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    env["RESUALIGN_LOG_DIR"] = str(tmp_path / "logs")
    env["RESUALIGN_DATA_DIR"] = str(tmp_path / "data")
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# redact_fields
# ---------------------------------------------------------------------------


def test_redact_fields_masks_api_key_tokens():
    fields = {
        "model": "deepseek-chat sk-live-key-123",
        "error": "LLM error: invalid api key sk-abcXYZ99",
    }
    redacted = redact_fields(fields)
    assert redacted["model"] == "deepseek-chat sk-***"
    assert redacted["error"] == "LLM error: invalid api key sk-***"
    # Input is never mutated.
    assert fields["model"] == "deepseek-chat sk-live-key-123"


def test_redact_fields_truncates_long_error_values():
    long_error = "x" * 1000
    redacted = redact_fields({"error": long_error})
    assert len(redacted["error"]) < len(long_error)
    assert redacted["error"].endswith("[truncated]")
    assert len(redacted["error"]) == 500 + len("[truncated]")
    # Non-error strings are left intact (only redacted for keys).
    assert redacted == {"error": redacted["error"]}


def test_redact_fields_recurses_into_extra_and_preserves_other_types():
    fields = {
        "event": "llm.call",
        "extra": {
            "provider": "deepseek",
            "model": "sk-secret-model",
            "status": "ok",
            "attempts": 2,
            "duration_ms": 12.5,
            "ok": True,
            "nested": {"error": "sk-tok tok"},
        },
    }
    redacted = redact_fields(fields)
    assert redacted["extra"]["model"] == "sk-***"
    assert redacted["extra"]["attempts"] == 2
    assert redacted["extra"]["duration_ms"] == 12.5
    assert redacted["extra"]["ok"] is True
    assert redacted["extra"]["nested"]["error"] == "sk-*** tok"
    assert redacted["event"] == "llm.call"


# ---------------------------------------------------------------------------
# should_sample / log_sample_rate
# ---------------------------------------------------------------------------


def test_should_sample_boundaries():
    for _ in range(100):
        assert should_sample(1.0) is True
    for _ in range(100):
        assert should_sample(0.0) is False
    # A middle rate must produce both outcomes over enough draws.
    seen_true = any(should_sample(0.5) for _ in range(200))
    seen_false = any(not should_sample(0.5) for _ in range(200))
    assert seen_true and seen_false


def test_log_sample_rate_reads_env_and_clamps(monkeypatch):
    monkeypatch.delenv("RESUALIGN_LOG_SAMPLE_RATE", raising=False)
    assert log_sample_rate() == 0.01  # default

    monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "1")
    assert log_sample_rate() == 1.0
    monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "0")
    assert log_sample_rate() == 0.0
    monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "0.25")
    assert log_sample_rate() == 0.25
    # Out-of-range and garbage values are clamped / fall back.
    monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "7")
    assert log_sample_rate() == 1.0
    monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "-2")
    assert log_sample_rate() == 0.0
    monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "not-a-number")
    assert log_sample_rate() == 0.01


# ---------------------------------------------------------------------------
# dictConfig: idempotent install, rotation policy, redacting filter
# ---------------------------------------------------------------------------


def test_logging_config_installs_console_and_rotating_file_once(tmp_path):
    code = """
import logging
import os
import resualign.api as api_module

root = logging.getLogger()
handlers = list(root.handlers)
rotating = [h for h in handlers if type(h).__name__ == "RotatingFileHandler"]
streams = [h for h in handlers if type(h).__name__ == "StreamHandler"]
assert len(handlers) == 2, [type(h).__name__ for h in handlers]
assert len(rotating) == 1 and len(streams) == 1, handlers

fh = rotating[0]
assert fh.maxBytes == 10 * 1024 * 1024, fh.maxBytes
assert fh.backupCount == 5, fh.backupCount
assert fh.encoding == "utf-8", fh.encoding
expected = os.path.join(os.environ["RESUALIGN_LOG_DIR"], "app.log")
assert os.path.normpath(fh.baseFilename) == os.path.normpath(expected), fh.baseFilename
assert all(
    any(type(f).__name__ == "RedactingFilter" for f in h.filters)
    for h in handlers
), "redacting filter missing from handlers"

# Idempotency: repeated configure calls and re-import must not stack handlers.
before = len(root.handlers)
api_module._configure_logging()
api_module._configure_logging()
import importlib
importlib.reload(api_module)
assert len(root.handlers) == before, [type(h).__name__ for h in root.handlers]
print("ok")
"""
    result = _run_child(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


def test_log_file_is_written_to_resualign_log_dir_with_redaction(tmp_path):
    code = """
import logging
import resualign.api  # installs handlers at import time
from resualign.observability import log_event

logger = logging.getLogger("resualign.api")
log_event(logger, "job.finished", extra={
    "job_id": "j-drill-1",
    "outcome": "failed",
    "error": "boom sk-secretkey123",
})
log_event(logger, "llm.call", extra={
    "provider": "deepseek",
    "model": "deepseek-chat",
    "status": "ok",
    "attempts": 1,
})
print("ok")
"""
    result = _run_child(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout

    log_file = tmp_path / "logs" / "app.log"
    assert log_file.exists(), "app.log was not created"
    content = log_file.read_text(encoding="utf-8")
    assert '"event": "job.finished"' in content
    assert '"event": "llm.call"' in content
    assert "sk-***" in content
    assert "sk-secretkey123" not in content, "raw API key leaked to log file"


# ---------------------------------------------------------------------------
# http.request sampling through the middleware
# ---------------------------------------------------------------------------


class _CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def isolated_registry(tmp_path):
    """Point the process singletons the lifespan touches at a temp DB."""
    from resualign.job_library import JobLibraryStore

    saved = {
        "_registry": api_module._registry,
        "_jobs": api_module._jobs,
    }
    api_module._registry = JobRegistry(db_path=tmp_path / "sample.db")
    api_module._jobs = JobLibraryStore(db_path=tmp_path / "sample.db")
    yield
    api_module._registry = saved["_registry"]
    api_module._jobs = saved["_jobs"]


def _http_request_count(records: list[logging.LogRecord]) -> int:
    return sum(
        1 for record in records if '"http.request"' in record.getMessage()
    )


def test_http_request_sampling_respects_env_rate(monkeypatch, isolated_registry):
    logger = logging.getLogger("resualign.api")
    handler = _CaptureHandler()
    logger.addHandler(handler)
    try:
        monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "1")
        client = TestClient(api_module.app)
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert _http_request_count(handler.records) == 2

        handler.records.clear()
        monkeypatch.setenv("RESUALIGN_LOG_SAMPLE_RATE", "0")
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        assert _http_request_count(handler.records) == 0
    finally:
        logger.removeHandler(handler)
