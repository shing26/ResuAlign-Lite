"""Temporary debug harness for the phase-20 markdown export failure."""

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

    def on_response(resp):
        if resp.request.method != "GET":
            print(
                "REQ",
                resp.request.method,
                resp.url,
                "->",
                resp.status,
            )
        if resp.status >= 400:
            print("HTTP", resp.status, resp.request.method, resp.url)
            try:
                print((resp.text() or "")[:600])
            except Exception as exc:
                print("read body failed:", exc)

    page.on("response", on_response)
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
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
        )
        try:
            pm.run_key_path(context, errors, app.base_url, "Phase20", created)
        except Exception:
            print("CONSOLE ERRORS:", errors["console"])
            print("PAGE ERRORS:", errors["page"])
            raise
        finally:
            context.close()
            browser.close()
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
