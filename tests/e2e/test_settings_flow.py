"""E2E: settings multi-node management -> reload -> node persists.

Sprint 5 replaced the single LLM form with a multi-node manager
(/api/llm/nodes). The flow under test is persistence: add a node via the
UI, reload, and confirm the node card (with masked key) survives. The
fake LLM server does not need to answer a node probe.
"""

from __future__ import annotations

import pytest
from helpers import capture_errors, expect, wait_for_function

pytestmark = pytest.mark.e2e

NODE_NAME = "e2e-openrouter"
PROVIDER = "openrouter"
MODEL = "e2e-openrouter-model"
API_KEY = "sk-e2e-1234567890abcd"
MASKED_KEY = "sk-e2e-1234567890abcd"[:4] + "••••" + API_KEY[-4:]

NODE_GRID = "[data-llm-node-grid]"
NODE_FORM = '[data-form="llm-node-form"]'


def test_node_survives_reload(page, base_url, api_call):
    errors = capture_errors(page)

    page.goto(f"{base_url}/#/settings", wait_until="domcontentloaded")
    page.wait_for_selector(NODE_GRID, timeout=15000)

    # Add a node via the modal form.
    page.click("[data-action='llm-node-add']")
    page.wait_for_selector(NODE_FORM, timeout=10000)
    page.fill(f"{NODE_FORM} input[name='node_name']", NODE_NAME)
    page.select_option(
        f"{NODE_FORM} select[name='node_provider']", PROVIDER
    )
    page.fill(f"{NODE_FORM} input[name='node_model']", MODEL)
    page.fill(f"{NODE_FORM} input[name='node_api_key']", API_KEY)
    page.click(f"{NODE_FORM} button[type='submit']")

    # The node card appears (view refreshes after submit) with a masked key,
    # never the raw one.
    wait_for_function(
        page,
        """(name) => Array.from(
               document.querySelectorAll("[data-llm-node-card]")
           ).some((card) => card.innerText.includes(name))""",
        arg=NODE_NAME,
        timeout=15.0,
    )
    card = page.locator("[data-llm-node-card]").filter(has_text=NODE_NAME)
    expect(card.count() >= 1, "new node card should render")
    card_text = card.first.inner_text()
    expect(
        MASKED_KEY in card_text,
        f"card should show masked key {MASKED_KEY}, got {card_text!r}",
    )
    expect(API_KEY not in card_text, "raw api key must never be shown")

    # Backend view: node persisted, key masked, raw never echoed.
    nodes = api_call("GET", "/api/llm/nodes")
    saved = next(
        (n for n in nodes if n.get("name") == NODE_NAME), None
    )
    expect(saved is not None, "node should exist in the backend")
    expect(saved["provider"] == PROVIDER, "provider should persist")
    expect(saved["model"] == MODEL, "model should persist")
    expect(
        saved.get("api_key") == MASKED_KEY,
        f"backend should mask the api key, got {saved.get('api_key')!r}",
    )

    # Reload: node card survives a fresh render from the store.
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector(NODE_GRID, timeout=15000)
    card = page.locator("[data-llm-node-card]").filter(has_text=NODE_NAME)
    expect(card.count() >= 1, "node card should survive reload")
    reload_text = card.first.inner_text()
    expect(
        MASKED_KEY in reload_text,
        "masked key should survive reload",
    )
    expect(API_KEY not in reload_text, "raw key never after reload")
