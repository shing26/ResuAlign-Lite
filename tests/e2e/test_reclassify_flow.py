"""E2E: pending-classification amber badge -> reclassify -> badge gone.

The pending state is constructed through the real API path: the fake LLM's
``/control/classify-fail`` endpoint makes the next 2 classifier calls
carrying the ``__E2E_CLASSIFY_FAIL__`` marker fail with HTTP 500 (the app
retries each LLM call once, for 2 attempts total), so
``_create_job_from_source`` stores the job with ``classification_pending=1``
-- no direct SQL, no special endpoints.

The UI has no reclassify button yet (the ``reclassify-job`` action handler
exists in main.js but is not wired to any element), so the reclassify
request is issued from the page context via fetch; the badge assertion is
fully end-to-end through the rendered board.
"""

from __future__ import annotations

import pytest
from helpers import assert_clean_page, capture_errors, expect

pytestmark = pytest.mark.e2e

FAIL_MARKER = "__E2E_CLASSIFY_FAIL__"
PENDING_JD = (
    "招聘 Python 后端工程师，要求 FastAPI 与 Redis，负责高并发服务端。"
    + FAIL_MARKER
)


def _reclassify_via_page(page, job_id: str) -> dict:
    return page.evaluate(
        """async (jobId) => {
            const res = await fetch(`/api/jobs/${jobId}/reclassify`, {
                method: "POST",
            });
            let body = null;
            try { body = await res.json(); } catch (_) {}
            return { ok: res.ok, status: res.status, body };
        }""",
        job_id,
    )


def test_pending_badge_then_reclassify(
    page, base_url, api_call, llm_api_call
):
    errors = capture_errors(page)

    # Make the fake LLM fail both classifier attempts carrying the marker
    # (the app retries each LLM call once), so POST /api/jobs stores the job
    # as classification_pending instead of failing the request.
    llm_api_call("POST", "/control/classify-fail?times=2")

    # Create a job whose classification fails -> stored as pending.
    job = api_call("POST", "/api/jobs", {
        "title": "E2E 分类待定岗位",
        "jd_text": PENDING_JD,
        "company": "E2E 待定公司",
        "location": "上海",
    })
    job_id = job["job_id"]
    expect(
        job["classification_pending"] == 1,
        "job should be stored with classification_pending=1",
    )
    health = llm_api_call("GET", "/health")
    expect(
        health["stage_hits"].get("e2e classify fail", 0) == 2,
        "fake LLM should have failed 2 classify attempts, "
        f"got {health['stage_hits']}",
    )

    try:
        # Board shows the amber badge on the pending job's card.
        page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
        card = page.locator(f'.board-card[data-job-id="{job_id}"]')
        card.wait_for(timeout=15000)
        badge = card.locator(".badge-pending")
        badge.wait_for(timeout=10000)
        expect(
            badge.inner_text().find("分类待定") >= 0,
            "pending badge should read 分类待定",
        )

        # Reclassify through the page context: the fake LLM now succeeds,
        # so the endpoint clears the pending flag and sets classification.
        result = _reclassify_via_page(page, job_id)
        expect(result["ok"], f"reclassify failed: {result}")
        expect(
            result["body"]["classification_pending"] == 0,
            "reclassify should clear classification_pending",
        )
        expect(
            result["body"]["job_function"] == "后端",
            f"reclassify should classify the job, got {result['body']}",
        )

        # Reload: the badge is gone from the board card.
        page.reload(wait_until="domcontentloaded")
        card = page.locator(f'.board-card[data-job-id="{job_id}"]')
        card.wait_for(timeout=15000)
        expect(
            card.locator(".badge-pending").count() == 0,
            "pending badge should disappear after reclassify",
        )

        # API agrees the flag is cleared.
        stored = api_call("GET", f"/api/jobs/{job_id}")
        expect(
            stored["classification_pending"] == 0,
            "stored job should no longer be pending",
        )
        assert_clean_page(errors, "reclassify")
    finally:
        try:
            api_call("DELETE", f"/api/jobs/{job_id}")
        except AssertionError:
            pass
