import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs browser globals before events.js
 * evaluates (it reads localStorage at module scope). */
import "./happy-setup.mjs";

import { setWbAuxPane } from "../../../src/resualign/static/app/split-canvas.js";

function mountAuxTabs() {
  document.body.innerHTML = `
    <div id="app-router-view">
      <div class="wb-tabs">
        <button type="button" data-action="set-wb-tab-v3" data-wb-tab-v3="inspector" aria-selected="true" class="wb-tab active">JD Inspector</button>
        <button type="button" data-action="set-wb-tab-v3" data-wb-tab-v3="livesheet" aria-selected="false" class="wb-tab">Live Sheet</button>
      </div>
      <div data-inspector-pane class="active"></div>
      <div data-live-sheet-pane></div>
    </div>`;
}

test("setWbAuxPane switches to live sheet and updates tabs", () => {
  mountAuxTabs();
  setWbAuxPane("livesheet");
  assert.equal(
    document.querySelector('[data-wb-tab-v3="livesheet"]').getAttribute("aria-selected"),
    "true",
  );
  assert.equal(
    document.querySelector('[data-wb-tab-v3="inspector"]').getAttribute("aria-selected"),
    "false",
  );
  assert.ok(document.querySelector('[data-live-sheet-pane]').classList.contains("active"));
  assert.ok(!document.querySelector('[data-inspector-pane]').classList.contains("active"));
});

test("setWbAuxPane switches back to inspector", () => {
  mountAuxTabs();
  setWbAuxPane("livesheet");
  setWbAuxPane("inspector");
  assert.equal(
    document.querySelector('[data-wb-tab-v3="inspector"]').getAttribute("aria-selected"),
    "true",
  );
  assert.ok(document.querySelector('[data-inspector-pane]').classList.contains("active"));
  assert.ok(!document.querySelector('[data-live-sheet-pane]').classList.contains("active"));
});

test("setWbAuxPane ignores unknown panes", () => {
  mountAuxTabs();
  setWbAuxPane("bogus");
  assert.equal(
    document.querySelector('[data-wb-tab-v3="inspector"]').getAttribute("aria-selected"),
    "true",
  );
  assert.ok(document.querySelector('[data-inspector-pane]').classList.contains("active"));
});
