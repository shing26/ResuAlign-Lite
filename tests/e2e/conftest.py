"""Browser E2E fixtures for ResuAlign: fake LLM + app servers, Playwright.

The suite follows the phase-20 smoke pattern: it boots its own FastAPI
fake-LLM server and the real ResuAlign app on independent ports with a
temporary SQLite database, so tests never touch user data or an existing
service on port 8000.

Gate: these tests need Playwright + a Chromium binary, so they are skipped
unless the ``--e2e`` flag is passed. Stage 1 (``pytest tests/``) collects
this directory but never runs it; Stage 3 runs it with ``--e2e``.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent
ROOT = E2E_DIR.parents[1]
SRC = ROOT / "src"
PHASE20_DIR = ROOT / ".scratch" / "phase-20"
ARTIFACTS_DIR = E2E_DIR / "artifacts"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run browser E2E tests (requires Playwright + Chromium)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--e2e"):
        return
    # Skip only items carrying the e2e marker (pytest 9 applies sub-directory
    # conftest collection hooks session-wide, so never blanket-skip items).
    skip = pytest.mark.skip(reason="browser E2E: run with --e2e")
    for item in items:
        if item.get_closest_marker("e2e"):
            item.add_marker(skip)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> None:
    """Stash the call-phase report so fixtures can detect test failure.

    ``item.rep_call`` (the classic hook) is not populated on pytest 9; the
    page fixture reads this stash to export failure artifacts.
    """
    outcome = yield
    if call.when == "call":
        item._e2e_call_report = outcome  # noqa: SLF001
    return outcome


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_health(base_url: str, proc: subprocess.Popen, log_path: Path,
                 timeout: float = 30.0) -> None:
    """Wait for a subprocess server's /health endpoint to answer."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log = log_path.read_text(errors="replace")
            raise RuntimeError(f"server exited early:\n{log}")
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=1).read()
            return
        except urllib.error.URLError:
            time.sleep(0.2)
    raise RuntimeError(f"server {base_url} did not become healthy in time")


class _SubprocessServer:
    """Minimal subprocess lifecycle shared by the fake LLM and app."""

    def __init__(self, prefix: str) -> None:
        self.port = _free_port()
        self.tmp = tempfile.TemporaryDirectory(prefix=prefix)
        self.tmp_path = Path(self.tmp.name)
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.proc: subprocess.Popen | None = None
        self.out_file = None
        self.err_file = None

    def start(self, argv: list[str], env: dict[str, str]) -> None:
        self.out_file = open(self.tmp_path / "server.out.log", "wb")
        self.err_file = open(self.tmp_path / "server.err.log", "wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            argv,
            cwd=str(ROOT),
            env=env,
            stdout=self.out_file,
            stderr=self.err_file,
            creationflags=flags,
        )
        _wait_health(self.base_url, self.proc, self.tmp_path / "server.err.log")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self.out_file:
            self.out_file.close()
        if self.err_file:
            self.err_file.close()
        self.tmp.cleanup()


class FakeLLMServer(_SubprocessServer):
    """Own FastAPI fake-LLM server (``.scratch/phase-20/fake_llm.py``)."""

    def __init__(self) -> None:
        super().__init__(prefix="resualign-e2e-llm-")

    def start(self) -> None:
        env = os.environ.copy()
        super().start(
            [
                sys.executable, "-m", "uvicorn",
                "fake_llm:app",
                "--host", "127.0.0.1",
                "--port", str(self.port),
                "--app-dir", str(PHASE20_DIR),
            ],
            env=env,
        )


class AppServer(_SubprocessServer):
    """The real ResuAlign app on a temp DB pointed at the fake LLM."""

    def __init__(self, llm: FakeLLMServer) -> None:
        super().__init__(prefix="resualign-e2e-app-")
        self.llm = llm
        self.db_path = self.tmp_path / "jobs.db"

    def start(self) -> None:
        env = os.environ.copy()
        env.update({
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "e2e-smoke-key",
            "DEEPSEEK_MODEL": "e2e-smoke-model",
            "DEEPSEEK_BASE_URL": f"{self.llm.base_url}/v1",
            "RESUALIGN_PERSONAL_MODE": "1",
            "RESUALIGN_JOB_DB": str(self.db_path),
            "RESUALIGN_HOST": "127.0.0.1",
            "RESUALIGN_PORT": str(self.port),
        })
        old_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(SRC) + os.pathsep + old_pythonpath
            if old_pythonpath
            else str(SRC)
        )
        super().start(
            [
                sys.executable, "-m", "uvicorn",
                "resualign.api:app",
                "--host", "127.0.0.1",
                "--port", str(self.port),
                "--app-dir", str(SRC),
            ],
            env=env,
        )


@pytest.fixture(scope="session")
def llm_server() -> FakeLLMServer:
    server = FakeLLMServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def llm_base_url(llm_server: FakeLLMServer) -> str:
    return llm_server.base_url


@pytest.fixture(scope="session")
def app_server(llm_server: FakeLLMServer) -> AppServer:
    server = AppServer(llm_server)
    server.start()
    yield server
    server.stop()


@pytest.fixture(scope="session")
def base_url(app_server: AppServer) -> str:
    return app_server.base_url


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def api_call(base_url: str):
    """JSON API helper against the app; raises AssertionError on HTTP errors."""

    def call(method: str, path: str, payload: dict | None = None):
        data = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Content-Type": "application/json"} if data else {}
        request = urllib.request.Request(
            base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"{method} {path} -> {exc.code}: {body}") from exc

    return call


@pytest.fixture(scope="session")
def llm_api_call(llm_base_url: str):
    """JSON API helper against the fake LLM's control endpoints."""

    def call(method: str, path: str, payload: dict | None = None):
        data = (
            json.dumps(payload).encode("utf-8")
            if payload is not None
            else None
        )
        headers = {"Content-Type": "application/json"} if data else {}
        request = urllib.request.Request(
            llm_base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise AssertionError(f"{method} {path} -> {exc.code}: {body}") from exc

    return call


@pytest.fixture(scope="session")
def browser():
    """One headless Chromium for the whole session."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        chromium = pw.chromium.launch(headless=True)
        yield chromium
        chromium.close()


@pytest.fixture()
def page(browser, base_url: str, artifacts_dir: Path, request: pytest.FixtureRequest):
    """A fresh page wired to capture console/page errors.

    On test failure the page's screenshot, DOM snapshot, and console log
    are exported to ``tests/e2e/artifacts/<test-name>/`` so every failure
    is debuggable without a rerun.
    """
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        accept_downloads=True,
    )
    errors = {"all": [], "console": [], "page": []}

    def on_console(message) -> None:
        errors["all"].append(message.text)
        if message.type == "error":
            errors["console"].append(message.text)

    def on_pageerror(exc) -> None:
        errors["page"].append(str(exc))

    page_obj = context.new_page()
    page_obj.on("console", on_console)
    page_obj.on("pageerror", on_pageerror)
    page_obj.on("dialog", lambda dialog: dialog.accept())
    # Tests read this dict through helpers.capture_errors(page).
    page_obj._e2e_errors = errors  # noqa: SLF001 - private test wiring

    yield page_obj

    report = getattr(request.node, "_e2e_call_report", None)
    if report is not None and report.failed:
        _capture_failure(page_obj, errors, artifacts_dir, request.node.name)
    context.close()


def _capture_failure(
    page_obj, errors: dict, artifacts_dir: Path, label: str
) -> None:
    """Export screenshot + DOM snapshot + console log for a failing test."""
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", label)
    out = artifacts_dir / name
    out.mkdir(parents=True, exist_ok=True)
    try:
        page_obj.screenshot(path=str(out / "screenshot.png"), full_page=True)
    except Exception as exc:  # noqa: BLE001 - artifact capture must not mask the failure
        (out / "screenshot-error.txt").write_text(str(exc), encoding="utf-8")
    try:
        (out / "dom.html").write_text(page_obj.content(), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        (out / "dom-error.txt").write_text(str(exc), encoding="utf-8")
    lines = [
        "== console (all) ==",
        *errors["all"],
        "== console (errors) ==",
        *errors["console"],
        "== page errors ==",
        *errors["page"],
    ]
    (out / "console.txt").write_text("\n".join(lines), encoding="utf-8")

