"""Shared browser helpers for the ResuAlign E2E suite.

Kept dependency-light on purpose: no pytest-playwright plugin, no hard
sleeps. All waits are condition-based (Playwright auto-waiting selectors /
``wait_for_function``), matching the determinism bar of the smoke script.
"""

from __future__ import annotations

import time
from typing import Callable


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def use_board_view(page) -> None:
    """B2（2026-10-22）起岗位库默认是「列表」视图；依赖看板卡片交互的
    冒烟用例需要显式把视图固定回看板，否则 #job-board .board-card 永远为空。"""
    page.add_init_script(
        "try { localStorage.setItem('resualign.jobs.view', 'board'); } "
        "catch (error) { /* storage disabled: view falls back to list */ }"
    )


def capture_errors(page):
    """Return the console/page-error capture dict for a fixture page.

    The conftest ``page`` fixture wires listeners and stores the dict on the
    page object; this indirection keeps test bodies free of pytest internals.
    """
    capture = getattr(page, "_e2e_errors", None)
    if capture is not None:
        return capture
    # Defensive fallback for pages created outside the fixture.
    errors = {"all": [], "console": [], "page": []}

    def on_console(message) -> None:
        errors["all"].append(message.text)
        if message.type == "error":
            errors["console"].append(message.text)

    page.on("console", on_console)
    page.on("pageerror", lambda exc: errors["page"].append(str(exc)))
    return errors


def assert_clean_page(errors: dict, label: str) -> None:
    """Fail on page exceptions and on severe console errors.

    Noise filters mirror the smoke script (favicon 404s and generic
    resource-load failures are environment chatter, not app bugs).
    """
    expect(not errors["page"], f"{label} page errors: {errors['page']}")
    severe = [
        error
        for error in errors["console"]
        if "favicon" not in error.lower()
        and "failed to load" not in error.lower()
    ]
    expect(not severe, f"{label} console errors: {severe}")


def wait_for_function(
    page, expression: str, arg=None, timeout: float = 20.0
):
    """Poll a JS predicate in the page until it is truthy or timeout.

    ``arg`` is passed through as the single Playwright argument; predicates
    that need multiple values should destructure it (``({a, b}) => ...``).
    """
    page.wait_for_function(
        expression, arg=arg, timeout=timeout * 1000
    )


def wait_for_count(
    page, selector: str, expected: int, timeout: float = 20.0
) -> None:
    """Wait until ``selector`` matches exactly ``expected`` elements."""
    wait_for_function(
        page,
        """({selector, expected}) =>
            document.querySelectorAll(selector).length === expected""",
        arg={"selector": selector, "expected": expected},
        timeout=timeout,
    )


def poll_until(
    predicate: Callable[[], bool],
    message: str,
    timeout: float = 20.0,
    interval: float = 0.25,
) -> None:
    """Poll a Python predicate; raise AssertionError on timeout.

    ``interval`` sleeps are bounded condition polls, never clock-to-completion
    waits: the predicate is re-checked every tick and returns as soon as the
    condition holds.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for: {message}")
