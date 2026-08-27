"""E2E: batch import 5 JDs -> job library counts 5 -> open job detail.

Setup is through the API (the app boots with an empty temp database), the
import itself is exercised through the real UI form: 批量导入 -> paste CSV ->
submit -> wait for the board to show 5 cards.
"""

from __future__ import annotations

import pytest
from helpers import (
    assert_clean_page,
    capture_errors,
    expect,
    wait_for_count,
)

pytestmark = pytest.mark.e2e

IMPORT_CSV = "\n".join([
    "title,jd_text,location",
    "E2E 后端工程师 A,招聘 Python 后端工程师 负责高并发服务端开发 A,上海",
    "E2E 后端工程师 B,招聘 Python 后端工程师 负责高并发服务端开发 B,北京",
    "E2E 后端工程师 C,招聘 Python 后端工程师 负责高并发服务端开发 C,深圳",
    "E2E 后端工程师 D,招聘 Python 后端工程师 负责高并发服务端开发 D,杭州",
    "E2E 后端工程师 E,招聘 Python 后端工程师 负责高并发服务端开发 E,广州",
])


def test_batch_import_five_jobs(page, base_url, api_call, artifacts_dir):
    errors = capture_errors(page)

    # Board starts empty on a fresh temp DB.
    page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector("[data-jobs-data-menu] summary", timeout=15000)
    page.click("[data-jobs-data-menu] summary")
    page.wait_for_selector("[data-action='show-import']", timeout=15000)
    expect(
        page.locator("#job-board .board-card").count() == 0,
        "fresh job board should be empty",
    )

    # Open the batch import form and paste 5 CSV rows.
    page.click("[data-action='show-import']")
    page.wait_for_selector("[data-form='job-import']:not([hidden])")
    page.fill(
        '[data-form="job-import"] textarea[name="import_text"]', IMPORT_CSV
    )
    page.click('[data-form="job-import"] button[type="submit"]')

    # The UI polls POST /api/jobs/import until the worker thread finishes;
    # wait on the completion text, then on the rendered card count.
    page.wait_for_selector("text=完成：新建 5", timeout=90000)
    wait_for_count(page, "#job-board .board-card", 5, timeout=30000)
    expect(
        page.locator("[data-jobs-rail-count]").inner_text().strip() == "5",
        "jobs rail should show a total of 5",
    )

    # API agrees: exactly 5 jobs are stored.
    jobs = api_call("GET", "/api/jobs?limit=100")
    expect(len(jobs) == 5, f"expected 5 jobs via API, got {len(jobs)}")
    job_ids = [job["job_id"] for job in jobs]

    try:
        # Open one job's detail modal from its board card.
        card = page.locator(f'.board-card[data-job-id="{job_ids[0]}"]')
        card.wait_for()
        title = next(
            job["title"] for job in jobs if job["job_id"] == job_ids[0]
        )
        card.locator(".board-more summary").click()
        card.locator("[data-action='open-job-timeline']").wait_for(
            state="visible", timeout=5000
        )
        card.locator('[data-action="open-job-timeline"]').click()
        modal = page.locator(".modal-backdrop[role='dialog']")
        modal.wait_for(timeout=10000)
        modal_title = modal.locator(".modal h3").inner_text()
        expect("岗位详情" in modal_title, "job detail modal should open")
        expect(title in modal_title, f"modal should name the job ({title})")
        page.click("[data-action='close-modal']")
        page.wait_for_selector(".modal-backdrop", state="detached")

        # Screenshot the populated board as a passing-run artifact.
        shots = artifacts_dir / "passing"
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=str(shots / "batch-import-board.png"), full_page=True
        )
        assert_clean_page(errors, "batch import")
    finally:
        for job_id in job_ids:
            try:
                api_call("DELETE", f"/api/jobs/{job_id}")
            except AssertionError:
                pass
