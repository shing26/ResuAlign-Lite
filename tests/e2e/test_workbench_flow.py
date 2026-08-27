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
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from helpers import (
    assert_clean_page,
    capture_errors,
    expect,
    poll_until,
    wait_for_count,
    wait_for_function,
)

pytestmark = pytest.mark.e2e

UNIQUE_TAG = "e2e-wb-flow"
SOURCE_URL = f"https://example.com/jobs/{UNIQUE_TAG}"
JD_TEXT = (
    "招聘 Python 后端工程师（{tag}），负责高并发服务端开发，"
    "要求熟悉 FastAPI 异步接口与 Redis 缓存。"
    "岗位要求：5 年以上后端经验；能支撑 millions of requests per day。"
).format(tag=UNIQUE_TAG)

# fake_llm.py's bullet-level editor rewrites the first targeted bullet to
# "<bullet> (high concurrency)"; every assertion below keys on that bullet.
RESUME_TITLE_LINE = "E2E 工作台主简历"
TARGET_BULLET = "使用 Python 开发后端服务"
RESUME_CONTENT = (
    RESUME_TITLE_LINE
    + "\n\n工作经历\n- 使用 Python 开发后端服务\n- 使用 Redis 做缓存与会话管理\n"
)
ACCEPTED_TEXT = f"{TARGET_BULLET} (high concurrency)"

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


def test_command_palette_preserves_multiline_jd(page, base_url, api_call):
    """Pasting a multi-line JD keeps line breaks for deterministic parsing."""
    tag = f"e2e-multiline-{time.time_ns()}"
    jd_text = (
        f"资深后端工程师（{tag}）\n"
        "公司：星辰科技\n"
        "地点：上海\n"
        "薪资：25-35K\n"
        "岗位职责：负责 FastAPI 服务设计与开发\n"
        "任职要求：Python、PostgreSQL、Redis"
    )
    job_id = None
    try:
        page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
        page.wait_for_selector("[data-action='open-command-panel']", timeout=15000)
        page.click("[data-action='open-command-panel']")
        page.fill("[data-command-input]", jd_text)
        page.press("[data-command-input]", "Enter")
        wait_for_function(
            page,
            "() => location.hash.startsWith('#/workspace/')",
            timeout=15000,
        )

        deadline = time.monotonic() + 10.0
        job = None
        while time.monotonic() < deadline:
            jobs = api_call("GET", "/api/jobs?limit=100")
            job = next(
                (item for item in jobs if tag in (item.get("jd_text") or "")),
                None,
            )
            if job is not None:
                break
            time.sleep(0.25)
        expect(job is not None, "multi-line JD should create a library job")
        job_id = job["job_id"]
        expect(
            "\n" in (job.get("jd_text") or ""),
            "command palette must preserve JD line breaks",
        )
        expect(job.get("title") == f"资深后端工程师（{tag}）", "title parsed")
        expect(job.get("company") == "星辰科技", "company parsed")
        expect(job.get("location") == "上海", "location parsed")
        # De-bloat: salary is no longer auto-extracted from JD text.
        expect(job.get("salary_min") is None, "salary min no longer auto-parsed")
        expect(job.get("salary_max") is None, "salary max no longer auto-parsed")
    finally:
        if job_id:
            api_call("DELETE", f"/api/jobs/{job_id}")


def test_workbench_full_flow(page, base_url, api_call, artifacts_dir, browser):
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
        # Do a full reload so any in-flight workspace poller/SSE callbacks
        # from the previous view are gone; hash-only navigation could let a
        # stale callback pushState back to the workspace route on CI.
        page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
        page.wait_for_selector("#job-board", timeout=20000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("#job-board", timeout=20000)
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
            TARGET_BULLET in quote.inner_text(),
            f"provenance quote should cite the source bullet, "
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
        poll_until(
            lambda: ACCEPTED_TEXT
            in ((api_call("GET", f"/api/jobs/{job_id}") or {}).get(
                "final_draft"
            ) or ""),
            "final_draft should persist the accepted text",
            timeout=15.0,
        )

        # #23: 补链接与记录投递入口必须同时出现在上下文条和定稿面板。
        context_actions = page.locator(".wb-context-actions")
        expect(
            context_actions.locator(
                f'[data-action="open-job-detail"][data-id="{job_id}"]'
            ).count()
            >= 1,
            "workbench context should guide the missing source link",
        )
        expect(
            context_actions.locator(
                f'[data-action="record-application"][data-id="{job_id}"]'
            ).count()
            >= 1,
            "workbench context should expose record-application",
        )
        final_panel = page.locator("[data-final-draft-panel]:not([hidden])")
        expect(
            final_panel.locator(
                f'[data-action="open-job-detail"][data-id="{job_id}"]'
            ).count()
            >= 1,
            "final-draft panel should guide the missing source link",
        )
        expect(
            final_panel.locator(
                f'[data-action="record-application"][data-id="{job_id}"]'
            ).count()
            >= 1,
            "final-draft panel should expose record-application",
        )

        # --- 6. canonical 定稿 Markdown 导出含采纳后的文本 ----------------
        # MVP-09：导出只走 /api/jobs/{job_id}/exports，内容来自持久化的
        # final_draft + accepted_diff_ids，不再导出会话内临时 Markdown。
        with page.expect_download(timeout=15000) as download_info:
            final_panel.locator(
                '[data-action="export-final-draft-md"]'
            ).click()
        content = _read_download(download_info.value)
        expect(
            content.startswith("# "),
            "canonical markdown export should start with a title heading",
        )
        expect(
            "## 定稿内容" in content,
            "canonical markdown export should carry the 定稿内容 section",
        )
        expect(
            ACCEPTED_TEXT in content,
            f"accepted-draft markdown should contain the accepted text, "
            f"got:\n{content[:400]}",
        )
        expect(
            "## 采纳项" in content,
            "canonical markdown export should carry the 采纳项 section",
        )

        # #23: 详情补填 source_url → 卡片/工作台显示去投递 → 记录投递。
        page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
        page.wait_for_selector("#job-board", timeout=20000)
        card = page.locator(f'.board-card[data-job-id="{job_id}"]')
        card.wait_for(timeout=15000)
        card.locator(".board-more summary").click()
        card.locator('[data-action="open-job-timeline"]').click()
        modal = page.locator(".modal-backdrop")
        modal.wait_for(timeout=10000)
        link_input = modal.locator('input[name="source_url"]')
        link_input.wait_for(timeout=10000)
        link_input.fill(SOURCE_URL)
        modal.locator("[data-form='job-detail-edit'] button[type='submit']").click()
        modal.wait_for(state="detached", timeout=10000)

        go_apply = card.locator(
            f'[data-action="open-source-url"][data-url="{SOURCE_URL}"]'
        )
        go_apply.wait_for(timeout=10000)
        page.evaluate(
            """() => {
                window.__openedUrls = [];
                window.open = (url, name, features) => {
                    window.__openedUrls.push({ url, name, features });
                    return null;
                };
            }"""
        )
        go_apply.click()
        opened = page.evaluate("() => window.__openedUrls")
        expect(
            opened
            == [
                {
                    "url": SOURCE_URL,
                    "name": "_blank",
                    "features": "noopener,noreferrer",
                }
            ],
            "go-to-apply should open the original JD URL in a new tab",
        )

        page.evaluate("location.hash = '#/workspace/%s'" % job_id)
        page.wait_for_selector(WORKSPACE_SELECTOR, timeout=15000)
        context_actions = page.locator(".wb-context-actions")
        go_apply = context_actions.locator(
            f'[data-action="open-source-url"][data-url="{SOURCE_URL}"]'
        )
        go_apply.wait_for(timeout=10000)
        final_panel = page.locator("[data-final-draft-panel]:not([hidden])")
        final_panel.wait_for(timeout=10000)
        expect(
            final_panel.locator(
                f'[data-action="open-source-url"][data-url="{SOURCE_URL}"]'
            ).count()
            >= 1,
            "final-draft panel should show go-to-apply after source_url save",
        )
        context_actions.locator(
            f'[data-action="record-application"][data-id="{job_id}"]'
        ).click()
        page.wait_for_function(
            "() => (document.querySelector('.wb-context-meta') || {}).textContent"
            "?.includes('已投递')",
            timeout=10000,
        )
        poll_until(
            lambda: (api_call("GET", f"/api/jobs/{job_id}") or {}).get("status")
            in ("applied", "已投递"),
            "record-application should move the job to applied",
            timeout=15,
        )
        recorded = api_call("GET", f"/api/jobs/{job_id}")
        expect(
            bool(recorded.get("applied_at")),
            "record-application should stamp applied_at",
        )

        # --- 6.9 #24: 安排跟进 → 生命周期写字段 → 提醒条立即更新 ----
        fresh_context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        followup_page = fresh_context.new_page()
        followup_errors = capture_errors(followup_page)
        try:
            followup_page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
            followup_page.wait_for_selector("#job-board", timeout=20000)
            card = followup_page.locator(f'.board-card[data-job-id="{job_id}"]')
            card.wait_for(timeout=15000)
            card.locator(".board-more summary").click()
            card.locator('[data-action="open-job-followup"]').click()
            followup_modal = followup_page.locator(".modal-backdrop")
            followup_modal.wait_for(timeout=10000)
            followup_form = followup_modal.locator("[data-form='job-followup']")
            followup_form.locator('[name="status"]').select_option("interview")
            followup_form.locator('[name="interview_stage"]').select_option("二面")
            followup_form.locator('[name="next_step"]').fill("准备二面")
            due_at = (datetime.now() + timedelta(hours=24)).strftime(
                "%Y-%m-%dT%H:%M"
            )
            followup_form.locator('[name="next_step_due_at"]').fill(due_at)
            followup_form.locator("button[type='submit']").click()
            followup_modal.wait_for(state="detached", timeout=10000)

            followed = api_call("GET", f"/api/jobs/{job_id}")
            expect(
                followed.get("status") in ("interview", "面试中"),
                "follow-up save should move the job to interview",
            )
            expect(
                followed.get("next_step") == "准备二面",
                "follow-up save should persist next_step",
            )
            expect(
                followed.get("next_step_due_at") == due_at,
                "follow-up save should persist due time",
            )
            expect(
                bool(followed.get("applied_at")),
                "lifecycle should keep applied_at while entering interview",
            )
            assert_clean_page(followup_errors, "workbench followup")
        finally:
            fresh_context.close()

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
