"""E2E: workbench key path — paste JD → classify → workbench → granularity →
async tailor → diff cards with provenance → accept bullet → markdown export.

The journey under test is the workstation money path:

1. 岗位库 command palette pastes a JD; the fake LLM classifies the job.
2. The workbench opens the job, pins a master resume, selects the fine
   granularity, and runs the async alignment (wb-run).
3. The split canvas polls to succeeded and renders diff cards with
   character-level highlights and provenance.
4. Accepting a bullet persists a final draft and surfaces the final-draft
   panel (the front-end accepted-state change).
5. Downloading Markdown carries the accepted text.

Setup through the API (the master resume — not the journey under test),
assertions through the rendered UI. The test owns its data and deletes the
job + resume in a finally block.

fake_llm coverage: the workbench run exercises ``resume auditor`` (diagnose),
``job description analyst + gap analyst`` (jd_analysis), and ``precise resume
editor`` (tailor) — all already routed by .scratch/phase-20/fake_llm.py, so
no fake-LLM change is required. evaluate is optional and stays off (the
settings default), matching the task's "(可选)" stage.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from helpers import (
    assert_clean_page,
    capture_errors,
    expect,
    wait_for_count,
    wait_for_function,
)

pytestmark = pytest.mark.e2e

UNIQUE_TAG = "e2e-wb-flow"
JD_TEXT = (
    "招聘 Python 后端工程师（{tag}），负责高并发服务端开发，"
    "要求熟悉 FastAPI 异步接口与 Redis 缓存。"
    "岗位要求：5 年以上后端经验；能支撑 millions of requests per day。"
).format(tag=UNIQUE_TAG)

# fake_llm.py's tailor branch rewrites the first resume line to
# "<line> (high concurrency)"; every assertion below keys on that line.
RESUME_TITLE_LINE = "E2E 工作台主简历"
RESUME_CONTENT = (
    RESUME_TITLE_LINE
    + "\n\n工作经历\n- 使用 Python 开发后端服务\n- 使用 Redis 做缓存与会话管理\n"
)
ACCEPTED_TEXT = f"{RESUME_TITLE_LINE} (high concurrency)"

WORKSPACE_SELECTOR = "[data-surface-mode='optimizer']"
SPLIT_FORM = "[data-form='split-align']"


def _wait_for_classified_job(api_call, timeout: float = 30.0) -> str:
    """Poll the jobs API until the pasted JD is classified and its JD
    profile is persisted (the background session pipeline has finished).

    Returns the library job_id. Bounded condition poll, no clock sleeps.
    """
    deadline = time.monotonic() + timeout
    job_id = None
    while time.monotonic() < deadline:
        jobs = api_call("GET", "/api/jobs?limit=100")
        for job in jobs:
            if UNIQUE_TAG in (job.get("jd_text") or ""):
                job_id = job["job_id"]
                if (
                    not job.get("classification_pending")
                    and (job.get("jd_profile") or {}).get("must_have_skills")
                ):
                    return job_id
        time.sleep(0.25)
    raise AssertionError(
        f"job tagged {UNIQUE_TAG!r} was not classified in time; "
        f"job_id={job_id}"
    )


def _read_download(download) -> str:
    path = download.path()
    return Path(path).read_text(encoding="utf-8")


def test_workbench_full_flow(page, base_url, api_call, artifacts_dir):
    errors = capture_errors(page)
    job_id = None
    resume_id = None

    # Setup through the API: one master resume the workbench can pin.
    resume = api_call("POST", "/api/master-resumes", {
        "title": "E2E 工作台主简历",
        "content": RESUME_CONTENT,
    })
    resume_id = resume["resume_id"]

    try:
        # --- 1. 岗位库 → 添加岗位（粘贴 JD，fake LLM 分类成功）------------
        page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
        page.wait_for_selector("[data-action='open-command-panel']", timeout=15000)
        page.click("[data-action='open-command-panel']")
        page.fill("[data-command-input]", JD_TEXT)
        # The confirm button stays disabled until the input is non-empty.
        wait_for_function(
            page,
            "() => !document.querySelector('[data-command-confirm]').disabled",
            timeout=10000,
        )
        page.click("[data-command-confirm]")

        # confirmCommandPanel POSTs /api/workbench/session/init and then
        # navigates to #/workspace/<session_id>; wait for that navigation.
        wait_for_function(
            page,
            "() => location.hash.startsWith('#/workspace/')",
            timeout=15000,
        )
        job_id = _wait_for_classified_job(api_call)

        # Back to the library: the card is classified (no pending badge).
        # Navigate by hash like the workspace hop below; a stale workspace
        # poller can pushState the hash back, so confirm it settled on the
        # jobs route and retry once before asserting on the board.
        for _ in range(2):
            page.evaluate("location.hash = '#/jobs'")
            try:
                page.wait_for_function(
                    "() => location.hash.startsWith('#/jobs')",
                    timeout=10.0,
                )
                page.wait_for_selector("#job-board", timeout=12000)
                break
            except Exception:
                continue
        card = page.locator(f'.board-card[data-job-id="{job_id}"]')
        card.wait_for(timeout=15000)
        expect(
            card.locator(".badge-pending").count() == 0,
            "job card should not show the pending badge after classification",
        )
        expect(
            card.locator(".badge-blue:has-text('后端')").count() >= 1,
            "job card should show the classified function badge",
        )

        # --- 2. 工作台打开该岗位 -------------------------------------------
        # Navigate by hash instead of clicking the card button: the board
        # re-renders on background polling (SSE/classification refresh), so
        # the button can detach mid-click on slower CI runners.
        page.evaluate("location.hash = '#/workspace/%s'" % job_id)
        page.wait_for_selector(WORKSPACE_SELECTOR, timeout=15000)

        # --- 3. 选主简历 + granularity（fine）→ 生成（wb-run）→ 轮询 succeeded
        wait_for_function(
            page,
            """({ resumeId }) => {
                const select = document.querySelector(
                    "[data-form='split-align'] [name='master_resume_id']");
                return select && [...select.options].some(
                    (option) => option.value === resumeId);
            }""",
            arg={"resumeId": resume_id},
            timeout=15000,
        )
        page.select_option(f"{SPLIT_FORM} [name='master_resume_id']", resume_id)
        page.select_option(f"{SPLIT_FORM} [name='granularity']", "fine")
        page.click("[data-align-run]")

        # Condition-based wait on the rendered diff cards (the frontend polls
        # the analysis job; no clock sleeps).
        wait_for_count(page, "[data-diff-list] .diff-card", 1, timeout=90000)
        first_card = page.locator("[data-diff-list] .diff-card").first
        first_card.wait_for(timeout=15000)

        # --- 4. Provenance 校验 --------------------------------------------
        provenance_badge = first_card.locator("[data-provenance]")
        expect(
            provenance_badge.count() == 1,
            "diff card should carry a provenance badge",
        )
        expect(
            first_card.locator(".provenance-badge--verified").count() == 1,
            "fake-LLM provenance resolves to verified",
        )
        quote = first_card.locator(".provenance-quote")
        expect(
            quote.count() == 1,
            "diff card should render a provenance quote",
        )
        expect(
            RESUME_TITLE_LINE in quote.inner_text(),
            f"provenance quote should cite the source line, "
            f"got {quote.inner_text()!r}",
        )

        # Character-level highlight (#17): the proposed side wraps the
        # inserted characters in .diff-char-ins.
        proposed = first_card.locator("[data-diff-proposed]")
        expect(
            proposed.locator(".diff-char-ins").count() >= 1,
            "proposed side should show character-level insert marks",
        )
        expect(
            ACCEPTED_TEXT in proposed.inner_text(),
            f"proposed text should carry the tailored line, "
            f"got {proposed.inner_text()!r}",
        )

        # --- 5. 采纳（accept-bullet）→ 采纳态变化 --------------------------
        before = api_call("GET", f"/api/jobs/{job_id}")
        expect(
            not (before.get("final_draft") or "").strip(),
            "job should have no final draft before accepting",
        )
        first_card.locator('[data-action="accept-bullet"]').click()

        # The front-end accepted state: the final-draft panel appears and
        # shows the incremental draft containing the accepted text.
        panel = page.locator("[data-final-draft-panel]:not([hidden])")
        panel.wait_for(timeout=15000)
        expect(
            ACCEPTED_TEXT in panel.locator(".pre.draft-preview").inner_text(),
            "final-draft panel should show the accepted text",
        )
        after = api_call("GET", f"/api/jobs/{job_id}")
        expect(
            ACCEPTED_TEXT in (after.get("final_draft") or ""),
            "final_draft should persist the accepted text",
        )

        # --- 6. 下载 Markdown → 导出内容含采纳后的文本 ---------------------
        # The workbench dock's "下载 Markdown" (export-align-markdown) carries
        # the accepted suggestion and its provenance in 修改建议. (Its 对齐内容
        # section reads session.alignment.draft, which the split-canvas SSE
        # job.result replay sets from result.draft — the analysis result has
        # no draft field, so the section renders the "尚未生成定稿" placeholder
        # in the current product. The accepted draft itself is exported from
        # the final-draft panel below.)
        with page.expect_download(timeout=15000) as download_info:
            page.click("[data-action='export-align-markdown']")
        dock_content = _read_download(download_info.value)
        expect(
            dock_content.startswith("# "),
            "workbench markdown export should start with a title heading",
        )
        expect(
            "## 修改建议" in dock_content,
            "workbench markdown export should carry a 修改建议 section",
        )
        expect(
            "Matches JD high-concurrency scenario" in dock_content,
            "markdown should list the accepted diff's reason",
        )
        expect(
            "来源已验证" in dock_content,
            "markdown should carry the verified provenance label",
        )

        # The final-draft panel's "导出 Markdown" (export-final-draft-md)
        # exports state.wbFinalDraft.draft — the accepted text, via a real
        # Playwright download event.
        with page.expect_download(timeout=15000) as download_info:
            page.click("[data-action='export-final-draft-md']")
        content = _read_download(download_info.value)
        expect(
            ACCEPTED_TEXT in content,
            f"accepted-draft markdown should contain the accepted text, "
            f"got:\n{content[:400]}",
        )

        # Passing-run artifact for the report.
        shots = artifacts_dir / "passing"
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(shots / "workbench-full-flow.png"), full_page=True
        )
        assert_clean_page(errors, "workbench full flow")
    finally:
        if job_id:
            try:
                api_call("DELETE", f"/api/jobs/{job_id}")
            except AssertionError:
                pass
        if resume_id:
            try:
                api_call("DELETE", f"/api/master-resumes/{resume_id}")
            except AssertionError:
                pass
