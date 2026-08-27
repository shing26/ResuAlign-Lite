"""Phase 16 unified Playwright smoke pass (desktop + mobile).

The script starts its own uvicorn on an independent port with a temporary
SQLite database and a local fake LLM endpoint, so it never touches user data
or an existing service on port 8000.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SHOTS = Path(__file__).resolve().parent / "screenshots"

BUILTIN_FUNCTIONS = [
    "后端", "前端", "算法", "数据", "测试", "运维",
    "产品", "设计", "运营", "销售", "其他",
]

PREFIX = "Phase16 回归"
RESUME_TITLE = f"{PREFIX} 简历"
JOB_TITLE = f"{PREFIX} 岗位"
RESUME_CONTENT = (
    "# Python 后端工程师\n\n"
    "5 年经验\n\n"
    "- FastAPI\n"
    "- Redis\n"
    "- Docker"
)
JOB_JD = (
    "招聘 Python 后端工程师\n"
    "要求 FastAPI 与 Redis\n"
    "月薪 25-35K"
)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def route_json(route, status: int, body) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(body, ensure_ascii=False),
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _resume_from_user(user: str) -> str:
    match = re.search(r"Resume:\n(.*?)\n\nGap Report:", user, re.S)
    return match.group(1).strip() if match else ""


def fake_llm_response(system: str, user: str) -> dict:
    """Return a deterministic OpenAI-compatible response per prompt."""
    if "job classifier" in system:
        return {
            "job_function": "后端",
            "seniority": "高级",
            "tech_tags": ["Python", "FastAPI"],
        }
    if "resume auditor" in system:
        return {
            "score": 82,
            "skills": ["Python", "FastAPI"],
            "issues": ["补充量化结果"],
        }
    if "job description analyst" in system:
        return {
            "must_have_skills": ["Python", "FastAPI"],
            "nice_to_have_skills": ["Redis"],
            "soft_skills": [],
            "business_scenarios": ["高并发"],
            "min_years_experience": 5,
            "education_requirements": [],
        }
    if "resume gap analyst" in system:
        return {
            "missing_keywords": ["FastAPI async endpoints"],
            "misaligned_emphasis": [],
            "strength_matches": ["Python"],
        }
    if "precise resume editor" in system:
        resume = _resume_from_user(user)
        original = "5 年经验" if "5 年经验" in resume else (
            resume.splitlines()[0] if resume else "Python 后端工程师"
        )
        proposed = f"{original}（高并发）"
        updated = resume.replace(original, proposed, 1)
        return {
            "sections": {"experience": updated},
            "diffs": [{
                "type": "modify",
                "original": original,
                "proposed": proposed,
                "reason": "匹配 JD 高并发场景",
                "confidence": "high",
                "provenance": original,
            }],
        }
    if "resume quality judge" in system:
        return {
            "jd_match_score": 88,
            "improvement": 12,
            "hallucination_detected": False,
            "hallucination_details": [],
            "gap_coverage": 0.9,
        }
    return {"score": 80, "skills": [], "issues": []}


class LLMHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        request = json.loads(raw.decode("utf-8"))
        messages = request.get("messages", [])
        system = next(
            (m.get("content", "") for m in messages
             if m.get("role") == "system"),
            "",
        )
        user = next(
            (m.get("content", "") for m in messages
             if m.get("role") == "user"),
            "",
        )
        payload = fake_llm_response(system, user)
        content = json.dumps(payload, ensure_ascii=False)
        body = json.dumps({
            "choices": [{"message": {"content": content}}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


class LLMServer:
    def __init__(self) -> None:
        self.port = free_port()
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", self.port), LLMHandler
        )
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, daemon=True
        )

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class AppServer:
    def __init__(self, llm: LLMServer) -> None:
        self.llm = llm
        self.tmp = tempfile.TemporaryDirectory(
            prefix="resualign-phase16-"
        )
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "jobs.db"
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.stdout_file = None
        self.stderr_file = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = os.environ.copy()
        env.update({
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "smoke-key",
            "DEEPSEEK_MODEL": "smoke-model",
            "DEEPSEEK_BASE_URL": self.llm.base_url,
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
        self.stdout_file = open(self.tmp_path / "uvicorn.log", "wb")
        self.stderr_file = open(
            self.tmp_path / "uvicorn.err.log", "wb"
        )
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
            stdout=self.stdout_file,
            stderr=self.stderr_file,
            creationflags=flags,
        )
        self._wait_health()

    def _wait_health(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc and self.proc.poll() is not None:
                log = (self.tmp_path / "uvicorn.err.log").read_text(
                    errors="replace"
                )
                raise RuntimeError(f"uvicorn exited early:\n{log}")
            try:
                urllib.request.urlopen(
                    f"{self.base_url}/health", timeout=1
                ).read()
                return
            except urllib.error.URLError:
                time.sleep(0.2)
        raise RuntimeError("uvicorn did not become healthy in time")

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)
        if self.stdout_file:
            self.stdout_file.close()
        if self.stderr_file:
            self.stderr_file.close()
        self.tmp.cleanup()


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


def test_no_login_wall(context, errors, base: str) -> None:
    page = new_page(context, errors)
    page.route(
        "**/api/master-resumes",
        lambda route: route_json(route, 401, {"detail": "Unauthorized"}),
    )
    page.goto(f"{base}/#/resume", wait_until="domcontentloaded")
    page.wait_for_selector("#app h3")
    expect(
        page.locator(".modal-backdrop").count() == 0,
        "login modal appeared after 401",
    )
    expect(
        page.locator('[data-form="login"]').count() == 0,
        "login form appeared after 401",
    )
    expect(
        "个人模式" in page.locator("#mode-label").inner_text(),
        "personal mode label missing",
    )
    expect(
        "出错了" in page.locator("#app").inner_text(),
        "401 did not render a readable error",
    )
    page.close()


def test_resume_archive_and_diagnosis(
    context, errors, base: str, resume_id: str
) -> None:
    page = new_page(context, errors)
    page.goto(
        f"{base}/#/resume/{resume_id}", wait_until="domcontentloaded"
    )
    page.wait_for_selector(".resume-doc h1")
    expect(
        page.locator(".resume-doc h1").inner_text()
        == "Python 后端工程师",
        "resume archive heading missing",
    )
    expect(
        page.locator(".card", has_text="v1").count() > 0,
        "version history missing",
    )
    page.click('[data-action="print-resume"]')
    page.wait_for_selector(
        "#print-root .resume-doc", state="attached"
    )
    expect(
        page.locator("#print-root button").count() == 0,
        "resume print root contains buttons",
    )
    page.pdf(path=str(SHOTS / "phase16-resume-print.pdf"), format="A4")
    expect(
        (SHOTS / "phase16-resume-print.pdf").stat().st_size > 1000,
        "resume PDF is empty",
    )

    diagnosis = {"phase": "cancel", "job_id": ""}

    def handle_diagnose(route):
        if diagnosis["phase"] == "cancel":
            diagnosis["job_id"] = "phase16-diag-cancel"
            diagnosis["phase"] = "canceled"
            route_json(route, 202, {
                "job_id": diagnosis["job_id"],
                "status": "queued",
            })
        else:
            diagnosis["job_id"] = "phase16-diag-ok"
            route_json(route, 202, {
                "job_id": diagnosis["job_id"],
                "status": "queued",
            })

    def handle_diag_job(route):
        job_id = diagnosis["job_id"]
        if job_id == "phase16-diag-cancel":
            route_json(route, 200, {
                "job_id": job_id,
                "status": "queued",
                "stage": "queued",
                "message": "排队中...",
                "elapsed_seconds": 0,
                "result": None,
                "error": None,
            })
        else:
            route_json(route, 200, {
                "job_id": job_id,
                "status": "succeeded",
                "stage": "succeeded",
                "message": "诊断完成",
                "elapsed_seconds": 1.2,
                "result": {
                    "score": 82,
                    "model": "smoke-model",
                    "diagnosis": {
                        "score": 82,
                        "skills": ["Python", "FastAPI"],
                        "issues": ["补充量化结果"],
                        "suggestions": ["建议：补充量化结果"],
                        "model": "smoke-model",
                    },
                },
                "error": None,
            })

    page.route(
        re.compile(
            r".*/api/master-resumes/" + re.escape(resume_id)
            + r"/diagnose$"
        ),
        handle_diagnose,
    )
    page.route(
        re.compile(r".*/api/jobs/phase16-diag-cancel$"),
        handle_diag_job,
    )
    page.route(
        re.compile(r".*/api/jobs/phase16-diag-ok$"),
        handle_diag_job,
    )
    page.route(
        re.compile(r".*/api/jobs/phase16-diag-cancel/cancel$"),
        lambda route: route_json(
            route, 200, {"job_id": "phase16-diag-cancel",
                         "status": "canceled"}
        ),
    )

    page.click('[data-action="diagnose-resume"]')
    page.wait_for_selector(
        "[data-diagnosis-progress]:not([hidden])", timeout=2000
    )
    page.wait_for_selector(
        '[data-action="cancel-diagnosis"]:not([hidden])'
    )
    page.click('[data-action="cancel-diagnosis"]')
    page.wait_for_selector(
        "[data-diagnosis-error]:not([hidden])"
    )
    expect(
        "诊断已取消" in page.locator(
            "[data-diagnosis-error]"
        ).inner_text(),
        "canceled diagnosis did not return to retry state",
    )
    page.click('[data-action="rerun-diagnosis"]')
    page.wait_for_selector(".diagnosis-score")
    expect(
        page.locator(".diagnosis-score .score-ring span").inner_text()
        == "82",
        "diagnosis score missing",
    )
    expect(
        page.locator(".diagnosis-list").count() == 2,
        "diagnosis issues/suggestions missing",
    )

    detail = api_call(
        base, "GET", f"/api/master-resumes/{resume_id}"
    )
    detail["latest_diagnosis_job_id"] = "phase16-diag-ok"
    page.route(
        re.compile(
            r".*/api/master-resumes/" + re.escape(resume_id) + r"$"
        ),
        lambda route: route_json(route, 200, detail),
    )
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector(".diagnosis-score")
    expect(
        page.locator(".diagnosis-score .score-ring span").inner_text()
        == "82",
        "diagnosis did not recover after refresh",
    )
    page.screenshot(
        path=str(SHOTS / "phase16-diagnosis.png"), full_page=True
    )
    page.close()


def test_jd_parse_flows(context, errors, base: str) -> None:
    parsed = {
        "title": "Senior Backend Engineer",
        "jd_text": "Python backend\nFastAPI and Redis\nSalary 25-35K",
        "company": "Example Corp",
        "city": "Shanghai",
        "salary_min": 25000,
        "salary_max": 35000,
        "salary_currency": "CNY",
        "source_url": "https://example.com/jobs/backend",
    }

    page = new_page(context, errors)
    page.route(
        "**/api/jobs/parse-jd",
        lambda route: route_json(route, 200, parsed),
    )
    page.goto(f"{base}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector("text=岗位库")
    page.click('[data-action="show-add-job"]')
    page.click('[data-mode="url"]')
    page.fill(
        '[data-form="job-create"] input[name="jd_url"]',
        "https://example.com/jobs/backend",
    )
    page.click('[data-action="parse-jd-link"]')
    page.wait_for_selector("text=已解析：Senior Backend Engineer")
    expect(
        page.input_value(
            '[data-form="job-create"] input[name="title"]'
        ) == "Senior Backend Engineer",
        "parse did not prefill title",
    )
    expect(
        page.input_value(
            '[data-form="job-create"] input[name="salary_min"]'
        ) == "25000",
        "parse did not prefill salary_min",
    )
    expect(
        page.input_value(
            '[data-form="job-create"] input[name="salary_max"]'
        ) == "35000",
        "parse did not prefill salary_max",
    )
    page.close()

    failure = {
        "code": "login_required",
        "reason": "该站点需要登录或权限，无法直接读取正文",
        "action": "请改用粘贴 JD 或更换链接重试",
    }
    page = new_page(context, errors)
    page.route(
        "**/api/jobs/parse-jd",
        lambda route: route_json(route, 502, failure),
    )
    page.goto(f"{base}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector("text=岗位库")
    page.click('[data-action="show-add-job"]')
    page.click('[data-mode="url"]')
    page.fill(
        '[data-form="job-create"] input[name="jd_url"]',
        "https://example.com/jobs/login-wall",
    )
    page.click('[data-action="parse-jd-link"]')
    page.wait_for_selector(".jd-parse-status.form-error")
    expect(
        "解析失败" in page.locator(
            "[data-jd-parse-status]"
        ).inner_text(),
        "parse failure message missing",
    )
    expect(
        page.locator('[data-action="use-paste-mode"]').count() == 1,
        "use-paste-mode button missing",
    )
    page.click('[data-action="use-paste-mode"]')
    expect(
        page.input_value(
            '[data-form="job-create"] input[name="source_url"]'
        ) == "https://example.com/jobs/login-wall",
        "source URL was not preserved in paste mode",
    )
    expect(
        page.is_visible(
            '[data-form="job-create"] textarea[name="jd_text"]'
        ),
        "paste mode did not show editable JD text",
    )
    page.close()


def test_wordlist_sync(context, errors, base: str) -> None:
    page = new_page(context, errors)
    page.goto(f"{base}/#/settings", wait_until="domcontentloaded")
    page.wait_for_selector("text=分类词表")
    page.fill(
        '[data-form="settings-vocabulary"] '
        'textarea[name="job_functions"]',
        "架构\n后端",
    )
    page.fill(
        '[data-form="settings-vocabulary"] '
        'textarea[name="seniorities"]',
        "首席\n高级",
    )
    page.fill(
        '[data-form="settings-vocabulary"] '
        'textarea[name="statuses"]',
        "待定\n已投递",
    )
    page.click(
        '[data-form="settings-vocabulary"] button[type="submit"]'
    )
    page.wait_for_selector("text=分类词表已保存")
    page.goto(f"{base}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector('select[name="job_function"]')
    expect(
        "架构" in page.locator(
            '[data-form="job-filter"] select[name="job_function"]'
            " option"
        ).all_inner_texts(),
        "custom function missing from filter",
    )
    page.wait_for_selector('[data-action="edit-job"]')
    page.click('[data-action="edit-job"]')
    modal_function = '.modal select[name="job_function"]'
    page.wait_for_selector(modal_function)
    expect(
        "架构" in page.locator(modal_function + " option").all_inner_texts(),
        "custom function missing from edit modal",
    )
    page.close()

    fallback_job = {
        "job_id": "phase16-fallback",
        "title": "Fallback Job",
        "company": "Example",
        "location": "Shanghai",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "CNY",
        "job_function": "后端",
        "seniority": "高级",
        "status": "未投递",
        "tech_tags": [],
        "jd_text": "Backend",
        "classification_pending": 0,
    }
    page = new_page(context, errors)
    page.route(
        "**/api/settings",
        lambda route: route_json(route, 500, {"detail": "unavailable"}),
    )
    page.route(
        re.compile(r".*/api/jobs\?.*"),
        lambda route: route_json(route, 200, [fallback_job]),
    )
    page.goto(f"{base}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector('select[name="job_function"]')
    values = page.locator(
        '[data-form="job-filter"] select[name="job_function"] option'
    ).all_inner_texts()
    expect(
        values == ["全部", *BUILTIN_FUNCTIONS],
        "wordlist fallback did not use built-in functions",
    )
    page.close()


def test_pending_reclassify(context, errors, base: str) -> None:
    pending = {
        "job_id": "phase16-pending",
        "title": "Phase16 待分类岗位",
        "company": "Acme",
        "location": "北京",
        "salary_min": 20000,
        "salary_max": 30000,
        "salary_currency": "CNY",
        "job_function": None,
        "seniority": None,
        "status": "已投递",
        "tech_tags": [],
        "jd_text": "Python backend",
        "classification_pending": 1,
    }
    page = new_page(context, errors)

    def handle_jobs(route):
        jobs = [dict(pending)]
        if not pending["classification_pending"]:
            jobs = [dict(pending)]
        route_json(route, 200, jobs)

    page.route(
        re.compile(r".*/api/jobs\?.*"), handle_jobs
    )
    page.route(
        re.compile(r".*/api/jobs/phase16-pending/reclassify$"),
        lambda route: route_json(route, 200, pending),
    )
    page.goto(f"{base}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector("text=Phase16 待分类岗位")
    expect(
        page.locator(".badge-pending").count() == 1,
        "classification pending badge missing",
    )
    expect(
        page.locator('[data-action="reclassify-job"]').count() == 1,
        "reclassify button missing",
    )
    pending.update({
        "job_function": "架构",
        "seniority": "首席",
        "tech_tags": ["Python"],
        "classification_pending": 0,
    })
    page.click('[data-action="reclassify-job"]')
    page.wait_for_selector(".badge-pending", state="detached")
    expect(
        page.locator(".card", has_text="架构").count() >= 1,
        "reclassify did not refresh the card",
    )
    page.close()


def test_workbench_final_draft(
    context, errors, base: str, resume_id: str, job_id: str
) -> str:
    page = new_page(context, errors)
    page.goto(
        f"{base}/#/workspace/{job_id}", wait_until="domcontentloaded"
    )
    page.wait_for_selector(f"text={JOB_TITLE}")
    page.select_option(
        '[data-form="wb-run"] select[name="master_resume_id"]',
        resume_id,
    )
    page.click('[data-wb-run]')
    page.wait_for_selector(
        "[data-wb-progress-panel]:not([hidden])", timeout=2000
    )
    page.wait_for_selector(".cmp-grid", timeout=30000)
    expect(
        page.locator(".opt-badge").count() >= 1,
        "optimized badges missing",
    )
    expect(
        page.locator('[data-accept-diff]').count() >= 1,
        "accept controls missing",
    )
    page.locator(".opt-badge").first.click()
    expect(
        page.locator(".opt-bubble:visible").count() >= 1,
        "optimized reason bubble did not open",
    )
    page.screenshot(
        path=str(SHOTS / "phase16-workbench-diff.png"), full_page=True
    )
    page.click('[data-action="accept-diffs"]')
    page.wait_for_selector("[data-accept-result] .drawer")
    page.click('[data-action="save-final-draft"]')
    page.wait_for_selector(
        "[data-final-draft-panel]:not([hidden])"
    )
    expect(
        "已保存" in page.locator(
            "[data-final-draft-panel]"
        ).inner_text(),
        "final draft saved badge missing",
    )
    expect(
        "第 1 版" in page.locator(
            "[data-final-draft-panel]"
        ).inner_text(),
        "final draft version missing",
    )

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector(
        "[data-final-draft-panel]:not([hidden])"
    )
    expect(
        "第 1 版" in page.locator(
            "[data-final-draft-panel]"
        ).inner_text(),
        "final draft did not restore after refresh",
    )
    page.wait_for_selector(".benchmark-source")
    source_text = page.locator(".benchmark-source").inner_text()
    expect(
        "设置表（北京）" in source_text,
        "settings benchmark source missing",
    )
    expect(
        "城市归一化：北京" in source_text,
        "normalized city missing",
    )

    page.click('[data-action="export-final-draft"]')
    page.wait_for_selector(
        "#print-root [data-final-draft-panel]",
        state="attached",
    )
    expect(
        page.locator("#print-root button").count() == 0,
        "final draft print root contains buttons",
    )
    page.pdf(
        path=str(SHOTS / "phase16-final-draft.pdf"), format="A4"
    )
    expect(
        (SHOTS / "phase16-final-draft.pdf").stat().st_size > 1000,
        "final draft PDF is empty",
    )
    page.click('[data-action="print-workbench"]')
    page.wait_for_selector(
        "#print-root .cmp-grid", state="attached"
    )
    expect(
        page.locator("#print-root .opt-badge").count() >= 1,
        "workbench print root missing badges",
    )
    page.pdf(
        path=str(SHOTS / "phase16-workbench.pdf"), format="A4"
    )
    expect(
        (SHOTS / "phase16-workbench.pdf").stat().st_size > 1000,
        "workbench PDF is empty",
    )

    page.click('[data-action="save-as-new-resume"]')
    page.wait_for_selector(".modal")
    expect(
        "不会改动当前主简历" in page.locator(".modal").inner_text(),
        "save-as confirmation text missing",
    )
    page.click('[data-action="close-modal"]')
    expect(
        page.locator(".modal").count() == 0,
        "modal did not close on cancel",
    )
    page.click('[data-action="save-as-new-resume"]')
    page.wait_for_selector(".modal")
    page.click('[data-action="confirm-save-as"]')
    page.wait_for_url(re.compile(r".*/#/resume/.+"))
    page.wait_for_selector(".resume-doc")
    new_resume_id = page.url.split("/resume/")[-1]
    original = api_call(
        base, "GET", f"/api/master-resumes/{resume_id}"
    )
    expect(
        original["content"] == RESUME_CONTENT,
        "save-as mutated the original resume",
    )
    page.screenshot(
        path=str(SHOTS / "phase16-save-as-resume.png"), full_page=True
    )
    page.close()
    return new_resume_id


def test_mobile(
    context, errors, base: str, resume_id: str, job_id: str
) -> None:
    page = new_page(context, errors)
    page.goto(f"{base}/#/resume", wait_until="domcontentloaded")
    page.wait_for_selector("text=简历中心")
    assert_no_overflow(page, "mobile resume center")
    page.screenshot(path=str(SHOTS / "phase16-mobile-resume.png"))

    page.goto(
        f"{base}/#/resume/{resume_id}", wait_until="domcontentloaded"
    )
    page.wait_for_selector(".resume-doc")
    assert_no_overflow(page, "mobile resume archive")

    page.goto(
        f"{base}/#/workspace/{job_id}", wait_until="domcontentloaded"
    )
    page.wait_for_selector(
        "[data-final-draft-panel]:not([hidden])"
    )
    assert_no_overflow(page, "mobile workspace")
    page.screenshot(path=str(SHOTS / "phase16-mobile-workspace.png"))
    page.close()


def main() -> None:
    errors = {"console": [], "page": []}
    llm = LLMServer()
    llm.start()
    app = AppServer(llm)
    app.start()
    base = app.base_url
    original_settings = None
    created_resume_ids: list[str] = []
    created_job_ids: list[str] = []
    try:
        original_settings = api_call(base, "GET", "/api/settings")
        resume = api_call(
            base,
            "POST",
            "/api/master-resumes",
            {
                "title": RESUME_TITLE,
                "content": RESUME_CONTENT,
            },
        )
        created_resume_ids.append(resume["resume_id"])
        job = api_call(
            base,
            "POST",
            "/api/jobs",
            {
                "title": JOB_TITLE,
                "jd_text": JOB_JD,
                "company": "Acme",
                "location": "北京朝阳区",
                "salary_min": 25000,
                "salary_max": 35000,
                "salary_currency": "CNY",
            },
        )
        created_job_ids.append(job["job_id"])
        expect(
            job["classification_pending"] == 0,
            "real classification did not succeed",
        )
        api_call(
            base,
            "PUT",
            "/api/settings",
            {
                "salary_reference": [{
                    "job_function": "后端",
                    "city": "北京市",
                    "p50": 30000,
                    "p75": 45000,
                }]
            },
        )

        SHOTS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900}
                )
                test_no_login_wall(context, errors, base)
                test_resume_archive_and_diagnosis(
                    context, errors, base, resume["resume_id"]
                )
                test_jd_parse_flows(context, errors, base)
                test_wordlist_sync(context, errors, base)
                test_pending_reclassify(context, errors, base)
                new_resume_id = test_workbench_final_draft(
                    context,
                    errors,
                    base,
                    resume["resume_id"],
                    job["job_id"],
                )
                created_resume_ids.append(new_resume_id)
                mobile = browser.new_context(
                    viewport={"width": 390, "height": 844},
                    is_mobile=True,
                )
                test_mobile(
                    mobile,
                    errors,
                    base,
                    resume["resume_id"],
                    job["job_id"],
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
    finally:
        if original_settings is not None:
            try:
                api_call(
                    base, "PUT", "/api/settings", original_settings
                )
            except Exception:
                pass
        for job_id in created_job_ids:
            try:
                api_call(base, "DELETE", f"/api/jobs/{job_id}")
            except Exception:
                pass
        for resume_id in created_resume_ids:
            try:
                api_call(
                    base, "DELETE",
                    f"/api/master-resumes/{resume_id}"
                )
            except Exception:
                pass
        app.stop()
        llm.stop()
    print("PHASE16 SMOKE OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PHASE16 SMOKE FAILED: {exc}", file=sys.stderr)
        raise
