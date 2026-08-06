import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs window/document/localStorage globals
 * before events.js (imported transitively by diff-editor.js) evaluates. */
import "./happy-setup.mjs";

import { Window } from "happy-dom";
import {
  bindColumnScrollSync,
  captureColumnScrolls,
  renderWbResult,
  restoreColumnScrolls,
  syncScrollTop,
} from "../../../src/resualign/static/app/diff-editor.js";
import { state } from "../../../src/resualign/static/app/events.js";

/* ------------------------------------------------------------------ */
/* syncScrollTop / bindColumnScrollSync                                */
/* ------------------------------------------------------------------ */

test("syncScrollTop mirrors only changed positions", () => {
  const target = document.createElement("div");
  const source = document.createElement("div");
  source.scrollTop = 10;
  assert.equal(syncScrollTop(target, source), true);
  assert.equal(target.scrollTop, 10);
  assert.equal(syncScrollTop(target, source), false);
  assert.equal(syncScrollTop(null, source), false);
  assert.equal(syncScrollTop(target, null), false);
  assert.equal(syncScrollTop(target, target), false);
});

test("bindColumnScrollSync mirrors both directions and unbinds", () => {
  const left = document.createElement("div");
  const right = document.createElement("div");
  const unbind = bindColumnScrollSync([left, right]);

  left.scrollTop = 33;
  left.dispatchEvent(new window.Event("scroll"));
  assert.equal(right.scrollTop, 33);

  right.scrollTop = 77;
  right.dispatchEvent(new window.Event("scroll"));
  assert.equal(left.scrollTop, 77);

  unbind();
  left.scrollTop = 1;
  left.dispatchEvent(new window.Event("scroll"));
  assert.equal(right.scrollTop, 77);
});

test("bindColumnScrollSync returns a no-op unbind for missing columns", () => {
  const noop = bindColumnScrollSync([]);
  assert.equal(typeof noop, "function");
  noop();
});

test("captureColumnScrolls and restoreColumnScrolls round-trip positions", () => {
  document.body.innerHTML = `
    <div id="p">
      <div class="cmp-column"></div>
      <div class="cmp-column"></div>
    </div>`;
  const panel = document.getElementById("p");
  const columns = panel.querySelectorAll(".cmp-column");
  columns[0].scrollTop = 5;
  columns[1].scrollTop = 9;
  const tops = captureColumnScrolls(panel);
  assert.deepEqual(tops, [5, 9]);

  columns[0].scrollTop = 0;
  columns[1].scrollTop = 0;
  assert.equal(restoreColumnScrolls(panel, tops), 2);
  assert.equal(columns[0].scrollTop, 5);
  assert.equal(columns[1].scrollTop, 9);

  assert.equal(captureColumnScrolls(null).length, 0);
  assert.equal(restoreColumnScrolls(null, tops), 0);
  assert.equal(restoreColumnScrolls(panel, null), 0);
});

/* ------------------------------------------------------------------ */
/* renderWbResult: line numbers, char marks, scroll sync, toggle keep  */
/* ------------------------------------------------------------------ */

function setupState() {
  state.wbResult = {
    tailored_resume: { sections: { a: "负责高并发系统开发\n相同行" } },
    diffs: [
      { type: "modify", original: "负责系统开发", proposed: "负责高并发系统开发" },
    ],
    score: 70,
    model: "deepseek-chat",
    elapsed_seconds: 3,
  };
  state.wbOriginalContent = "负责系统开发\n相同行";
  state.wbRun = null;
  state.wbJob = null;
  state.wbAcceptedIndices = [];
  state.wbCompareView = "side";
}

test("renderWbResult renders addressable lines with numbers and char-level marks", async () => {
  setupState();
  document.body.innerHTML = '<div data-wb-result></div>';
  await renderWbResult();

  const columns = document.querySelectorAll(".cmp-column");
  assert.equal(columns.length, 2);

  // Every line is addressable: 0-based data-line + visible 1-based number.
  const lines = document.querySelectorAll(".cmp-line");
  assert.ok(lines.length >= 2);
  const first = lines[0];
  assert.equal(first.getAttribute("data-line"), "0");
  assert.ok(first.querySelector(".cmp-line-num"));
  assert.equal(first.querySelector(".cmp-line-num").textContent, "1");

  // Modified line: diff-modify row with exactly one inserted mark (高并发).
  const modifyRows = document.querySelectorAll(".cmp-line.diff-modify");
  assert.equal(modifyRows.length, 2); // one in each column
  const insertMarks = document.querySelectorAll(".diff-char-ins");
  assert.equal(insertMarks.length, 1);
  assert.equal(insertMarks[0].textContent, "高并发");
  assert.equal(document.querySelectorAll(".diff-char-del").length, 0);

  // Unchanged line stays plain in both columns.
  const plainLines = Array.from(lines).filter((line) =>
    line.classList.contains("diff-modify") === false &&
    line.classList.contains("diff-add") === false &&
    line.classList.contains("diff-remove") === false,
  );
  assert.ok(plainLines.length >= 2);
});

test("renderWbResult wires scroll sync between the two columns", async () => {
  setupState();
  document.body.innerHTML = '<div data-wb-result></div>';
  await renderWbResult();

  const columns = document.querySelectorAll(".cmp-column");
  columns[0].scrollTop = 120;
  columns[0].dispatchEvent(new window.Event("scroll"));
  assert.equal(columns[1].scrollTop, 120);

  columns[1].scrollTop = 45;
  columns[1].dispatchEvent(new window.Event("scroll"));
  assert.equal(columns[0].scrollTop, 45);
});

test("renderWbResult preserves scroll positions across side <-> list toggles", async () => {
  setupState();
  state.wbCompareView = "side";
  document.body.innerHTML = '<div data-wb-result></div>';
  await renderWbResult();

  const columns = document.querySelectorAll(".cmp-column");
  assert.equal(columns.length, 2);
  columns[0].scrollTop = 150;
  columns[1].scrollTop = 40;

  // Switch to list: columns disappear but positions must be remembered.
  state.wbCompareView = "list";
  await renderWbResult();
  assert.equal(document.querySelectorAll(".cmp-column").length, 0);

  // Switch back to side: fresh columns restore the saved positions.
  state.wbCompareView = "side";
  await renderWbResult();
  const restored = document.querySelectorAll(".cmp-column");
  assert.equal(restored.length, 2);
  assert.equal(restored[0].scrollTop, 150);
  assert.equal(restored[1].scrollTop, 40);
});
