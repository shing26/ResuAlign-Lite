"""Temporary debug harness for the phase-20 mobile diff-card visibility."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".scratch" / "phase-20"))

import playwright_smoke as pm  # noqa: E402


errors = {"console": [], "page": []}


def new_page(context, errors):
    page = context.new_page()
    page.on(
        "console",
        lambda msg: errors["console"].append(msg.text)
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda exc: errors["page"].append(str(exc)))
    page.on("dialog", lambda dialog: dialog.accept())
    return page


pm.new_page = new_page

llm = pm.FakeLLMServer()
llm.start()
app = pm.AppServer(llm)
app.start()
created = {"resume_ids": [], "job_ids": []}
try:
    with pm.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            accept_downloads=True,
        )
        failed = None
        try:
            pm.run_key_path(context, errors, app.base_url, "Phase20 Mobile", created)
        except Exception as exc:
            failed = exc
            print("SMOKE ERROR:", exc)
            for page in context.pages:
                print("PAGE URL:", page.url)
                try:
                    print(
                        "diff-card count:",
                        page.locator(".diff-card").count(),
                    )
                    print(
                        "diff-card visible:",
                        page.locator(".diff-card").first.is_visible()
                        if page.locator(".diff-card").count()
                        else None,
                    )
                    print(
                        "a4-wrap count:",
                        page.locator("[data-a4-wrap]").count(),
                    )
                    print(
                        "diff-list count:",
                        page.locator(".diff-list").count(),
                    )
                    print(
                        "wb-main display:",
                        page.locator("[data-wb-pane='diff']").first.evaluate(
                            "(el) => getComputedStyle(el).display"
                        )
                        if page.locator("[data-wb-pane='diff']").count()
                        else None,
                    )
                    print(
                        "mobile tabs visible:",
                        page.locator("[data-wb-tab='diff']").first.is_visible()
                        if page.locator("[data-wb-tab='diff']").count()
                        else None,
                    )
                    print(
                        "v3 tabs visible:",
                        page.locator("[data-wb-tab-v3='controls']").first.is_visible()
                        if page.locator("[data-wb-tab-v3='controls']").count()
                        else None,
                    )
                    active = page.evaluate(
                        """() => {
                            const btn = document.querySelector(
                                ".wb-view-toggle__btn.active"
                            );
                            return btn ? btn.textContent.trim() : null;
                        }"""
                    )
                    print("active view mode:", active)
                except Exception as inspect_exc:
                    print("inspect failed:", inspect_exc)
        context.close()
        browser.close()
        if failed:
            raise failed
finally:
    for job_id in created["job_ids"]:
        try:
            pm.api_call(app.base_url, "DELETE", f"/api/jobs/{job_id}")
        except Exception:
            pass
    for resume_id in created["resume_ids"]:
        try:
            pm.api_call(
                app.base_url,
                "DELETE",
                f"/api/master-resumes/{resume_id}",
            )
        except Exception:
            pass
    app.stop()
    llm.stop()
