"""E2E: settings page saves LLM config -> reload -> values persist.

The backend persists settings to the temp SQLite store (PUT /api/settings)
and masks the API key in every response, so after ``page.reload()`` the
form shows the saved provider/model and the masked-key hint instead of the
raw key. Test-connection is deliberately skipped: the flow under test is
persistence, and the fake LLM does not need a probe.
"""

from __future__ import annotations

import pytest
from helpers import assert_clean_page, capture_errors, expect

pytestmark = pytest.mark.e2e

PROVIDER = "openrouter"
MODEL = "e2e-openrouter-model"
API_KEY = "sk-e2e-1234567890abcd"
MASKED_KEY = "sk-e••••abcd"

LLM_FORM = '[data-form="settings-llm"]'


def _form_state(page) -> dict:
    provider = page.locator(f"{LLM_FORM} select[name='llm_provider']")
    model = page.locator(f"{LLM_FORM} input[name='llm_model']")
    key_hint = page.locator(
        f"{LLM_FORM} input[name='llm_api_key'] ~ .small.muted"
    )
    return {
        "provider": provider.input_value(),
        "model": model.input_value(),
        "hint": key_hint.inner_text(),
        "placeholder": page.locator(
            f"{LLM_FORM} input[name='llm_api_key']"
        ).get_attribute("placeholder") or "",
    }


def test_settings_survive_reload(page, base_url, api_call):
    errors = capture_errors(page)

    page.goto(f"{base_url}/#/settings", wait_until="domcontentloaded")
    page.wait_for_selector(LLM_FORM, timeout=15000)

    # Fill and save the LLM form.
    page.select_option(
        f"{LLM_FORM} select[name='llm_provider']", PROVIDER
    )
    page.fill(f"{LLM_FORM} input[name='llm_model']", MODEL)
    page.fill(f"{LLM_FORM} input[name='llm_api_key']", API_KEY)
    page.click(f"{LLM_FORM} button[type='submit']")

    # Save re-renders the view; wait for the masked-key hint to appear.
    page.wait_for_selector(
        f"{LLM_FORM} input[name='llm_api_key'] ~ "
        ".small.muted:has-text('已保存 Key')",
        timeout=15000,
    )

    state = _form_state(page)
    expect(
        state["provider"] == PROVIDER,
        f"provider should persist, got {state['provider']}",
    )
    expect(
        state["model"] == MODEL,
        f"model should persist, got {state['model']}",
    )
    expect(
        MASKED_KEY in state["hint"],
        f"hint should show the masked key {MASKED_KEY}, got {state['hint']!r}",
    )

    # Backend view: masked key, never the raw one.
    saved = api_call("GET", "/api/settings")
    llm = saved.get("llm") or {}
    expect(llm.get("provider") == PROVIDER, "backend provider should persist")
    expect(llm.get("model") == MODEL, "backend model should persist")
    expect(
        llm.get("api_key") == MASKED_KEY,
        f"backend should mask the api key, got {llm.get('api_key')!r}",
    )
    expect(API_KEY not in str(saved), "raw api key must never be echoed")

    # Reload the page: values survive a fresh render from the store.
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector(LLM_FORM, timeout=15000)
    state = _form_state(page)
    expect(state["provider"] == PROVIDER, "provider should survive reload")
    expect(state["model"] == MODEL, "model should survive reload")
    expect(
        MASKED_KEY in state["hint"],
        "masked-key hint should survive reload",
    )
    expect(
        state["placeholder"].find("已保存") >= 0,
        "api key field should hint that a key is already saved",
    )
    assert_clean_page(errors, "settings")

    # Restore defaults so later scenarios keep resolving .env config.
    reset = api_call("POST", "/api/settings/reset")
    expect(
        ((reset.get("llm") or {}).get("provider") or "") == "",
        "settings reset should clear the stored provider",
    )
