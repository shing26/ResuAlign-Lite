import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs window/document/localStorage globals
 * before events.js evaluates (it reads localStorage at module scope). */
import "./happy-setup.mjs";

import { setWbMobilePane, state } from "../../../src/resualign/static/app/events.js";

/* F5: 移动端工作台双面板（调优 / 结果）切换。 */

function mountWorkbench() {
  document.body.innerHTML = `
    <div data-workbench-layout>
      <div class="wb-mobile-tabs">
        <button type="button" data-action="set-wb-tab" data-wb-tab="controls" aria-selected="true">调优</button>
        <button type="button" data-action="set-wb-tab" data-wb-tab="diff" aria-selected="false">结果</button>
      </div>
      <div class="wb-main is-active" data-wb-pane="diff"></div>
      <div class="wb-aux">
        <div class="wb-pane active" data-wb-pane="controls"></div>
        <div class="wb-pane" data-wb-pane="livesheet"></div>
      </div>
    </div>`;
}

test("setWbMobilePane activates the diff pane and updates tab aria-selected", () => {
  mountWorkbench();
  state.wbMobilePane = "controls";
  setWbMobilePane("diff");
  assert.equal(state.wbMobilePane, "diff");
  assert.equal(
    document.querySelector('[data-wb-tab="diff"]').getAttribute("aria-selected"),
    "true",
  );
  assert.equal(
    document.querySelector('[data-wb-tab="controls"]').getAttribute("aria-selected"),
    "false",
  );
  assert.ok(document.querySelector('[data-wb-pane="diff"]').classList.contains("is-active"));
  assert.ok(!document.querySelector('[data-wb-pane="controls"]').classList.contains("is-active"));
});

test("setWbMobilePane switches back to controls from diff", () => {
  mountWorkbench();
  setWbMobilePane("diff");
  assert.ok(document.querySelector('[data-wb-pane="diff"]').classList.contains("is-active"));
  assert.ok(!document.querySelector('[data-wb-pane="controls"]').classList.contains("is-active"));
  setWbMobilePane("controls");
  assert.ok(document.querySelector('[data-wb-pane="controls"]').classList.contains("is-active"));
  assert.ok(!document.querySelector('[data-wb-pane="diff"]').classList.contains("is-active"));
});

test("setWbMobilePane clamps unknown panes to controls", () => {
  mountWorkbench();
  setWbMobilePane("bogus");
  assert.equal(state.wbMobilePane, "controls");
  assert.ok(document.querySelector('[data-wb-pane="controls"]').classList.contains("is-active"));
});

test("setWbMobilePane is a no-op when the workbench DOM is absent", () => {
  document.body.innerHTML = "<div></div>";
  state.wbMobilePane = "diff";
  setWbMobilePane("controls");
  assert.equal(state.wbMobilePane, "controls");
});
