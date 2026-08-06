import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  MODAL_OPEN_CLASS,
  collectFocusables,
  focusInitial,
  isFocusable,
  lockBodyScroll,
  nextFocusIndex,
  restoreFocus,
  trapTabKey,
  unlockBodyScroll,
} from "../../../src/resualign/static/app/focus-trap.js";

/** Mirrors the structure showModal builds in events.js. */
function dialogHtml() {
  return `
    <div class="modal-backdrop">
      <div class="modal">
        <h3>标题</h3>
        <input id="in1">
        <button id="b1">取消</button>
        <button id="b2">保存</button>
        <select id="s1"><option>草稿</option></select>
        <textarea id="t1"></textarea>
        <a id="l1" href="#x">链接</a>
        <input id="in-disabled" disabled>
        <input id="in-hidden" type="hidden">
        <div hidden><button id="b-hidden">隐藏按钮</button></div>
        <div aria-hidden="true"><button id="b-aria">aria 隐藏</button></div>
        <div tabindex="-1" id="neg">负 tabindex</div>
      </div>
    </div>`;
}

function windowWithDialog() {
  const window = new Window();
  window.document.body.innerHTML = dialogHtml();
  return window;
}

function tabEvent(window, shiftKey = false) {
  return new window.KeyboardEvent("keydown", {
    key: "Tab",
    shiftKey,
    cancelable: true,
  });
}

/* ------------------------------------------------------------------ */
/* nextFocusIndex (pure tab-order math)                                */
/* ------------------------------------------------------------------ */

test("nextFocusIndex advances forward with wraparound", () => {
  assert.equal(nextFocusIndex(0, 3, false), 1);
  assert.equal(nextFocusIndex(1, 3, false), 2);
  assert.equal(nextFocusIndex(2, 3, false), 0);
});

test("nextFocusIndex moves backward with wraparound", () => {
  assert.equal(nextFocusIndex(0, 3, true), 2);
  assert.equal(nextFocusIndex(1, 3, true), 0);
  assert.equal(nextFocusIndex(2, 3, true), 1);
});

test("nextFocusIndex starts at first/last when current is outside the list", () => {
  assert.equal(nextFocusIndex(-1, 3, false), 0);
  assert.equal(nextFocusIndex(-1, 3, true), 2);
  assert.equal(nextFocusIndex(9, 3, false), 0);
});

test("nextFocusIndex returns -1 for an empty list", () => {
  assert.equal(nextFocusIndex(0, 0, false), -1);
  assert.equal(nextFocusIndex(-1, 0, true), -1);
});

/* ------------------------------------------------------------------ */
/* isFocusable / collectFocusables                                     */
/* ------------------------------------------------------------------ */

test("isFocusable accepts enabled, visible, standard controls", () => {
  const window = new Window();
  const document = window.document;
  document.body.innerHTML = `<input id="a"><button id="b">x</button>`;
  assert.equal(isFocusable(document.getElementById("a")), true);
  assert.equal(isFocusable(document.getElementById("b")), true);
});

test("isFocusable rejects disabled, hidden and aria-hidden nodes", () => {
  const window = new Window();
  const document = window.document;
  document.body.innerHTML = `
    <input id="a" disabled>
    <input id="b" type="hidden">
    <button id="c" hidden>隐藏</button>
    <div aria-hidden="true"><button id="d">aria</button></div>
    <button id="e">可用</button>`;
  assert.equal(isFocusable(document.getElementById("a")), false);
  assert.equal(isFocusable(document.getElementById("b")), false);
  assert.equal(isFocusable(document.getElementById("c")), false);
  assert.equal(isFocusable(document.getElementById("d")), false);
  assert.equal(isFocusable(document.getElementById("e")), true);
  assert.equal(isFocusable(null), false);
});

test("collectFocusables returns enabled visible elements in document order", () => {
  const window = windowWithDialog();
  const backdrop = window.document.querySelector(".modal-backdrop");
  const ids = collectFocusables(backdrop).map((node) => node.id);
  assert.deepEqual(ids, ["in1", "b1", "b2", "s1", "t1", "l1"]);
  // disabled / type=hidden / [hidden] / aria-hidden / tabindex=-1 are out
  assert.equal(ids.includes("in-disabled"), false);
  assert.equal(ids.includes("in-hidden"), false);
  assert.equal(ids.includes("b-hidden"), false);
  assert.equal(ids.includes("b-aria"), false);
  assert.equal(ids.includes("neg"), false);
});

test("collectFocusables tolerates null or empty roots", () => {
  assert.deepEqual(collectFocusables(null), []);
  const window = new Window();
  assert.deepEqual(
    collectFocusables(window.document.querySelector(".modal-backdrop")),
    [],
  );
});

/* ------------------------------------------------------------------ */
/* focusInitial                                                        */
/* ------------------------------------------------------------------ */

test("focusInitial focuses the first focusable element", () => {
  const window = windowWithDialog();
  focusInitial(window.document.querySelector(".modal-backdrop"));
  assert.equal(window.document.activeElement.id, "in1");
});

test("focusInitial is a no-op when the dialog has no focusables", () => {
  const window = new Window();
  const root = window.document.createElement("div");
  root.innerHTML = `<h3>只有标题</h3>`;
  window.document.body.append(root);
  window.document.body.focus();
  focusInitial(root);
  assert.equal(window.document.activeElement, window.document.body);
});

/* ------------------------------------------------------------------ */
/* trapTabKey                                                          */
/* ------------------------------------------------------------------ */

test("trapTabKey ignores non-Tab keys", () => {
  const window = windowWithDialog();
  const backdrop = window.document.querySelector(".modal-backdrop");
  const event = new window.KeyboardEvent("keydown", {
    key: "ArrowDown",
    cancelable: true,
  });
  trapTabKey(backdrop, event, window.document.activeElement);
  assert.equal(event.defaultPrevented, false);
});

test("trapTabKey wraps Tab from the last element to the first", () => {
  const window = windowWithDialog();
  const backdrop = window.document.querySelector(".modal-backdrop");
  const last = window.document.getElementById("l1");
  last.focus();
  const event = tabEvent(window);
  trapTabKey(backdrop, event, window.document.activeElement);
  assert.equal(event.defaultPrevented, true);
  assert.equal(window.document.activeElement.id, "in1");
});

test("trapTabKey wraps Shift+Tab from the first element to the last", () => {
  const window = windowWithDialog();
  const backdrop = window.document.querySelector(".modal-backdrop");
  window.document.getElementById("in1").focus();
  const event = tabEvent(window, true);
  trapTabKey(backdrop, event, window.document.activeElement);
  assert.equal(event.defaultPrevented, true);
  assert.equal(window.document.activeElement.id, "l1");
});

test("trapTabKey pulls focus back in when it escaped the dialog", () => {
  const window = windowWithDialog();
  const backdrop = window.document.querySelector(".modal-backdrop");
  window.document.body.focus();
  const forward = tabEvent(window);
  trapTabKey(backdrop, forward, window.document.activeElement);
  assert.equal(forward.defaultPrevented, true);
  assert.equal(window.document.activeElement.id, "in1");

  window.document.body.focus();
  const backward = tabEvent(window, true);
  trapTabKey(backdrop, backward, window.document.activeElement);
  assert.equal(backward.defaultPrevented, true);
  assert.equal(window.document.activeElement.id, "l1");
});

test("trapTabKey allows Tab between middle elements without interference", () => {
  const window = windowWithDialog();
  const backdrop = window.document.querySelector(".modal-backdrop");
  window.document.getElementById("b1").focus();
  const event = tabEvent(window);
  trapTabKey(backdrop, event, window.document.activeElement);
  assert.equal(event.defaultPrevented, false);
});

test("trapTabKey is a safe no-op on empty dialogs and bad input", () => {
  const window = new Window();
  const root = window.document.createElement("div");
  root.innerHTML = `<h3>空弹窗</h3>`;
  window.document.body.append(root);
  const event = tabEvent(window);
  trapTabKey(root, event, window.document.activeElement);
  assert.equal(event.defaultPrevented, false);
  trapTabKey(null, event, window.document.activeElement);
  trapTabKey(root, null, window.document.activeElement);
  trapTabKey(root, { key: "Tab" }, window.document.activeElement);
});

/* ------------------------------------------------------------------ */
/* restoreFocus                                                        */
/* ------------------------------------------------------------------ */

test("restoreFocus returns focus to a still-connected trigger", () => {
  const window = new Window();
  const document = window.document;
  document.body.innerHTML = `<button id="trigger">打开</button>`;
  const trigger = document.getElementById("trigger");
  trigger.focus();
  restoreFocus(trigger);
  assert.equal(document.activeElement, trigger);
});

test("restoreFocus skips triggers that were removed from the document", () => {
  const window = new Window();
  const document = window.document;
  const trigger = document.createElement("button");
  document.body.append(trigger);
  trigger.focus();
  trigger.remove();
  // No crash, and focus stays put (body) instead of jumping to a dead node.
  restoreFocus(trigger);
  assert.equal(document.activeElement, document.body);
});

test("restoreFocus tolerates null", () => {
  restoreFocus(null);
});

/* ------------------------------------------------------------------ */
/* Body scroll lock class management (modal-open)                      */
/* ------------------------------------------------------------------ */

test("lockBodyScroll adds the modal-open class to the body", () => {
  const window = new Window();
  const body = window.document.body;
  assert.equal(body.classList.contains(MODAL_OPEN_CLASS), false);
  lockBodyScroll(body);
  assert.equal(body.classList.contains(MODAL_OPEN_CLASS), true);
});

test("unlockBodyScroll removes the modal-open class", () => {
  const window = new Window();
  const body = window.document.body;
  lockBodyScroll(body);
  unlockBodyScroll(body);
  assert.equal(body.classList.contains(MODAL_OPEN_CLASS), false);
});

test("unlockBodyScroll is idempotent and tolerates a missing body", () => {
  const window = new Window();
  const body = window.document.body;
  unlockBodyScroll(body);
  unlockBodyScroll(body);
  assert.equal(body.classList.contains(MODAL_OPEN_CLASS), false);
  lockBodyScroll(null);
  unlockBodyScroll(null);
});

test("modal-open class round-trips through the show/close lifecycle", () => {
  // Mirrors the events.js sequence: showModal locks, closeModal unlocks.
  const window = new Window();
  const body = window.document.body;
  lockBodyScroll(body);
  assert.equal(body.classList.contains(MODAL_OPEN_CLASS), true);
  unlockBodyScroll(body);
  assert.equal(body.classList.contains(MODAL_OPEN_CLASS), false);
});
