"""Capture README screenshots from an isolated, synthetic demo dataset.

The shots never touch the user's real ``data/`` directory: the app runs on a
random port with a temporary SQLite database, a fake LLM, and invented
resumes/jobs. The point is a representative UI screenshot that carries no
personal information.

Usage:

    python scripts/capture_readme_shots.py

Output:

    docs/assets/shots/dashboard.png
    docs/assets/shots/jobs.png

Screenshots are illustrative, not evidence. Numbers quoted in the README must
still come from the commands listed in ``docs/EVIDENCE.md``.
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

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
E2E_DIR = ROOT / "tests" / "e2e"
OUT_DIR = ROOT / "docs" / "assets" / "shots"

RESUME = """林一帆
后端工程师 · 5 年经验 · 上海

技能
Python · FastAPI · PostgreSQL · Redis · Docker · Kubernetes

工作经历
云杉数据 · 后端工程师 · 2021.07 - 至今
- 用 Python 与 FastAPI 重构订单服务，P99 从 480ms 降到 190ms。
- 用 Redis 做热点缓存与分布式锁，峰值 QPS 提升 3 倍。
- 用 PostgreSQL 分区表与索引优化慢查询，日报生成耗时下降 62%。
- 用 Docker 与 Kubernetes 管理 12 个服务，发布回滚时间从 30 分钟降到 3 分钟。

星澜科技 · 后端开发实习生 · 2020.03 - 2021.06
- 参与日志采集服务开发，日均处理 2 亿条事件。
- 编写接口自动化脚本，回归测试时间缩短一半。

教育
华东理工大学 · 计算机科学与技术 · 本科
"""

JOBS = [
    {
        "title": "高级后端工程师",
        "company": "北辰智能",
        "location": "上海",
        "salary_min": 30000,
        "salary_max": 45000,
        "status": "interview",
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Python", "FastAPI", "Redis", "PostgreSQL"],
        "posting_date": "2026-11-12",
        "jd_text": (
            "公司：北辰智能\n地点：上海\n高级后端工程师\n"
            "职责：负责推理平台的服务端架构与稳定性建设。\n"
            "要求：5 年以上 Python 经验，熟悉 FastAPI、Redis、PostgreSQL；"
            "有高并发与容器化经验；熟悉 Kubernetes 者优先。"
        ),
    },
    {
        "title": "数据平台工程师",
        "company": "星澜科技",
        "location": "杭州",
        "salary_min": 25000,
        "salary_max": 38000,
        "status": "applied",
        "job_function": "数据",
        "seniority": "中级",
        "tech_tags": ["Python", "SQL", "Spark", "Airflow"],
        "posting_date": "2026-11-08",
        "jd_text": (
            "公司：星澜科技\n地点：杭州\n数据平台工程师\n"
            "职责：建设离线与实时数据链路，维护调度与质量监控。\n"
            "要求：熟悉 Python、SQL、Spark、Airflow；有数据仓库建模经验。"
        ),
    },
    {
        "title": "AI 应用工程师",
        "company": "拾光工作室",
        "location": "远程",
        "salary_min": 28000,
        "salary_max": 40000,
        "status": "applied",
        "job_function": "算法",
        "seniority": "中级",
        "tech_tags": ["Python", "LLM", "RAG", "FastAPI"],
        "posting_date": "2026-11-05",
        "jd_text": (
            "公司：拾光工作室\n地点：远程\nAI 应用工程师\n"
            "职责：把大模型能力落到业务流程，负责检索增强与工具调用。\n"
            "要求：熟悉 Python 与 FastAPI；理解 RAG、向量检索与提示词工程。"
        ),
    },
    {
        "title": "全栈工程师",
        "company": "澄海网络",
        "location": "深圳",
        "salary_min": 22000,
        "salary_max": 35000,
        "status": "offer",
        "job_function": "后端",
        "seniority": "中级",
        "tech_tags": ["Python", "React", "TypeScript", "PostgreSQL"],
        "posting_date": "2026-10-28",
        "jd_text": (
            "公司：澄海网络\n地点：深圳\n全栈工程师\n"
            "职责：独立负责中小型产品的后端与前端交付。\n"
            "要求：熟悉 Python 后端与 React/TypeScript 前端，能设计关系型数据库。"
        ),
    },
    {
        "title": "后端开发工程师",
        "company": "极昼实验室",
        "location": "北京",
        "salary_min": 26000,
        "salary_max": 40000,
        "status": "draft",
        "job_function": "后端",
        "seniority": "高级",
        "tech_tags": ["Go", "Python", "MySQL", "Redis"],
        "posting_date": "2026-11-15",
        "jd_text": (
            "公司：极昼实验室\n地点：北京\n后端开发工程师\n"
            "职责：负责实验平台的服务端研发与性能优化。\n"
            "要求：熟悉 Go 或 Python，掌握 MySQL、Redis；有分布式系统经验。"
        ),
    },
    {
        "title": "Python 后端工程师",
        "company": "云杉数据",
        "location": "上海",
        "salary_min": 24000,
        "salary_max": 36000,
        "status": "draft",
        "job_function": "后端",
        "seniority": "中级",
        "tech_tags": ["Python", "Django", "Redis", "Docker"],
        "posting_date": "2026-11-18",
        "jd_text": (
            "公司：云杉数据\n地点：上海\nPython 后端工程师\n"
            "职责：负责数据产品的 API 与任务调度。\n"
            "要求：熟悉 Python、Django、Redis、Docker；重视工程质量。"
        ),
    },
    {
        "title": "平台后端工程师",
        "company": "青屿医疗",
        "location": "苏州",
        "salary_min": 20000,
        "salary_max": 32000,
        "status": "withdrawn",
        "job_function": "后端",
        "seniority": "中级",
        "tech_tags": ["Java", "Python", "MySQL", "Redis"],
        "posting_date": "2026-10-20",
        "jd_text": (
            "公司：青屿医疗\n地点：苏州\n平台后端工程师\n"
            "职责：负责医疗数据平台的服务端开发。\n"
            "要求：熟悉 Java 或 Python，掌握 MySQL 与 Redis；接受轮值。"
        ),
    },
]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Server:
    def __init__(self, name: str, tmp: Path) -> None:
        self.name = name
        self.port = free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.tmp = tmp
        self.proc: subprocess.Popen | None = None
        self.log = (tmp / f"{name}.log").open("wb")

    def wait_health(self) -> None:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(
                    f"{self.name} exited early:\n"
                    f"{(self.tmp / f'{self.name}.log').read_text(errors='replace')}"
                )
            try:
                urllib.request.urlopen(f"{self.base_url}/health", timeout=1).read()
                return
            except Exception:
                time.sleep(0.3)
        raise RuntimeError(f"{self.name} did not become healthy")

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.log.close()


def api(base: str, method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(
        base + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {body}") from exc


def start_fake_llm(tmp: Path) -> Server:
    server = Server("fake-llm", tmp)
    server.proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "fake_llm:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(server.port),
            "--app-dir",
            str(E2E_DIR),
        ],
        stdout=server.log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    server.wait_health()
    return server


def start_app(tmp: Path, llm: Server) -> Server:
    server = Server("app", tmp)
    env = os.environ.copy()
    env.update(
        {
            "LLM_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "readme-shot-placeholder",
            "DEEPSEEK_MODEL": "readme-shot-model",
            "DEEPSEEK_BASE_URL": f"{llm.base_url}/v1",
            "RESUALIGN_PERSONAL_MODE": "1",
            "RESUALIGN_DATA_DIR": str(tmp / "data"),
            "RESUALIGN_JOB_DB": str(tmp / "data" / "jobs.db"),
            "RESUALIGN_HOST": "127.0.0.1",
            "RESUALIGN_PORT": str(server.port),
            "RESUALIGN_LOG_DIR": str(tmp / "logs"),
            "PYTHONPATH": str(SRC),
        }
    )
    server.proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "resualign.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(server.port),
            "--app-dir",
            str(SRC),
        ],
        env=env,
        stdout=server.log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    server.wait_health()
    return server


def seed(base: str) -> None:
    resume = api(
        base,
        "POST",
        "/api/master-resumes",
        {"title": "林一帆 · 后端工程师", "content": RESUME},
    )
    diag = api(base, "POST", f"/api/master-resumes/{resume['resume_id']}/diagnose", {})
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = api(base, "GET", f"/api/jobs/{diag['job_id']}/analysis-status")
        if state.get("status") in {"succeeded", "failed", "expired"}:
            break
        time.sleep(1)

    job_ids: list[str] = []
    for job in JOBS:
        created = api(base, "POST", "/api/jobs", job)
        job_ids.append(created["job_id"])

    api(
        base,
        "POST",
        f"/api/jobs/{job_ids[0]}/workbench",
        {"master_resume_id": resume["resume_id"], "run_eval": True},
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = api(base, "GET", f"/api/jobs/{job_ids[0]}")
        if state.get("alignment_status") in {"succeeded", "failed"}:
            break
        time.sleep(1)


def wait_view(page) -> None:
    page.wait_for_function(
        "() => !document.querySelector('[data-view-skeleton]')", timeout=20000
    )


def capture(base: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            device_scale_factor=1,
            reduced_motion="reduce",
            color_scheme="light",
        )
        page = context.new_page()

        page.goto(f"{base}/#/dashboard", wait_until="domcontentloaded")
        wait_view(page)
        page.wait_for_timeout(1800)
        page.screenshot(path=str(OUT_DIR / "dashboard.png"))

        page.goto(f"{base}/#/jobs?view=list", wait_until="domcontentloaded")
        wait_view(page)
        page.wait_for_selector("[data-jh-card]", timeout=15000)
        page.locator("[data-jh-job]").first.click()
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT_DIR / "jobs.png"))

        context.close()
        browser.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="resualign-readme-shots-"))
    llm = start_fake_llm(tmp)
    app = start_app(tmp, llm)
    try:
        seed(app.base_url)
        capture(app.base_url)
    finally:
        app.stop()
        llm.stop()
    print(f"wrote {OUT_DIR.relative_to(ROOT)} (tmp: {tmp})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
