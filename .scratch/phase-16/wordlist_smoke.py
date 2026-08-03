"""T6 wordlist sync smoke: settings words -> library dropdowns -> fallback."""

from __future__ import annotations

import json
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
BUILTIN_FUNCTIONS = ["后端", "前端", "算法", "数据", "测试", "运维",
                     "产品", "设计", "运营", "销售", "其他"]


def api_call(method: str, path: str, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(
        BASE + path, data=data, headers=headers, method=method
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def option_values(page, selector: str) -> list[str]:
    return page.locator(selector + " option").all_inner_texts()


def fake_jobs_route(route):
    job = {
        "job_id": "job-wordlist-smoke",
        "title": "Wordlist Smoke Job",
        "company": "Example",
        "location": "Shanghai",
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "CNY",
        "job_function": "后端",
        "seniority": "高级",
        "status": "已投递",
        "tech_tags": ["Python"],
        "jd_text": "Backend engineer.",
        "classification_pending": False,
    }
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps([job]),
    )


def run() -> None:
    api_call(
        "PUT",
        "/api/settings",
        {
            "classification_vocabulary": {
                "job_functions": ["架构", "后端"],
                "seniorities": ["首席", "高级"],
                "statuses": ["待定", "已投递"],
            }
        },
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        settings_calls: list[str] = []
        page.on(
            "request",
            lambda req: settings_calls.append(req.url)
            if req.url.endswith("/api/settings")
            else None,
        )
        page.route("**/api/jobs*", fake_jobs_route)
        page.goto(f"{BASE}/#/jobs", wait_until="networkidle")
        page.wait_for_selector('select[name="job_function"]')

        assert "架构" in option_values(page, 'select[name="job_function"]')
        assert "首席" in option_values(page, 'select[name="seniority"]')
        assert "待定" in option_values(page, 'select[name="status"]')

        page.locator(
            '[data-form="job-filter"] select[name="job_function"]'
        ).select_option("架构")
        page.locator('[data-form="job-filter"] button[type="submit"]').click()
        page.wait_for_selector('select[name="job_function"]')
        assert "架构" in option_values(page, 'select[name="job_function"]')
        assert len(settings_calls) == 1, (
            f"expected one settings request, got {len(settings_calls)}"
        )

        page.wait_for_selector('[data-action="edit-job"]')
        page.click('[data-action="edit-job"]')
        modal_function = '.modal select[name="job_function"]'
        modal_seniority = '.modal select[name="seniority"]'
        modal_status = '.modal select[name="status"]'
        page.wait_for_selector(modal_function)
        assert "架构" in option_values(page, modal_function)
        assert "首席" in option_values(page, modal_seniority)
        assert "待定" in option_values(page, modal_status)

        fallback = context.new_page()
        fallback.route(
            "**/api/settings",
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"detail": "unavailable"}),
            ),
        )
        fallback.route("**/api/jobs*", fake_jobs_route)
        fallback.goto(f"{BASE}/#/jobs", wait_until="networkidle")
        fallback.wait_for_selector('select[name="job_function"]')
        assert option_values(fallback, 'select[name="job_function"]') == [
            "全部",
            *BUILTIN_FUNCTIONS,
        ]
        assert "架构" not in option_values(
            fallback, 'select[name="job_function"]'
        )
        browser.close()

    print("T6 wordlist smoke passed")


if __name__ == "__main__":
    run()
