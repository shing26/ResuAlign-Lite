"""Phase 20 key-path smoke: import resume -> crawl JD -> tailor -> export.

The script starts its own FastAPI fake-LLM server plus the ResuAlign app on
independent ports with a temporary SQLite database, so it never touches user
data or an existing service on port 8000.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PHASE20_DIR = Path(__file__).resolve().parent
SHOTS = PHASE20_DIR / "screenshots"


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def api_call(base: str, method: str, path: str, payload=None):
    data = (
        json.dumps(payload).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(
        base + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AssertionError(
            f"{method} {path} -> {exc.code}: {body}"
        ) from exc


def new_page(context, errors: dict):
    page = context.new_page()
    page.on(
        "console",
        lambda msg: errors["console"].append(msg.text)
        if msg.type == "error"
        else None,
    )
    page.on(
        "pageerror",
        lambda exc: errors["page"].append(str(exc)),
    )
    page.on("dialog", lambda dialog: dialog.accept())
    return page


def assert_no_overflow(page, label: str) -> None:
    overflow = page.evaluate(
        "document.documentElement.scrollWidth "
        "> window.innerWidth + 1"
    )
    expect(not overflow, f"{label} overflows horizontally")


class FakeLLMServer:
    """Own FastAPI fake-LLM server running under uvicorn."""

    def __init__(self) -> None:
        self.port = free_port()
        self.tmp = tempfile.TemporaryDirectory(
            prefix="resualign-phase20-llm-"
        )
        self.tmp_path = Path(self.tmp.name)
        self.proc: subprocess.Popen | None = None
        self.out_file = None
        self.err_file = None
        self.base_url = f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        self.out_file = open(self.tmp_path / "llm.out.log", "wb")
        self.err_file = open(self.tmp_path / "llm.err.log", "wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "fake_llm:app",
                "--host", "127.0.0.1",
                "--port", str(self.port),
                "--app-dir", str(PHASE20_DIR),
            ],
            cwd=str(ROOT),
            stdout=self.out_file,
            stderr=self.err_file,
            creationflags=flags,
        )
        self._wait_health()

    def _wait_health(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                log = (self.tmp_path / "llm.err.log").read_text(
                    errors="replace"
                )
                raise RuntimeError(f"fake LLM exited early:\n{log}")
            try:
                urllib.request.urlopen(
                    f"{self.base_url}/health", timeout=1
                ).read()
                return
            except urllib.error.URLError:
                time.sleep(0.2)
        raise RuntimeError("fake LLM server did not become healthy in time")

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


class AppServer:
    def __init__(self, llm: FakeLLMServer) -> None:
        self.llm = llm
        self.tmp = tempfile.TemporaryDirectory(
            prefix="resualign-phase20-app-"
        )
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "jobs.db"
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.out_file = None
        self.err_file = None
        self.base_url = f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = os.environ.copy()
        env.update({
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "smoke-key",
            "DEEPSEEK_MODEL": "smoke-model",
            "DEEPSEEK_BASE_URL": f"{self.llm.base_url}/v1",
            "RESUALIGN_PERSONAL_MODE": "1",
            "RESUALIGN_JOB_DB": str(self.db_path),
            "RESUALIGN_HOST": "127.0.0.1",
            "RESUALIGN_PORT": str(self.port),
        })
        old_pythonpath = env.get("PYTHONPATH")
        if old_pythonpath:
            env["PYTHONPATH"] = str(SRC) + os.pathsep + old_pythonpath
        else:
            env["PYTHONPATH"] = str(SRC)
        self.out_file = open(self.tmp_path / "app.out.log", "wb")
        self.err_file = open(self.tmp_path / "app.err.log", "wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "resualign.api:app",
                "--host", "127.0.0.1",
                "--port", str(self.port),
                "--app-dir", str(SRC),
            ],
            cwd=str(ROOT),
            env=env,
            stdout=self.out_file,
            stderr=self.err_file,
            creationflags=flags,
        )
        self._wait_health()

    def _wait_health(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                log = (self.tmp_path / "app.err.log").read_text(
                    errors="replace"
                )
                raise RuntimeError(f"app server exited early:\n{log}")
            try:
                urllib.request.urlopen(
                    f"{self.base_url}/health", timeout=1
                ).read()
                return
            except urllib.error.URLError:
                time.sleep(0.2)
        raise RuntimeError("app server did not become healthy in time")

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


def run_key_path(
    context,
    errors: dict,
    base: str,
    prefix: str,
    created: dict,
) -> None:
    resume_title = f"{prefix} Master Resume"
    resume_content = (
        "# Python Backend Engineer\n\n"
        "5 years of experience\n\n"
        "- FastAPI\n"
        "- Redis\n"
        "- Docker"
    )
    jd_text = (
        "Hiring a Python backend engineer. Requirements: FastAPI async "
        "endpoints and Redis caching for high concurrency. Salary 25-35K."
    )
    page = new_page(context, errors)

    # Import resume through the resume center. The default #/resume route
    # opens the newest resume's detail once one exists, so the list route is
    # used explicitly to keep each run able to create a fresh resume.
    page.goto(f"{base}/#/resume/list", wait_until="domcontentloaded")
    page.wait_for_selector('[data-action="new-resume"]')
    page.locator('[data-action="new-resume"]').first.click()
    page.fill(
        '[data-form="resume-create"] input[name="title"]', resume_title
    )
    page.fill(
        '[data-form="resume-create"] textarea[name="content"]',
        resume_content,
    )
    page.click('[data-form="resume-create"] button[type="submit"]')
    page.wait_for_selector(".card.resume-card", timeout=10000)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if page.locator(f"text={resume_title}").count() >= 1:
            break
        page.wait_for_timeout(200)
    match_count = page.locator(f"text={resume_title}").count()
    expect(match_count >= 1, "imported resume list card missing")
    # v3 default route opens the newest resume's detail view; verify it too.
    page.goto(f"{base}/#/resume", wait_until="domcontentloaded")
    page.wait_for_selector("[data-resume-sheet-doc]", timeout=10000)
    assert_no_overflow(page, f"{prefix} resume center")
    resumes = api_call(base, "GET", "/api/master-resumes")
    resume_id = next(
        item["resume_id"]
        for item in resumes
        if item["title"] == resume_title
    )
    created["resume_ids"].append(resume_id)

    # Universal input: paste JD text, confirm, land in the Optimizer.
    page.goto(f"{base}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector("[data-command-trigger]")
    page.click("[data-command-trigger]")
    page.wait_for_selector("[data-command-palette]:not([hidden])")
    page.fill(
        "[data-command-input]",
        jd_text,
    )
    expect(
        page.locator("[data-command-preview] .badge").count() >= 1,
        "command palette preview badge missing",
    )
    page.click("[data-command-confirm]")
    page.wait_for_timeout(1500)
    try:
        page.wait_for_selector("[data-surface-mode='optimizer']", timeout=15000)
    except Exception:
        raise
    expect(
        page.locator("[data-jd-canvas]").count() == 1,
        "JD canvas missing after universal input",
    )
    expect(
        page.locator("[data-resume-canvas]").count() == 1,
        "resume canvas missing after universal input",
    )
    assert_no_overflow(page, f"{prefix} jobs")

    session_id = page.evaluate("location.hash.split('/').pop()")
    session = api_call(
        base, "GET", f"/api/workspace/session/{session_id}"
    )
    job_id = session["job"]["job_id"]
    created["job_ids"].append(job_id)
    page.close()

    # Tailor in the Optimizer split canvas.
    page = new_page(context, errors)
    page.goto(f"{base}/#/workspace/{job_id}", wait_until="domcontentloaded")
    page.wait_for_selector("[data-surface-mode='optimizer']")
    if not page.locator("[data-form='split-align']").first.is_visible():
        page.locator("[data-wb-tab-v3='controls']").first.click()
    page.wait_for_selector("[data-form='split-align']")
    page.select_option(
        '[data-form="split-align"] select[name="master_resume_id"]', resume_id
    )
    page.click('[data-form="split-align"] button[type="submit"]')
    # The workbench may mount in A4 preview mode when a draft already
    # exists; switch to diff mode so the suggestion cards are visible.
    diff_toggle = page.locator("[data-wb-view-mode='diff']")
    if diff_toggle.count() and not diff_toggle.first.evaluate(
        "(el) => el.classList.contains('active')"
    ):
        diff_toggle.first.click()
    # The canvas keeps re-rendering while the job runs, so wait for the
    # terminal state before trying to click a diff-card action.
    deadline = time.monotonic() + 60
    status_job = {}
    while time.monotonic() < deadline:
        status_job = api_call(base, "GET", f"/api/jobs/{job_id}")
        if status_job.get("alignment_status") == "succeeded":
            break
        page.wait_for_timeout(500)
    expect(
        status_job.get("alignment_status") == "succeeded",
        "alignment did not reach succeeded state",
    )
    # On narrow screens the split-canvas panes are tab-gated and the diff
    # pane (with the result cards) starts hidden; switch to it so the cards
    # are visible on mobile. Desktop tab bar is display:none, so only click
    # when actually visible.
    try:
        page.wait_for_selector("[data-wb-tab='diff']", timeout=15000)
        if page.locator("[data-wb-tab='diff']").first.is_visible():
            page.click("[data-wb-tab='diff']")
    except Exception:
        pass
    page.wait_for_selector(".diff-card", timeout=30000)
    expect(
        page.locator(".diff-card").count() >= 1,
        "tailor diff controls missing",
    )

    # Accept one bullet so the canonical final draft is persisted, then
    # export markdown from the final-draft panel (the v3 export dock is
    # disabled until a final draft exists).
    first_card = page.locator(".diff-card").first
    first_card.locator('[data-action="accept-bullet"]').click()
    panel = page.locator("[data-final-draft-panel]:not([hidden])")
    panel.wait_for(timeout=15000)
    deadline = time.monotonic() + 15
    job = {}
    while time.monotonic() < deadline:
        job = api_call(base, "GET", f"/api/jobs/{job_id}")
        if (job.get("final_draft") or "").strip():
            break
        page.wait_for_timeout(200)
    expect(
        (job.get("final_draft") or "").strip(),
        "final draft was not persisted after accepting a bullet",
    )
    with page.expect_download() as download_info:
        panel.locator('[data-action="export-final-draft-md"]').click()
    download = download_info.value
    expect(
        download.suggested_filename.endswith(".md"),
        "markdown export filename is not .md",
    )

    slug = prefix.lower().replace(" ", "-")
    page.screenshot(
        path=str(SHOTS / f"phase20-{slug}-workspace.png"),
        full_page=True,
    )
    assert_no_overflow(page, f"{prefix} workspace")

    # Export PDF on the desktop viewport from the same final-draft panel.
    # The app writes #print-root, calls window.print(), then clears it, so
    # validate the canonical export payload and re-render it for page.pdf().
    if prefix == "Phase20":
        panel = page.locator("[data-final-draft-panel]:not([hidden])")
        panel.wait_for(timeout=15000)
        with page.expect_response(
            lambda resp: resp.url.endswith("/exports")
            and resp.request.method == "POST"
        ) as response_info:
            panel.locator('[data-action="export-final-draft"]').click()
        export = response_info.value.json()
        expect(export.get("format") == "pdf", "pdf export format mismatch")
        expect(
            export.get("render") == "print-html",
            "pdf export render type mismatch",
        )
        content = export.get("content") or ""
        expect("export-article" in content, "pdf print html missing article")
        expect("定稿内容" in content, "pdf print html missing draft section")
        expect(
            "<button" not in content.lower(),
            "pdf print html contains buttons",
        )
        page.evaluate(
            """content => {
                const node = document.querySelector("#print-root");
                if (node) node.innerHTML = content;
            }""",
            content,
        )
        expect(
            page.locator("#print-root button").count() == 0,
            "final draft print root contains buttons",
        )
        pdf_path = SHOTS / f"phase20-{slug}-final-draft.pdf"
        page.pdf(path=str(pdf_path), format="A4")
        expect(pdf_path.stat().st_size > 1000, "final draft PDF is empty")
    page.close()


def main() -> None:
    errors = {"console": [], "page": []}
    llm = FakeLLMServer()
    llm.start()
    app = AppServer(llm)
    app.start()
    base = app.base_url
    created = {"resume_ids": [], "job_ids": []}
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                desktop = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    accept_downloads=True,
                )
                run_key_path(desktop, errors, base, "Phase20", created)
                desktop.close()

                mobile = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                    accept_downloads=True,
                )
                run_key_path(
                    mobile, errors, base, "Phase20 Mobile", created
                )
                mobile.close()
            finally:
                browser.close()

        expect(not errors["page"], f"page errors: {errors['page']}")
        severe = [
            error
            for error in errors["console"]
            if "favicon" not in error.lower()
            and "failed to load" not in error.lower()
        ]
        expect(not severe, f"console errors: {severe}")
        # Q2 gate: every required fake-LLM stage must have been hit >= 1.
        # The fake server returns 500 (surfaced as AssertionError by api_call)
        # when a required stage was never reached.
        api_call(llm.base_url, "GET", "/assert-stages")
    finally:
        for job_id in created["job_ids"]:
            try:
                api_call(base, "DELETE", f"/api/jobs/{job_id}")
            except Exception:
                pass
        for resume_id in created["resume_ids"]:
            try:
                api_call(
                    base, "DELETE", f"/api/master-resumes/{resume_id}"
                )
            except Exception:
                pass
        app.stop()
        llm.stop()
    print("PHASE20 SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PHASE20 SMOKE FAILED: {exc}", file=sys.stderr)
        raise
