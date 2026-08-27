import test from "node:test";
import assert from "node:assert/strict";

/* Must be imported first: installs window/document/localStorage globals
 * before events.js (imported transitively by diff-editor.js) evaluates. */
import "./happy-setup.mjs";

import { Window } from "happy-dom";
import {
  bindColumnScrollSync,
  captureColumnScrolls,
  restoreColumnScrolls,
  syncScrollTop,
} from "../../../src/resualign/static/app/diff-editor.js";

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
