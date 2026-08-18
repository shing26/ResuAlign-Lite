"""Dogfood QA harness for ResuAlign (see docs/agents/qa-dogfooder.md).

Starts the fake LLM and the real app on isolated temp DB + random ports,
then drives the UI with Playwright across the five QA dimensions. Writes
findings JSON and screenshots into ``.scratch/qa/``.
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
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
PHASE20 = ROOT / ".scratch" / "phase-20"
ARTIFACTS = ROOT / ".scratch" / "qa"

FINDINGS: list[dict] = []
CONSOLE_MESSAGES: list[str] = []


def record(
    severity: str,
    category: str,
    title: str,
    actual: str,
    expected: str,
    repro: list[str],
    clue: str = "",
    evidence: str = "",
) -> None:
    FINDINGS.append(
        {
            "severity": severity,
            "category": category,
            "title": title,
            "actual": actual,
            "expected": expected,
            "repro": repro,
            "clue": clue,
            "evidence": evidence,
        }
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_health(base_url: str, proc: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early:\n{log_path.read_text(errors='replace')}")
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=1).read()
            return
        except urllib.error.URLError:
            time.sleep(0.2)
    raise RuntimeError(f"{base_url} did not become healthy in time")


class Server:
    def __init__(self, prefix: str = "resualign-qa-") -> None:
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
        for handle in (self.out_file, self.err_file):
            if handle:
                handle.close()
        self.tmp.cleanup()


class FakeLLMServer(Server):
    def start(self) -> None:
        super().start(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "fake_llm:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--app-dir",
                str(PHASE20),
            ],
            env=os.environ.copy(),
        )


class AppServer(Server):
    def __init__(self, llm: FakeLLMServer) -> None:
        super().__init__(prefix="resualign-qa-app-")
        self.llm = llm
        self.db_path = self.tmp_path / "jobs.db"

    def start(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "LLM_PROVIDER": "deepseek",
                "DEEPSEEK_API_KEY": "qa-smoke-key",
                "DEEPSEEK_MODEL": "qa-smoke-model",
                "DEEPSEEK_BASE_URL": f"{self.llm.base_url}/v1",
                "RESUALIGN_PERSONAL_MODE": "1",
                "RESUALIGN_JOB_DB": str(self.db_path),
                "RESUALIGN_HOST": "127.0.0.1",
                "RESUALIGN_PORT": str(self.port),
                "PYTHONPATH": str(SRC),
            }
        )
        super().start(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "resualign.api:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--app-dir",
                str(SRC),
            ],
            env=env,
        )


def api_call(base_url: str, method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
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


class Runner:
    def __init__(
        self,
        base_url: str,
        *,
        app_tmp_path: Path | None = None,
        app_port: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.app_tmp_path = app_tmp_path
        self.app_port = app_port
        self.artifacts = ARTIFACTS
        self.artifacts.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def new_page(context):
        errors = {"all": [], "console": [], "page": [], "failed": []}

        def on_console(message) -> None:
            text = message.text
            errors["all"].append(text)
            CONSOLE_MESSAGES.append(f"[{message.type}] {text}")
            if message.type == "error":
                errors["console"].append(text)

        def on_pageerror(exc) -> None:
            errors["page"].append(str(exc))
            CONSOLE_MESSAGES.append(f"[pageerror] {exc}")

        def on_requestfailed(request) -> None:
            line = f"{request.method} {request.url} -> {request.failure}"
            errors["failed"].append(line)
            CONSOLE_MESSAGES.append(f"[requestfailed] {line}")

        def on_response(response) -> None:
            if response.status >= 400:
                CONSOLE_MESSAGES.append(
                    f"[http{response.status}] {response.request.method} "
                    f"{response.url}"
                )

        page = context.new_page()
        page.on("console", on_console)
        page.on("pageerror", on_pageerror)
        page.on("requestfailed", on_requestfailed)
        page.on("response", on_response)
        page._qa_errors = errors  # noqa: SLF001 - harness-private wiring
        return page

    @staticmethod
    def errors(page) -> dict:
        return page._qa_errors

    def wait_view(self, page, timeout: float = 20.0) -> None:
        page.wait_for_function(
            """() => {
                const view = document.querySelector('#app-router-view');
                if (!view) return false;
                const text = view.textContent || '';
                return text.trim().length > 0
                    && !view.querySelector('.skeleton')
                    && !view.innerHTML.includes('加载中...');
            }""",
            timeout=timeout * 1000,
        )

    def goto(self, page, route: str, wait: bool = True) -> None:
        page.goto(f"{self.base_url}/{route}", wait_until="domcontentloaded")
        if wait:
            # Hash-only SPA navigation may resolve before the route handler
            # runs; wait for the requested route (or its auto-redirect prefix)
            # to actually land in location.hash first.
            page.wait_for_function(
                """(expected) => {
                    const hash = location.hash;
                    return hash === expected || hash.startsWith(expected);
                }""",
                arg=route,
                timeout=10000,
            )
            self.wait_view(page)

    def overflow_scan(self, page, label: str) -> list[str]:
        hits = page.evaluate(
            """() => {
                const vw = document.documentElement.clientWidth;
                const hits = [];
                const insideScrollable = (el) => {
                    let p = el.parentElement;
                    while (p) {
                        const s = getComputedStyle(p);
                        const x = s.overflowX;
                        if ((x === 'auto' || x === 'scroll')
                                && p.scrollWidth > p.clientWidth + 2) {
                            return true;
                        }
                        p = p.parentElement;
                    }
                    return false;
                };
                document.querySelectorAll('body *').forEach((el) => {
                    const s = getComputedStyle(el);
                    if (s.display === 'none' || s.visibility === 'hidden') return;
                    if (el.closest('[hidden]')) return;
                    if (insideScrollable(el)) return;
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && (r.right > vw + 2 || r.left < -2)) {
                        const cls = String(el.className || '')
                            .split(' ').slice(0, 3).join('.');
                        hits.push(el.tagName.toLowerCase() + '.' + cls
                            + ' right=' + Math.round(r.right));
                    }
                });
                return hits.slice(0, 10);
            }"""
        )
        doc_overflow = page.evaluate(
            "document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"
        )
        if doc_overflow:
            record(
                "P2",
                "视觉适配",
                f"{label} 页面级横向溢出",
                "documentElement.scrollWidth 超出视口",
                "页面本身不应出现横向滚动",
                [f"访问 {label}"],
                clue="检查 body/app-shell 布局",
                evidence=label,
            )
        if hits:
            record(
                "P3",
                "视觉适配",
                f"{label} 存在横向溢出元素",
                "可见元素超出视口右边界: " + ", ".join(hits),
                "所有可见元素都应保持在视口内",
                [f"访问 {label}", "执行 overflow_scan"],
                clue="检查相关容器宽度/flex 布局",
                evidence=label,
            )
        return hits

    def screenshot(self, page, name: str) -> None:
        try:
            page.screenshot(path=str(self.artifacts / f"{name}.png"))
        except Exception as exc:  # noqa: BLE001 - screenshot must not kill QA
            print("screenshot failed:", name, exc)

    def check_console(self, page, label: str) -> None:
        errors = self.errors(page)
        severe = [
            e
            for e in errors["console"]
            if "favicon" not in e.lower() and "failed to load resource" not in e.lower()
        ]
        if errors["page"]:
            record(
                "P1",
                "性能与控制台",
                f"{label} 页面异常",
                "; ".join(errors["page"]),
                "页面不应抛出未捕获异常",
                [f"访问 {label}"],
                clue="pageerror 来自前端未捕获异常",
                evidence=label,
            )
        if severe:
            record(
                "P2",
                "性能与控制台",
                f"{label} 控制台错误",
                "; ".join(severe),
                "控制台不应出现错误级别日志",
                [f"访问 {label}"],
                clue="console.error / 资源失败",
                evidence=label,
            )

    def check_routes(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            routes = [
                ("dashboard", "#/dashboard"),
                ("jobs", "#/jobs"),
                ("resume", "#/resume"),
                ("settings", "#/settings"),
                ("today", "#/today"),
                ("workspace-empty", "#/workspace"),
                ("unknown-route", "#/does-not-exist"),
            ]
            for label, route in routes:
                try:
                    self.goto(page, route)
                    page.wait_for_timeout(400)
                    self.check_console(page, label)
                    self.overflow_scan(page, f"desktop-{label}")
                    self.screenshot(page, f"desktop-{label}")
                except PlaywrightTimeoutError:
                    record(
                        "P2",
                        "功能缺陷",
                        f"路由 {route} 加载超时",
                        "视图未在 20s 内渲染",
                        "路由应正常渲染视图",
                        [f"访问 {route}"],
                        clue="handleRoute 或视图渲染卡住",
                        evidence=label,
                    )
        finally:
            context.close()

    def check_empty_states(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            self.goto(page, "#/resume")
            text = page.locator("#app-router-view").inner_text()
            if "新建主简历" not in text and "上传简历文件" not in text:
                record(
                    "P2",
                    "交互反馈",
                    "简历中心空状态缺失",
                    "空库时没有新建/上传引导",
                    "应展示新建主简历与上传入口",
                    ["清空数据后访问 #/resume"],
                    clue="resume-center.js 空状态分支",
                )
            self.goto(page, "#/jobs")
            if "暂无岗位" not in page.locator("#job-board").inner_text():
                record(
                    "P3",
                    "交互反馈",
                    "岗位库空状态文案缺失",
                    "空库看板没有'暂无岗位'提示",
                    "每列应有空状态占位",
                    ["清空数据后访问 #/jobs"],
                    clue="kanban.js board-column__empty",
                )
        finally:
            context.close()

    def check_resume_flow(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            self.goto(page, "#/resume")
            page.click('[data-action="new-resume"]')
            form = page.locator('[data-form="resume-create"]')
            form.wait_for(timeout=10000)
            form.locator('input[name="title"]').fill("QA 主简历")
            form.locator('textarea[name="content"]').fill(
                "QA 主简历\n\n工作经历\n- 使用 Python 开发后端服务\n"
                "- 使用 Redis 缓存\n- 负责高并发接口优化\n"
            )
            form.locator('button[type="submit"]').click()
            page.wait_for_selector('[data-action="edit-resume"]', timeout=15000)
            page.wait_for_timeout(300)
            self.check_console(page, "resume-create")

            # 刷新后持久化检查
            page.reload(wait_until="domcontentloaded")
            self.wait_view(page)
            if page.locator('[data-action="edit-resume"]').count() == 0:
                record(
                    "P1",
                    "状态同步",
                    "新建简历刷新后丢失",
                    "F5 后简历卡片消失",
                    "刷新后应保留简历",
                    ["新建简历", "F5 刷新"],
                    clue="创建后未写入 store 或列表未从 API 拉取",
                )

            # 诊断（fake LLM）
            page.click('[data-action="diagnose-resume"]')
            try:
                page.wait_for_function(
                    """() => {
                        const node = document.querySelector(
                            '[data-resume-band-status-text]'
                        );
                        return node && /\\d+ 分/.test(node.textContent || '');
                    }""",
                    timeout=30000,
                )
                self.check_console(page, "resume-diagnose")
            except PlaywrightTimeoutError:
                record(
                    "P1",
                    "功能缺陷",
                    "简历诊断未完成",
                    "诊断任务没有进入完成态",
                    "应展示诊断分数",
                    ["点击诊断简历", "等待任务完成"],
                    clue="检查 diagnosis API / 轮询逻辑",
                )
        finally:
            context.close()

    def check_job_and_workbench(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        tag = f"qa-{int(time.time())}"
        jd_text = (
            f"招聘 Python 后端工程师（{tag}），负责高并发服务端开发，"
            "要求熟悉 FastAPI 异步接口与 Redis 缓存。"
            "任职要求：5 年以上后端经验，能支撑百万级请求。"
        )
        try:
            self.goto(page, "#/jobs")
            page.click('[data-action="open-command-panel"]')
            page.fill('[data-command-input]', jd_text)
            page.wait_for_function(
                "() => !document.querySelector('[data-command-confirm]').disabled",
                timeout=10000,
            )
            session_404s: list[str] = []

            def on_session_response(response) -> None:
                if (
                    "/api/workspace/session/" in response.url
                    and response.status >= 400
                ):
                    session_404s.append(f"{response.status} {response.url}")

            page.on("response", on_session_response)
            page.click('[data-command-confirm]')
            page.wait_for_function(
                "() => location.hash.startsWith('#/workspace/')",
                timeout=15000,
            )

            job_id = None
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                jobs = api_call(self.base_url, "GET", "/api/jobs?limit=100")
                for job in jobs:
                    if tag in (job.get("jd_text") or ""):
                        job_id = job["job_id"]
                        break
                if job_id:
                    break
                time.sleep(0.3)
            if not job_id:
                record(
                    "P1",
                    "功能缺陷",
                    "命令面板粘贴 JD 未创建岗位",
                    "等待 30s 未在岗位库找到该 JD",
                    "粘贴 JD 应创建岗位并进入工作台",
                    ["打开命令面板", "粘贴 JD", "点击确认"],
                    clue="检查 /api/workbench/session/init 与 /api/jobs",
                )
                return

            current_hash = page.evaluate("location.hash")
            expected_hash = f"#/workspace/{job_id}"
            if not current_hash.startswith(expected_hash):
                record(
                    "P2",
                    "状态同步",
                    "命令面板深链仍跳转 session_id",
                    f"hash={current_hash!r}, 期望以 {expected_hash!r} 开头",
                    "确认 JD 后应跳转可长期有效的岗位深链",
                    ["打开命令面板", "粘贴 JD", "点击确认"],
                    clue="main.js command-panel 分支应优先使用 session.job.job_id",
                    evidence="; ".join(session_404s),
                )
            if session_404s:
                record(
                    "P2",
                    "性能与控制台",
                    "命令面板深链产生 workspace/session 4xx",
                    "; ".join(session_404s),
                    "跳转岗位工作台不应请求错误的 session 路由",
                    ["打开命令面板", "粘贴 JD", "点击确认"],
                    clue="loadSession 对 session_id 的兜底查询",
                    evidence="; ".join(session_404s),
                )

            # 回到岗位库，卡片应出现
            self.goto(page, "#/jobs")
            page.wait_for_selector("#job-board", timeout=10000)
            card = page.locator(f'[data-job-id="{job_id}"]')
            try:
                card.wait_for(timeout=15000)
            except PlaywrightTimeoutError:
                jobs = api_call(self.base_url, "GET", "/api/jobs?limit=500")
                (self.artifacts / "debug-jobs.json").write_text(
                    json.dumps(jobs, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (self.artifacts / "debug-job-board.html").write_text(
                    page.content(), encoding="utf-8"
                )
                errs = self.errors(page)
                record(
                    "P2",
                    "状态同步",
                    "新岗位未出现在看板",
                    "创建后看板找不到岗位卡片",
                    "岗位应出现在岗位库",
                    ["粘贴 JD 创建岗位", "回到 #/jobs"],
                    clue="检查 kanban 渲染与状态刷新",
                    evidence=(
                        f"jobs={len(jobs)} console={errs['console'][:3]} "
                        "page_errors=" + ";".join(errs["page"])
                    ),
                )
                return

            # 工作台对齐
            page.goto(
                f"{self.base_url}/#/workspace/{job_id}",
                wait_until="domcontentloaded",
            )
            self.wait_view(page)
            resume_select = page.locator(
                "[data-form='split-align'] [name='master_resume_id']"
            )
            try:
                resume_select.wait_for(timeout=15000)
                resumes = api_call(self.base_url, "GET", "/api/master-resumes")
                if not resumes:
                    record(
                        "P2",
                        "功能缺陷",
                        "工作台没有可用主简历",
                        "已创建简历但工作台 resume 下拉为空",
                        "工作台应展示主简历选项",
                        ["打开岗位工作台"],
                        clue="检查 master-resumes 数据流",
                    )
                    return
                page.select_option(
                    "[data-form='split-align'] [name='master_resume_id']",
                    resumes[0]["resume_id"],
                )
            except PlaywrightTimeoutError:
                record(
                    "P2",
                    "功能缺陷",
                    "工作台缺少主简历选择器",
                    "工作台未渲染 split-align 表单",
                    "应能选择主简历并发起对齐",
                    ["打开岗位工作台"],
                    clue="检查 split-canvas 渲染条件",
                )
                return

            run_button = page.locator('[data-align-run]')
            run_button.wait_for(timeout=15000)
            run_button.click()

            try:
                page.wait_for_selector(
                    "[data-diff-list] .diff-card", timeout=60000
                )
                page.wait_for_timeout(400)
                page.locator('[data-action="accept-bullet"]').first.click()
                page.wait_for_timeout(800)
                self.check_console(page, "workbench-align")

                # 已采纳状态应持久化：F5 后计数与标记不丢
                page.reload(wait_until="domcontentloaded")
                self.wait_view(page)
                page.wait_for_selector("[data-diff-list] .diff-card", timeout=30000)
                page.wait_for_timeout(500)
                adopted = page.locator(".adopted[disabled]")
                reloaded_status = (
                    page.locator(".status-line").first.inner_text()
                    if page.locator(".status-line").count()
                    else ""
                )
                if adopted.count() == 0 or "已采纳" not in reloaded_status:
                    record(
                        "P1",
                        "状态同步",
                        "已采纳状态刷新后丢失",
                        f"F5 后 adopted={adopted.count()}, status={reloaded_status!r}",
                        "刷新后应保留已采纳标记与计数",
                        ["对齐完成", "采纳 1 条建议", "F5 刷新"],
                        clue="save_final_draft 应持久化 accepted_diff_ids 到 diffs_json",
                    )

                # 对齐结果应持久化到岗位库（dashboard 快速继续会刻意
                # 优先展示“未对齐”岗位，因此用 API 直接校验岗位状态）
                aligned_job = api_call(
                    self.base_url, "GET", f"/api/jobs/{job_id}"
                )
                if aligned_job.get("alignment_status") != "succeeded":
                    record(
                        "P1",
                        "状态同步",
                        "对齐状态未持久化到岗位库",
                        f"alignment_status={aligned_job.get('alignment_status')!r}",
                        "对齐完成后岗位应标记为 succeeded",
                        ["运行对齐", "等待 diff 产出"],
                        clue="save_alignment 的 alignment_status 写入路径",
                    )

                # 驾驶舱快速继续状态应为中文
                self.goto(page, "#/dashboard")
                quick = page.locator("[data-quick-continue]")
                if quick.count():
                    quick_text = quick.first.inner_text()
                    english_statuses = (
                        "succeeded",
                        "running",
                        "queued",
                        "failed",
                        "idle",
                    )
                    if any(token in quick_text for token in english_statuses):
                        record(
                            "P3",
                            "交互反馈",
                            "驾驶舱快速继续状态暴露英文状态值",
                            f"quick-continue 文案: {quick_text!r}",
                            "应使用 alignmentStatusLabel 的中文映射",
                            ["对齐成功后访问 #/dashboard"],
                            clue="dashboard-view.js alignmentStatusLabel 覆盖",
                        )
            except PlaywrightTimeoutError:
                (self.artifacts / "debug-workbench.html").write_text(
                    page.content(), encoding="utf-8"
                )
                errs = self.errors(page)
                record(
                    "P1",
                    "功能缺陷",
                    "工作台对齐未产出 Diff",
                    "60s 内未渲染任何 diff 卡片",
                    "对齐完成后应展示 Diff 与采纳按钮",
                    ["打开岗位工作台", "点击开始对齐", "等待完成"],
                    clue="检查 alignment 轮询/SSE 与 diff 渲染",
                    evidence=(
                        "console=" + ";".join(errs["console"][:3])
                        + " page_errors=" + ";".join(errs["page"])
                    ),
                )
        finally:
            context.close()

    def check_deterministic_job_fields(self) -> None:
        """API 级探针：公司/城市提取、标题推导的旧报告回归点。"""
        cases = [
            {
                "jd_text": (
                    "公司：星河科技\n地点：上海\n"
                    "【测试岗位】高级数据分析师\n职责：负责数据分析与报表。"
                ),
                "company": "星河科技",
                "location": "上海",
                "title_keyword": "数据",
                "title_bad": "测试岗位】",
            },
            {
                "jd_text": (
                    "【招聘】高薪诚聘\n资深后端工程师\n"
                    "职责：负责高并发服务端开发。"
                ),
                "company": None,
                "location": None,
                "title_keyword": "后端",
                "title_bad": "未命名岗位",
            },
            {
                "jd_text": (
                    "Python 后端工程师，负责高并发服务端开发，"
                    "要求熟悉 FastAPI 与 Redis。"
                ),
                "company": None,
                "location": None,
                "title_keyword": "后端",
                "title_bad": "未命名岗位",
            },
        ]
        for index, case in enumerate(cases, 1):
            job = api_call(
                self.base_url,
                "POST",
                "/api/jobs",
                {"jd_text": case["jd_text"]},
            )
            title = job.get("title") or ""
            if case["company"] and job.get("company") != case["company"]:
                record(
                    "P2",
                    "功能缺陷",
                    "JD 公司字段未提取",
                    f"case{index} company={job.get('company')!r}",
                    f"应从 JD 提取公司 {case['company']!r}",
                    ["POST /api/jobs 传入带公司标签的 JD"],
                    clue="services/jobs.py _extract_company_location",
                )
            if case["location"] and job.get("location") != case["location"]:
                record(
                    "P2",
                    "功能缺陷",
                    "JD 城市字段未提取",
                    f"case{index} location={job.get('location')!r}",
                    f"应从 JD 提取城市 {case['location']!r}",
                    ["POST /api/jobs 传入带地点标签的 JD"],
                    clue="services/jobs.py _extract_company_location",
                )
            if case["title_keyword"] and case["title_keyword"] not in title:
                record(
                    "P2",
                    "功能缺陷",
                    "JD 标题推导不准确",
                    f"case{index} title={title!r}",
                    f"标题应包含 {case['title_keyword']!r}",
                    ["POST /api/jobs 传入无 title 的 JD"],
                    clue="services/jobs.py _derive_title",
                )
            if case["title_bad"] and case["title_bad"] in title:
                record(
                    "P2",
                    "功能缺陷",
                    "JD 标题推导残留噪声",
                    f"case{index} title={title!r}",
                    f"标题不应包含 {case['title_bad']!r}",
                    ["POST /api/jobs 传入含噪声前缀的 JD"],
                clue="services/jobs.py _clean_title_candidate",
                )

    def check_match_score_sort(self, browser) -> None:
        """MVP-07: jobs board consumes match_score and sorts by it."""
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        tag = f"qa-match-{int(time.time())}"
        try:
            resume = api_call(
                self.base_url,
                "POST",
                "/api/master-resumes",
                {
                    "title": "QA 匹配主简历",
                    "content": (
                        "QA 匹配主简历\n\n"
                        "- 使用 Python 与 FastAPI 开发高并发后端服务\n"
                        "- 使用 Redis 缓存热点数据\n"
                    ),
                },
            )
            created: list[str] = []
            for name, score_jd in (
                ("高匹配", f"后端工程师（{tag}-a），要求 Python、FastAPI、Redis。"),
                ("低匹配", f"前端设计师（{tag}-b），要求 Figma、Sketch。"),
            ):
                job = api_call(
                    self.base_url,
                    "POST",
                    "/api/jobs",
                    {"title": name, "jd_text": score_jd},
                )
                created.append(job["job_id"])
                api_call(
                    self.base_url,
                    "POST",
                    f"/api/jobs/{job['job_id']}/workbench",
                    {
                        "master_resume_id": resume["resume_id"],
                        "run_eval": False,
                    },
                )
            deadline = time.monotonic() + 90
            tagged: list[dict] = []
            while time.monotonic() < deadline:
                jobs = api_call(self.base_url, "GET", "/api/jobs?limit=500")
                tagged = [j for j in jobs if tag in (j.get("jd_text") or "")]
                if (
                    len(tagged) == len(created)
                    and all(j.get("match_score") is not None for j in tagged)
                ):
                    break
                time.sleep(0.5)
            if len(tagged) != len(created) or any(
                j.get("match_score") is None for j in tagged
            ):
                record(
                    "P2",
                    "功能缺陷",
                    "岗位匹配分未落库",
                    f"tagged={[(j['title'], j.get('match_score')) for j in tagged]}",
                    "MVP-01 后岗位应带 match_score",
                    ["创建岗位", "选择主简历", "运行对齐", "等待评分"],
                    clue="检查 match scorer 是否在 workbench 后写入",
                )
                return
            self.goto(page, "#/jobs")
            page.wait_for_selector("#job-board", timeout=10000)
            select = page.locator("[data-job-sort]")
            select.wait_for(timeout=10000)
            sort_option = select.locator('option[value="match_score_desc"]')
            if sort_option.count() == 0:
                record(
                    "P2",
                    "交互反馈",
                    "岗位库排序控件缺失",
                    "没有匹配分排序选项",
                    "应提供匹配分排序选项",
                    ["访问 #/jobs"],
                    clue="kanban.js data-job-sort 渲染",
                )
            else:
                if "匹配分从高到低" not in sort_option.first.inner_text():
                    record(
                        "P2",
                        "交互反馈",
                        "岗位库排序文案缺失",
                        f"option={sort_option.first.inner_text()!r}",
                        "应显示匹配分从高到低选项",
                        ["访问 #/jobs"],
                        clue="kanban.js data-job-sort 渲染",
                    )
                select.select_option("match_score_desc")
                page.wait_for_timeout(1200)
            for job in tagged:
                card = page.locator(f'[data-job-id="{job["job_id"]}"]')
                try:
                    card.wait_for(timeout=10000)
                except PlaywrightTimeoutError:
                    record(
                        "P2",
                        "状态同步",
                        "评分岗位未出现在看板",
                        f"job_id={job['job_id']}",
                        "有匹配分的岗位应显示在看板",
                        ["访问 #/jobs"],
                        clue="kanban 渲染",
                    )
                    continue
                total = card.locator("[data-match-total]")
                if total.count() == 0 or "待分析" in total.first.inner_text():
                    record(
                        "P2",
                        "功能缺陷",
                        "看板未展示岗位匹配分",
                        f"title={job.get('title')!r} "
                        f"total={total.first.inner_text() if total.count() else 'missing'}",
                        "岗位卡片应显示匹配分",
                        ["访问 #/jobs"],
                        clue="format.js boardCard match block",
                    )
                dims = card.locator("[data-match-dimension]")
                if dims.count() != 4:
                    record(
                        "P2",
                        "功能缺陷",
                        "看板匹配分缺少四维明细",
                        f"title={job.get('title')!r} dims={dims.count()}",
                        "岗位卡片应展示四个维度",
                        ["访问 #/jobs"],
                        clue="format.js matchDimensionHtml",
                    )
            high = max(tagged, key=lambda job: job.get("match_score") or 0)
            low = min(tagged, key=lambda job: job.get("match_score") or 0)
            if high.get("match_score") != low.get("match_score"):
                high_before_low = page.evaluate(
                    """(ids) => {
                        const high = document.querySelector(
                            `[data-job-id="${ids[0]}"]`
                        );
                        const low = document.querySelector(
                            `[data-job-id="${ids[1]}"]`
                        );
                        if (!high || !low) return null;
                        return Boolean(
                            high.compareDocumentPosition(low) &
                            Node.DOCUMENT_POSITION_FOLLOWING
                        );
                    }""",
                    [high["job_id"], low["job_id"]],
                )
                if high_before_low is not True:
                    record(
                        "P2",
                        "功能缺陷",
                        "匹配分排序顺序错误",
                        f"high_before_low={high_before_low!r}",
                        "高匹配岗位应排在低匹配岗位之前",
                        ["访问 #/jobs", "选择匹配分从高到低"],
                        clue="job_library list_jobs sort 与 kanban 分组",
                    )
            self.check_console(page, "jobs-match-sort")
        finally:
            context.close()

    def check_today_view(self, browser) -> None:
        """MVP-08: #/today renders reminders (or a clean empty state)."""
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            self.goto(page, "#/today")
            text = page.locator("#app-router-view").inner_text()
            self.check_console(page, "today-view")
            if "今日待办" not in text:
                record(
                    "P2",
                    "功能缺陷",
                    "今日待办视图未渲染",
                    f"view text={text[:80]!r}",
                    "#/today 应显示今日待办视图",
                    ["访问 #/today"],
                    clue="main.js today 路由 / todayViewHtml",
                )
        finally:
            context.close()

    def check_export_final_draft(self, browser) -> None:
        """MVP-09: workbench final exports come from the canonical API."""
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            job = api_call(
                self.base_url,
                "POST",
                "/api/jobs",
                {
                    "title": "QA 导出",
                    "jd_text": "后端工程师，要求 Python、FastAPI、Redis。",
                },
            )
            api_call(
                self.base_url,
                "POST",
                f"/api/jobs/{job['job_id']}/final-draft",
                {
                    "draft": "# QA 定稿\n\n- Python 后端\n",
                    "accepted_diff_ids": [],
                },
            )
            self.goto(page, f"#/workspace/{job['job_id']}")
            dock = page.locator("[data-export-dock]")
            dock.wait_for(timeout=15000)
            if not dock.get_attribute("open"):
                dock.locator("summary").click()
                dock.locator('[data-action="export-final-draft-md"]').wait_for(
                    state="visible",
                    timeout=10000,
                )
            if not dock.locator("[data-export-final-badge]").count():
                record(
                    "P2",
                    "状态同步",
                    "工作台导出菜单未识别定稿",
                    "有 final_draft 但菜单没有已定稿徽章",
                    "定稿后应显示 vN 并可导出",
                    ["保存定稿", "打开工作台"],
                    clue="exportDock 从持久化 job 字段取状态",
                )
            for action in (
                "export-final-draft",
                "export-final-draft-md",
                "export-final-draft-json",
            ):
                if not dock.locator(f'[data-action="{action}"]').count():
                    record(
                        "P2",
                        "功能缺陷",
                        f"导出菜单缺少 {action}",
                        "定稿后菜单未渲染该导出动作",
                        "三个 final 导出动作都应可用",
                        ["保存定稿", "打开工作台导出菜单"],
                        clue="format.js exportDock",
                    )
            panel = page.locator("[data-final-draft-panel]")
            if panel.count() and not panel.locator(
                '[data-action="export-final-draft-json"]'
            ).count():
                record(
                    "P2",
                    "功能缺陷",
                    "定稿面板缺少 JSON 导出",
                    "面板只有 PDF/Markdown",
                    "定稿面板应提供 PDF/Markdown/JSON",
                    ["打开已定稿工作台"],
                    clue="split-canvas.js renderFinalDraftPanel",
                )

            with page.expect_download(timeout=15000) as download_info:
                dock.locator('[data-action="export-final-draft-md"]').click()
            download = download_info.value
            filename = download.suggested_filename
            if not filename.endswith(".md") or "QA" not in filename:
                record(
                    "P2",
                    "功能缺陷",
                    "Markdown 导出文件名不合规",
                    f"suggested_filename={filename!r}",
                    "应使用 resualign-<title>-vN.md",
                    ["工作台点击导出 Markdown"],
                    clue="MVP-03 _export_filename / frontend filename",
                )
            self.check_console(page, "workbench-export")
        finally:
            context.close()

    def check_cost_guard(self) -> None:
        """MVP-10: daily cap persists and blocks new LLM tasks with 429."""
        api_call(
            self.base_url,
            "PUT",
            "/api/settings",
            {"daily_llm_cap": 1},
        )
        blocked = False
        try:
            api_call(
                self.base_url,
                "POST",
                "/api/jobs",
                {"jd_text": "cost-guard blocked probe"},
            )
            if not blocked:
                record(
                    "P2",
                    "功能缺陷",
                    "成本护栏未拦截超限任务",
                    "daily_llm_cap=1 后新 LLM 任务仍成功",
                    "超出上限应返回 429",
                    ["设置 daily_llm_cap=1", "连续触发两个 LLM 任务"],
                    clue="cost_guard.enforce_daily_llm_cap",
                )
        except AssertionError as exc:
            if "429" in str(exc):
                blocked = True
            else:
                record(
                    "P2",
                    "异常处理",
                    "成本护栏返回非预期错误",
                    str(exc)[:200],
                    "超限任务应返回 429 而非其他错误",
                    ["设置 daily_llm_cap=1", "触发第二个任务"],
                    clue="cost_guard.enforce_daily_llm_cap",
                )
        finally:
            api_call(
                self.base_url,
                "PUT",
                "/api/settings",
                {"daily_llm_cap": None},
            )

    def check_backup_restore_guard(self) -> None:
        """MVP-11: backup works while serving and restore refuses live service."""
        import subprocess
        import sys

        script = ROOT / "scripts" / "backup_restore.py"
        if self.app_tmp_path is None:
            return
        data_dir = self.app_tmp_path
        backup = subprocess.run(
            [
                sys.executable,
                str(script),
                "backup",
                "--data-dir",
                str(data_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if backup.returncode != 0:
            record(
                "P2",
                "功能缺陷",
                "在线备份脚本失败",
                backup.stderr[:300],
                "服务运行中应能创建一致备份",
                ["运行 scripts/backup_restore.py backup"],
                clue="backup_restore.py cmd_backup",
            )
            return
        manifests = list((Path(data_dir) / "backups").glob("manifest-*.json"))
        if not manifests:
            record(
                "P2",
                "功能缺陷",
                "备份未生成 manifest",
                "backups 目录没有 manifest",
                "备份产物应包含 manifest",
                ["运行备份脚本"],
                clue="backup_restore.py manifest 写入",
            )
        if self.app_port:
            restore_run = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "restore",
                    "--data-dir",
                    str(data_dir),
                    "--service-check",
                    str(self.app_port),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if restore_run.returncode == 0:
                record(
                    "P2",
                    "功能缺陷",
                    "恢复脚本未拒绝运行中服务",
                    "服务监听 8000 时 restore 仍成功",
                    "服务未停止时应拒绝恢复",
                    ["服务运行中执行 restore"],
                    clue="backup_restore.py service_check",
                )

    def check_mobile_nav_clickable(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 390, "height": 844}
        )
        page = self.new_page(context)
        targets = {
            "dashboard": "#/dashboard",
            "workspace": "#/workspace",
            "jobs": "#/jobs",
            "resume": "#/resume",
            "settings": "#/settings",
            "today": "#/today",
        }
        try:
            self.goto(page, "#/dashboard")
            for route, target in targets.items():
                button = page.locator(f'[data-route="{route}"]')
                try:
                    button.wait_for(timeout=5000)
                except PlaywrightTimeoutError:
                    record(
                        "P1",
                        "视觉适配",
                        f"移动端缺少导航按钮 {route}",
                        "390px 视口下按钮未渲染",
                        "五个主导航按钮都应可见",
                        ["390x844 访问 #/dashboard"],
                        clue="index.html app-rail 渲染",
                    )
                    continue
                box = button.bounding_box()
                hit = None
                if box:
                    hit = page.evaluate(
                        """(pt) => {
                            const el = document.elementFromPoint(pt.x, pt.y);
                            if (!el) return null;
                            const routeEl = el.closest('[data-route]');
                            return {
                                tag: el.tagName,
                                cls: String(el.className || ''),
                                route: routeEl ? routeEl.dataset.route : ''
                            };
                        }""",
                        {
                            "x": box["x"] + box["width"] / 2,
                            "y": box["y"] + box["height"] / 2,
                        },
                    )
                if not box or not hit or hit["route"] != route:
                    record(
                        "P1",
                        "视觉适配",
                        f"移动端导航按钮 {route} 不可点击",
                        f"box={box} hit={hit}",
                        "按钮中心应命中自身并可真实点击",
                        ["390x844 访问 #/dashboard"],
                        clue="app-rail 布局或 z-index 遮挡",
                    )
                    continue
                button.click()
                page.wait_for_timeout(600)
                actual = page.evaluate("location.hash")
                if route == "workspace":
                    ok = actual == "#/workspace" or actual.startswith("#/workspace/")
                    if ok and actual.startswith("#/workspace/"):
                        raw_id = actual.rsplit("/", 1)[-1].split("?")[0]
                        raw_id = urllib.parse.unquote(raw_id)
                        jobs = api_call(
                            self.base_url, "GET", "/api/jobs?limit=200"
                        )
                        job_ids = {job.get("job_id") for job in jobs}
                        if raw_id not in job_ids:
                            record(
                                "P1",
                                "功能缺陷",
                                "移动端工作台导航跳到无效岗位",
                                f"auto-redirect 到 {raw_id!r}，岗位库无此 id",
                                "自动跳转的目标必须是真实岗位",
                                ["390x844 点击工作台导航"],
                                clue="renderOptimizerCanvas 自动选岗逻辑",
                            )
                            ok = False
                else:
                    ok = actual == target
                if not ok:
                    record(
                        "P1",
                        "功能缺陷",
                        f"移动端导航 {route} 点击未跳转",
                        f"点击后 hash={actual!r}, 期望 {target!r}",
                        "导航按钮点击应切换路由",
                        ["390x844 点击导航按钮", route],
                        clue="main.js tab click 绑定",
                    )
        finally:
            context.close()

    def check_settings_and_theme(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            self.goto(page, "#/settings")
            toggle = page.locator('[data-action="toggle-theme"]')
            toggle.click()
            page.wait_for_timeout(300)
            pressed = toggle.get_attribute("aria-pressed")
            theme = page.locator("html").get_attribute("data-theme")
            self.check_console(page, "settings-theme")
            self.screenshot(page, "desktop-settings-theme")
            expected_pressed = "true" if theme == "dark" else "false"
            if theme not in ("light", "dark") or pressed != expected_pressed:
                record(
                    "P3",
                    "交互反馈",
                    "主题切换状态无反馈",
                    f"aria-pressed={pressed}, data-theme={theme}, "
                    f"expected={expected_pressed}",
                    "切换后按钮状态与主题 class 应联动",
                    ["进入设置", "点击主题切换"],
                    clue="theme.js 状态同步",
                )
        finally:
            context.close()

    def check_resume_diagnosis_persistence(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            resume = api_call(
                self.base_url,
                "POST",
                "/api/master-resumes",
                {
                    "title": "QA 诊断持久化",
                    "content": "# QA 诊断持久化\n\n- Python 后端\n- Redis 缓存\n",
                },
            )
            self.goto(page, f"#/resume/{resume['resume_id']}")
            page.click('[data-action="diagnose-resume"]')
            page.wait_for_function(
                """() => {
                    const node = document.querySelector(
                        '[data-resume-band-status-text]'
                    );
                    return node && /\\d+ 分/.test(node.textContent || '');
                }""",
                timeout=30000,
            )
            page.reload(wait_until="domcontentloaded")
            self.wait_view(page)
            page.wait_for_timeout(500)
            band = page.locator("[data-resume-band-status-text]").inner_text()
            if "分" not in band:
                record(
                    "P2",
                    "状态同步",
                    "简历诊断刷新后丢失",
                    f"F5 后状态文案为 {band!r}",
                    "刷新后应保留最近诊断分数",
                    ["诊断简历", "F5 刷新"],
                    clue="检查诊断结果是否持久化到 resume",
                )
        finally:
            context.close()

    def check_special_char_escaping(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            title = '<img src=x onerror="window.__pwned=1">QA'
            content = "<script>window.__scripted=1</script>\n# QA 标题\n"
            api_call(
                self.base_url,
                "POST",
                "/api/master-resumes",
                {"title": title, "content": content},
            )
            self.goto(page, "#/resume")
            pwned = page.evaluate("window.__pwned === 1")
            scripted = page.evaluate("window.__scripted === 1")
            img_count = page.locator("#app-router-view img").count()
            if pwned or scripted or img_count:
                record(
                    "P0",
                    "功能缺陷",
                    "简历标题/内容 HTML 未转义",
                    f"pwned={pwned} scripted={scripted} img_count={img_count}",
                    "用户输入应按纯文本渲染，不能执行 HTML/JS",
                    ["创建包含 HTML/JS 的简历", "访问简历列表"],
                    clue="检查 esc() 是否覆盖 title/content 渲染",
                )
        finally:
            context.close()

    def check_long_jd_input(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        tag = f"qa-long-{int(time.time())}"
        long_jd = (
            f"资深后端工程师（{tag}）\n"
            + ("岗位职责：负责高并发服务开发与性能优化。\n" * 1200)
        )
        try:
            self.goto(page, "#/jobs")
            page.click('[data-action="open-command-panel"]')
            page.fill('[data-command-input]', long_jd)
            page.wait_for_function(
                "() => !document.querySelector('[data-command-confirm]').disabled",
                timeout=10000,
            )
            page.click('[data-command-confirm]')
            page.wait_for_timeout(5000)
            errors = self.errors(page)
            toast_text = page.locator("#toast-region").inner_text()
            jobs = api_call(self.base_url, "GET", "/api/jobs?limit=500")
            created = any(tag in (job.get("jd_text") or "") for job in jobs)
            if errors["page"]:
                record(
                    "P1",
                    "异常处理",
                    "超长 JD 输入导致页面异常",
                    "; ".join(errors["page"]),
                    "超长输入不应导致未捕获异常",
                    ["粘贴 2 万字符 JD", "点击确认"],
                    clue="检查长文本处理/输入上限",
                )
            if not created and not toast_text.strip():
                record(
                    "P3",
                    "交互反馈",
                    "超长 JD 无结果也无提示",
                    "未创建岗位，也没有 toast 提示",
                    "要么创建岗位，要么明确提示输入超限",
                    ["粘贴 2 万字符 JD", "点击确认"],
                    clue="检查 command-panel 提交反馈",
                )
        finally:
            context.close()

    def check_missing_workspace_job(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        session_404s: list[str] = []

        def on_session_response(response) -> None:
            if (
                "/api/workspace/session/" in response.url
                or "/api/workbench/session/" in response.url
            ) and response.status >= 400:
                session_404s.append(f"{response.status} {response.url}")

        page.on("response", on_session_response)
        try:
            self.goto(page, "#/workspace/__missing_job__", wait=False)
            page.wait_for_timeout(3000)
            text = page.locator("#app-router-view").inner_text()
            hash_value = page.evaluate("location.hash")
            toast_text = page.locator("#toast-region").inner_text()
            if not hash_value.startswith("#/dashboard"):
                record(
                    "P2",
                    "异常处理",
                    "无效工作台深链未回退驾驶舱",
                    f"hash={hash_value!r}, view={text[:80]!r}",
                    "访问不存在的岗位应自动回退到驾驶舱",
                    ["访问 #/workspace/__missing_job__"],
                    clue="main.js 的 workspace not-found 回退分支",
                )
            if "岗位不存在" not in toast_text:
                record(
                    "P3",
                    "交互反馈",
                    "无效工作台深链缺少回退提示",
                    f"toast={toast_text!r}",
                    "回退驾驶舱时应提示岗位不存在",
                    ["访问 #/workspace/__missing_job__"],
                    clue="renderOptimizerCanvas 无效岗位分支",
                )
            if session_404s:
                record(
                    "P3",
                    "性能与控制台",
                    "无效工作台深链仍产生 session 404",
                    "; ".join(session_404s),
                    "无效岗位应直接回退，不应探测 session 路由",
                    ["访问 #/workspace/__missing_job__"],
                    clue="loadSession 应先确认岗位存在",
                )
        finally:
            context.close()

    def check_invalid_url_blocker(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        try:
            self.goto(page, "#/jobs")
            page.fill('[data-fetch-url]', "not-a-url")
            page.click('[data-action="fetch-job-url"]')
            page.wait_for_timeout(3000)
            errors = self.errors(page)
            badge = page.locator("[data-blocker-badge]").inner_text()
            toast_text = page.locator("#toast-region").inner_text()
            feedback = badge + " " + toast_text
            if errors["page"]:
                record(
                    "P1",
                    "异常处理",
                    "无效链接抓取导致页面异常",
                    "; ".join(errors["page"]),
                    "无效链接应有 blocker 反馈而非页面异常",
                    ["岗位库输入 not-a-url", "点击自动抓取"],
                    clue="检查 fetch pipeline 前端 catch",
                )
            if not feedback.strip():
                record(
                    "P2",
                    "交互反馈",
                    "无效链接抓取无任何反馈",
                    "页面没有 blocker 徽标或 toast",
                    "应提示链接无效并生成 blocker",
                    ["岗位库输入 not-a-url", "点击自动抓取"],
                    clue="检查 blocker badge 渲染",
                )
        finally:
            context.close()

    def check_mobile_viewport(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 390, "height": 844}
        )
        page = self.new_page(context)
        try:
            for label, route in [
                ("dashboard", "#/dashboard"),
                ("jobs", "#/jobs"),
                ("resume", "#/resume"),
                ("settings", "#/settings"),
                ("today", "#/today"),
                ("workspace", "#/workspace"),
            ]:
                try:
                    self.goto(page, route)
                    page.wait_for_timeout(300)
                    self.overflow_scan(page, f"mobile-{label}")
                    self.check_console(page, f"mobile-{label}")
                    self.screenshot(page, f"mobile-{label}")
                except PlaywrightTimeoutError:
                    record(
                        "P2",
                        "视觉适配",
                        f"移动端路由 {route} 加载超时",
                        "390px 视口下视图未渲染",
                        "移动端所有路由应可访问",
                        [f"390x844 访问 {route}"],
                        clue="检查移动端布局分支",
                    )
        finally:
            context.close()

    def check_network_degradation(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)

        def abort_jobs(route) -> None:
            if route.request.url.endswith("/api/jobs"):
                route.abort()
            else:
                route.continue_()

        context.route("**/api/jobs", abort_jobs)
        try:
            self.goto(page, "#/jobs", wait=False)
            try:
                self.wait_view(page)
            except PlaywrightTimeoutError:
                pass
            page.wait_for_timeout(800)
            text = page.locator("#app-router-view").inner_text()
            if "出错了" not in text and "重试" not in text and not page.locator("#job-board").count():
                record(
                    "P1",
                    "异常处理",
                    "岗位库接口失败无降级 UI",
                    "GET /api/jobs 失败后页面无错误提示",
                    "应显示错误面板或重试入口",
                    ["拦截 /api/jobs 使其失败", "访问 #/jobs"],
                    clue="检查 renderKanban 的 catch 分支",
                )
        finally:
            context.close()

    def check_double_submit(self, browser) -> None:
        context = browser.new_context(
            viewport={"width": 1440, "height": 900}
        )
        page = self.new_page(context)
        tag = f"qa-dup-{int(time.time())}"
        try:
            self.goto(page, "#/jobs")
            page.click('[data-action="open-command-panel"]')
            page.fill(
                '[data-command-input]',
                f"后端工程师（{tag}），负责高并发服务开发，要求 Python、FastAPI。",
            )
            page.wait_for_function(
                "() => !document.querySelector('[data-command-confirm]').disabled",
                timeout=10000,
            )
            page.evaluate(
                "() => { const b = document.querySelector('[data-command-confirm]'); b.click(); b.click(); }"
            )
            time.sleep(2)
            jobs = api_call(self.base_url, "GET", "/api/jobs?limit=200")
            matches = [j for j in jobs if tag in (j.get("jd_text") or "")]
            if len(matches) > 1:
                record(
                    "P2",
                    "状态同步",
                    "命令面板双击确认产生重复岗位",
                    f"同一 JD 创建了 {len(matches)} 条岗位",
                    "重复提交应被幂等拦截或按钮禁用",
                    ["粘贴 JD", "双击确认按钮"],
                    clue="检查 confirmCommandPanel 的防抖/幂等",
                )
        finally:
            context.close()

    def run(self, browser) -> None:
        self.check_routes(browser)
        self.check_empty_states(browser)
        self.check_deterministic_job_fields()
        self.check_resume_flow(browser)
        self.check_match_score_sort(browser)
        self.check_resume_diagnosis_persistence(browser)
        self.check_special_char_escaping(browser)
        self.check_job_and_workbench(browser)
        self.check_export_final_draft(browser)
        self.check_settings_and_theme(browser)
        self.check_today_view(browser)
        self.check_cost_guard()
        self.check_backup_restore_guard()
        self.check_long_jd_input(browser)
        self.check_missing_workspace_job(browser)
        self.check_invalid_url_blocker(browser)
        self.check_mobile_viewport(browser)
        self.check_mobile_nav_clickable(browser)
        self.check_network_degradation(browser)
        self.check_double_submit(browser)


def main() -> int:
    llm = FakeLLMServer()
    llm.start()
    app = AppServer(llm)
    app.start()
    try:
        runner = Runner(
            app.base_url,
            app_tmp_path=app.tmp_path,
            app_port=app.port,
        )
        with sync_playwright() as pw:
            chromium = pw.chromium.launch(headless=True)
            try:
                runner.run(chromium)
            finally:
                chromium.close()
    finally:
        app.stop()
        llm.stop()

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / "findings.json").write_text(
        json.dumps(FINDINGS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (ARTIFACTS / "console-all.log").write_text(
        "\n".join(CONSOLE_MESSAGES),
        encoding="utf-8",
    )
    print(f"findings: {len(FINDINGS)}")
    for finding in FINDINGS:
        print(f"  [{finding['severity']}] {finding['category']} {finding['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
