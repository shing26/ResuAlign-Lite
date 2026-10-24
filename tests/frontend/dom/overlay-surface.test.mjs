/* SH-09 后续（2026-10-25）：命令面板等非 modal 浮层的背景隔离 + 焦点归还。
 * openOverlaySurface / closeOverlaySurface 与 showModal 共享同一套机制；
 * happy-dom 不支持原生 inert，走 aria-hidden 降级分支——两条路径的
 * 行为契约一致（背景不可达读屏、关闭焦点回触发元素）。 */

import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window();
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Element = window.Element;
globalThis.Node = window.Node;

const { closeOverlaySurface, openOverlaySurface } = await import(
  "../../../src/resualign/static/app/events.js"
);

function shellHtml() {
  return `
    <button id="trigger" type="button">⌘K</button>
    <aside class="app-rail"></aside>
    <header class="topbar"></header>
    <main id="app-router-view"></main>`;
}

function awaitTick() {
  return new Promise((resolve) => setTimeout(resolve, 5));
}

function backgroundHidden(node) {
  /* happy-dom 新版支持原生 inert（优先分支）；旧版走 aria-hidden 降级。
   * 两条路径的契约一致：背景对 Tab/读屏不可达。 */
  return node.inert === true || node.getAttribute("aria-hidden") === "true";
}

test("openOverlaySurface isolates the background from screen readers", () => {
  document.body.innerHTML = shellHtml();
  document.getElementById("trigger").focus();
  openOverlaySurface();
  assert.equal(backgroundHidden(document.querySelector(".app-rail")), true);
  assert.equal(backgroundHidden(document.querySelector(".topbar")), true);
  assert.equal(backgroundHidden(document.getElementById("app-router-view")), true);
});

test("closeOverlaySurface restores the background and returns focus to the trigger", async () => {
  document.body.innerHTML = shellHtml();
  const trigger = document.getElementById("trigger");
  trigger.focus();
  openOverlaySurface();
  closeOverlaySurface();
  assert.equal(
    backgroundHidden(document.querySelector(".app-rail")),
    false,
    "背景 inert/aria-hidden 应在关闭时同步解除",
  );
  await awaitTick();
  assert.equal(
    document.activeElement,
    trigger,
    "焦点应回到打开浮层时的触发元素",
  );
});

test("closeOverlaySurface falls back to the route container when the trigger is gone", async () => {
  document.body.innerHTML = shellHtml();
  const trigger = document.getElementById("trigger");
  trigger.focus();
  openOverlaySurface();
  /* 关闭前触发元素被重渲染替换（命令执行后导航的典型场景）。 */
  trigger.remove();
  closeOverlaySurface();
  await awaitTick();
  const main = document.getElementById("app-router-view");
  assert.equal(document.activeElement, main, "回退到路由容器而非 body");
});

/* 注：浮层的 no-op 保障在调用方（closeCommandPanel 的 palette.hidden
 * 守卫）——overlay 层的重复 close 会再调度一次「回退路由容器」的焦点
 * 恢复，这是设计内行为，不在此断言。 */
