"""V4 browser smoke: settings token + applied-draft snapshot drawer."""

from __future__ import annotations

import pytest
from helpers import capture_errors, expect, wait_for_function

pytestmark = pytest.mark.e2e


def _job_payload(title: str, status: str | None = None) -> dict:
    payload = {
        "title": title,
        "jd_text": f"{title}\nPython + FastAPI，20-30K",
        "company": "Acme",
        "location": "Shanghai",
    }
    if status:
        payload["status"] = status
    return payload


def test_local_ingest_token_visible_reset_and_persists(
    page, base_url
):
    capture_errors(page)
    page.goto(f"{base_url}/#/settings", wait_until="domcontentloaded")
    page.wait_for_selector("[data-local-ingest-panel]", timeout=15000)
    token1 = page.locator("[data-local-ingest-token]").inner_text()
    expect(len(token1) >= 20, "settings should expose a generated token")

    page.click("[data-action='reset-local-ingest-token']")
    wait_for_function(
        page,
        """(prev) => {
            const node = document.querySelector("[data-local-ingest-token]");
            return node && node.textContent !== prev;
        }""",
        arg=token1,
        timeout=10.0,
    )
    token2 = page.locator("[data-local-ingest-token]").inner_text()
    expect(token1 != token2, "reset should rotate the token")

    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("[data-local-ingest-panel]", timeout=15000)
    expect(
        page.locator("[data-local-ingest-token]").inner_text() == token2,
        "rotated token should survive reload",
    )


def test_job_drawer_shows_snapshots_and_legacy_fallback(
    page, base_url, api_call
):
    capture_errors(page)

    applied_job = api_call("POST", "/api/jobs", _job_payload("V4 Snapshot Job"))
    api_call(
        "POST",
        f"/api/jobs/{applied_job['job_id']}/final-draft",
        {"draft": "# Snapshot draft"},
    )
    api_call(
        "PATCH",
        f"/api/jobs/{applied_job['job_id']}",
        {"status": "applied", "applied_at": "2026-08-10"},
    )
    snapshots = api_call(
        "GET", f"/api/jobs/{applied_job['job_id']}/snapshots"
    )
    expect(
        len(snapshots) == 1 and snapshots[0]["version_index"] == 1,
        "applying a drafted job should freeze one snapshot",
    )

    legacy_job = api_call(
        "POST",
        "/api/jobs",
        _job_payload("V4 Legacy Applied", status="applied"),
    )
    api_call(
        "POST",
        f"/api/jobs/{legacy_job['job_id']}/final-draft",
        {"draft": "# Legacy draft"},
    )
    expect(
        api_call("GET", f"/api/jobs/{legacy_job['job_id']}/snapshots") == [],
        "pre-migration applied job should have no immutable snapshots",
    )

    page.goto(f"{base_url}/#/jobs", wait_until="domcontentloaded")
    page.wait_for_selector(
        f"[data-job-id='{applied_job['job_id']}']", timeout=15000
    )
    page.click(
        f"[data-job-id='{applied_job['job_id']}'] .board-more__trigger"
    )
    page.click(
        f"[data-action='open-job-timeline'][data-id='{applied_job['job_id']}']"
    )
    page.wait_for_selector("[data-snapshot-item]", timeout=10000)
    snapshot_html = page.locator(".modal-backdrop").inner_text()
    expect("第 1 版投递快照" in snapshot_html, "drawer should list snapshot v1")
    expect("匹配度 —" in snapshot_html, "missing match score should show placeholder")
    page.click("[data-action='close-modal']")

    page.wait_for_selector(
        f"[data-job-id='{legacy_job['job_id']}']", timeout=15000
    )
    page.click(
        f"[data-job-id='{legacy_job['job_id']}'] .board-more__trigger"
    )
    page.click(
        f"[data-action='open-job-timeline'][data-id='{legacy_job['job_id']}']"
    )
    page.wait_for_selector("[data-legacy-snapshot]", timeout=10000)
    legacy_html = page.locator(".modal-backdrop").inner_text()
    expect(
        "早期投递版本（未生成不可篡改快照）" in legacy_html,
        "legacy applied job should show the early-version warning",
    )
