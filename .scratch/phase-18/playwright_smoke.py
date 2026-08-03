"""Phase 18 card + component motion smoke pass (desktop + mobile)."""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
P16_DIR = ROOT / ".scratch" / "phase-16"
sys.path.insert(0, str(P16_DIR))

from playwright_smoke import (  # noqa: E402
    AppServer,
    LLMServer,
    api_call,
    assert_no_overflow,
    expect,
    new_page,
)

SHOTS = Path(__file__).resolve().parent / "screenshots"
PREFIX = "Phase18 卡片"
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


def computed(page, selector, prop, pseudo=None) -> str:
    if pseudo:
        return page.evaluate(
            """([selector, prop, pseudo]) => {
                const node = document.querySelector(selector);
                return getComputedStyle(node, pseudo).getPropertyValue(prop);
            }""",
            [selector, prop, pseudo],
        ).strip()
    return page.evaluate(
        """([selector, prop]) => {
            const node = document.querySelector(selector);
            return getComputedStyle(node).getPropertyValue(prop);
        }""",
        [selector, prop],
    ).strip()


def check_desktop_look(page) -> None:
    expect(page.locator(".app-rail").count() == 1, "rail missing")
    expect(page.locator(".tabs button").count() == 4, "nav buttons missing")
    expect(
        "个人模式" in page.locator("#mode-label").inner_text(),
        "personal mode label missing",
    )
    expect(
        page.locator(".modal-backdrop").count() == 0,
        "login modal appeared",
    )

    panel_card = page.locator(".panel-card").first
    expect(panel_card.count() > 0, "panel-card missing")
    expect(
        computed(page, ".panel-card", "border-radius") == "8px",
        "panel-card radius is not 8px",
    )
    expect(
        computed(page, ".panel-card", "box-shadow") != "none",
        "panel-card has no card shadow",
    )
    expect(
        computed(page, ".card-list .card", "animation-name") == "card-enter",
        "card stagger animation missing",
    )
    expect(
        computed(page, ".card.resume-card", "border-radius") == "8px",
        "resume card radius is not 8px",
    )
    expect(
        page.locator(".card.resume-card.card-base.card-hover-soft").count() == 1,
        "resume card classes missing",
    )


def check_segmented(page) -> None:
    page.wait_for_timeout(500)
    expect(
        computed(page, ".segmented-card", "border-radius") == "8px",
        "segmented card radius missing",
    )
    expect(
        computed(
            page,
            '.segmented button[aria-pressed="true"]',
            "opacity",
            "::before",
        )
        == "1",
        "segmented indicator is not visible",
    )


def check_mobile_look(page) -> None:
    expect(page.locator(".app-rail").count() == 1, "rail missing")
    expect(
        computed(page, ".btn", "min-height") == "44px",
        "mobile button touch target below 44px",
    )
    expect(
        computed(page, ".tabs--rail button", "min-height") == "44px",
        "mobile rail touch target below 44px",
    )
    expect(
        computed(page, ".card-list .card", "animation-delay") == "0s",
        "mobile stagger delay is not zero",
    )


def main() -> None:
    errors = {"console": [], "page": []}
    llm = LLMServer()
    llm.start()
    app = AppServer(llm)
    app.start()
    base = app.base_url
    created_resume_ids: list[str] = []
    created_job_ids: list[str] = []
    SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        resume = api_call(
            base,
            "POST",
            "/api/master-resumes",
            {"title": RESUME_TITLE, "content": RESUME_CONTENT},
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

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=1,
            )
            page = new_page(context, errors)

            page.goto(f"{base}/#/resume", wait_until="networkidle")
            page.wait_for_selector(".card.resume-card")
            check_desktop_look(page)
            assert_no_overflow(page, "desktop resume center")
            page.screenshot(path=str(SHOTS / "phase18-desktop-resume.png"))

            page.goto(
                f"{base}/#/resume/{resume['resume_id']}",
                wait_until="networkidle",
            )
            page.wait_for_selector(".resume-doc")
            expect(
                page.locator(".panel--teal.panel-card").count() == 1,
                "diagnosis panel card missing",
            )
            expect(
                page.locator(".card-list.motion-stagger").count() >= 1,
                "version history stagger missing",
            )
            expect(
                page.locator(
                    ".card.version-card.card-base.card-hover-soft"
                ).count()
                >= 1,
                "version card classes missing",
            )
            assert_no_overflow(page, "desktop resume detail")
            page.screenshot(
                path=str(SHOTS / "phase18-desktop-resume-detail.png")
            )

            page.goto(f"{base}/#/jobs", wait_until="networkidle")
            page.wait_for_selector(".card.job-card")
            expect(
                page.locator(
                    ".card.job-card.card-base.card-hover-soft"
                ).count()
                == 1,
                "job card classes missing",
            )
            check_segmented(page)
            assert_no_overflow(page, "desktop jobs")
            page.screenshot(path=str(SHOTS / "phase18-desktop-jobs.png"))

            page.goto(
                f"{base}/#/workspace/{job['job_id']}",
                wait_until="networkidle",
            )
            page.wait_for_selector(".appraisal-panel")
            expect(
                page.locator(".appraisal-panel.panel-card").count() == 1,
                "appraisal panel card missing",
            )
            expect(
                page.locator(".segmented-card").count() >= 2,
                "workspace segmented cards missing",
            )
            check_segmented(page)
            assert_no_overflow(page, "desktop workspace")
            page.screenshot(
                path=str(SHOTS / "phase18-desktop-workspace.png")
            )

            page.goto(f"{base}/#/settings", wait_until="networkidle")
            page.wait_for_selector('[data-form="settings-weights"]')
            expect(
                page.locator(
                    '[data-form="settings-weights"].panel-card'
                ).count()
                == 1,
                "settings panel card missing",
            )
            assert_no_overflow(page, "desktop settings")
            page.screenshot(path=str(SHOTS / "phase18-desktop-settings.png"))
            page.close()

            mobile = pw.chromium.launch()
            mcontext = mobile.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                device_scale_factor=1,
            )
            mpage = new_page(mcontext, errors)
            mpage.goto(f"{base}/#/resume", wait_until="networkidle")
            mpage.wait_for_selector(".card.resume-card")
            check_mobile_look(mpage)
            assert_no_overflow(mpage, "mobile resume center")
            mpage.screenshot(path=str(SHOTS / "phase18-mobile-resume.png"))

            mpage.goto(
                f"{base}/#/workspace/{job['job_id']}",
                wait_until="networkidle",
            )
            mpage.wait_for_selector(".appraisal-panel")
            assert_no_overflow(mpage, "mobile workspace")
            mpage.screenshot(
                path=str(SHOTS / "phase18-mobile-workspace.png")
            )
            mpage.close()
            context.close()
            mcontext.close()

            reduce_context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                reduced_motion="reduce",
            )
            rpage = new_page(reduce_context, errors)
            rpage.goto(f"{base}/#/resume", wait_until="networkidle")
            rpage.wait_for_selector(".card.resume-card")
            duration = computed(rpage, ".card-list .card", "animation-duration")
            duration_seconds = (
                float(duration[:-2]) / 1000
                if duration.endswith("ms")
                else float(duration.rstrip("s"))
            )
            expect(
                duration_seconds <= 0.001,
                "reduced motion did not kill animation",
            )
            rpage.close()
            reduce_context.close()
            browser.close()

        expect(
            not errors["console"] and not errors["page"],
            f"browser errors: {errors}",
        )
    finally:
        for job_id in created_job_ids:
            try:
                api_call(base, "DELETE", f"/api/jobs/{job_id}")
            except Exception:
                pass
        for resume_id in created_resume_ids:
            try:
                api_call(base, "DELETE", f"/api/master-resumes/{resume_id}")
            except Exception:
                pass
        app.stop()
        llm.stop()
    print("PHASE18 VISUAL OK")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PHASE18 VISUAL FAILED: {exc}", file=sys.stderr)
        raise
