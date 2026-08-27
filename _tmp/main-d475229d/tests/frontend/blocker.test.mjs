import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  blockerCountBadge,
  blockerListHtml,
  fetchUrlResultMessage,
} from "../../src/resualign/static/app/format.js";

/* Parse a rendered HTML string and return its body element, so the DOM
 * structure produced by the pure builders can be asserted exactly like
 * the real page would behave after main.js mounts them into the modal. */
function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

/* ------------------------------------------------------------------ */
/* fetchUrlResultMessage: toast copy per contract status               */
/* ------------------------------------------------------------------ */

test("fetchUrlResultMessage maps the four contract statuses", () => {
  assert.equal(fetchUrlResultMessage("created"), "岗位已抓取");
  assert.equal(fetchUrlResultMessage("duplicate"), "已存在相同岗位");
  assert.equal(fetchUrlResultMessage("blocked"), "已加入阻断队列");
  assert.equal(fetchUrlResultMessage("rule_rejected"), "规则拦截");
});

test("fetchUrlResultMessage appends the backend reason for blocked / rule_rejected", () => {
  assert.equal(
    fetchUrlResultMessage("blocked", "需要验证码"),
    "已加入阻断队列：需要验证码",
  );
  assert.equal(
    fetchUrlResultMessage("rule_rejected", "重复岗位"),
    "规则拦截：重复岗位",
  );
});

test("fetchUrlResultMessage tolerates empty reason", () => {
  assert.equal(fetchUrlResultMessage("blocked", ""), "已加入阻断队列");
  assert.equal(fetchUrlResultMessage("blocked", null), "已加入阻断队列");
  assert.equal(fetchUrlResultMessage("rule_rejected", "  "), "规则拦截");
});

test("fetchUrlResultMessage falls back for unknown / missing status", () => {
  assert.equal(fetchUrlResultMessage("queued"), "抓取结果：queued");
  assert.equal(fetchUrlResultMessage(null), "抓取结果：未知");
  assert.equal(fetchUrlResultMessage(undefined), "抓取结果：未知");
  assert.equal(fetchUrlResultMessage(""), "抓取结果：未知");
});

/* ------------------------------------------------------------------ */
/* blockerListHtml: list rendering + escaping                          */
/* ------------------------------------------------------------------ */

const blockers = [
  {
    blocker_id: "b1",
    job_id: null,
    url: "https://example.com/jobs/1",
    title: "后端工程师",
    reason: "页面需要登录",
    category: "login_required",
    status: "pending",
    created_at: 1700000000,
  },
  {
    blocker_id: "b2",
    job_id: null,
    url: "https://example.com/jobs/2",
    title: "前端工程师",
    reason: "",
    category: "",
    status: "pending",
    created_at: 1700000060,
  },
];

test("blockerListHtml renders one item per blocker with both actions", () => {
  const body = bodyFrom(blockerListHtml(blockers));
  const list = body.querySelector("[data-blocker-list]");
  assert.ok(list, "list container is rendered");
  const items = [...list.querySelectorAll("[data-blocker-item]")];
  assert.equal(items.length, 2);

  const first = items[0];
  assert.equal(first.dataset.blockerId, "b1");
  assert.equal(first.querySelector(".blocker-item__title").textContent, "后端工程师");
  assert.ok(
    first.querySelector('.blocker-item__meta').textContent.includes("https://example.com/jobs/1"),
  );
  assert.ok(
    first.querySelector('.blocker-item__meta').textContent.includes("login_required"),
  );
  assert.equal(
    first.querySelector(".blocker-item__reason").textContent,
    "页面需要登录",
  );
  assert.ok(first.querySelector('[data-action="ignore-blocker"][data-id="b1"]'));
  assert.ok(
    first.querySelector('[data-action="toggle-blocker-resolve"][data-id="b1"]'),
  );
  assert.equal(first.querySelector(".badge").textContent, "待处理");
});

test("blockerListHtml omits reason block and category when empty", () => {
  const body = bodyFrom(blockerListHtml([blockers[1]]));
  const item = body.querySelector("[data-blocker-item]");
  assert.equal(item.querySelectorAll(".blocker-item__reason").length, 0);
  assert.equal(item.querySelector(".blocker-item__meta").textContent, "https://example.com/jobs/2");
  assert.ok(!item.textContent.includes("login_required"));
});

test("blockerListHtml escapes url/title/reason/category HTML", () => {
  const hostile = {
    blocker_id: "b<script>",
    job_id: null,
    url: "https://example.com/?q=<script>alert(1)</script>",
    title: '<img src=x onerror=alert(1)>后端',
    reason: "<b>需要</b>登录 & 验证",
    category: "<i>cat</i>",
    status: "pending",
    created_at: 1700000000,
  };
  const body = bodyFrom(blockerListHtml([hostile]));
  assert.equal(body.querySelectorAll("script, img, b, i").length, 0, "no raw tags");
  const item = body.querySelector("[data-blocker-item]");
  assert.equal(item.querySelector(".blocker-item__title").textContent, '<img src=x onerror=alert(1)>后端');
  assert.equal(item.querySelector(".blocker-item__reason").textContent, "<b>需要</b>登录 & 验证");
  /* 属性值在注入时经 esc 转义，happy-dom 解析后 dataset 回到原文，
   * 且不会产生任何真实的 <script> 元素。 */
  assert.equal(item.dataset.blockerId, "b<script>");
  assert.equal(body.querySelector("script"), null);
  assert.equal(body.querySelector("img"), null);
});

test("blockerListHtml renders the resolve form with hidden blocker_id and textarea", () => {
  const body = bodyFrom(blockerListHtml([blockers[0]]));
  const form = body.querySelector("[data-form='blocker-resolve']");
  assert.ok(form, "resolve form exists");
  assert.equal(form.getAttribute("hidden"), "", "resolve form starts hidden");
  assert.equal(form.dataset.id, "b1");
  assert.equal(form.querySelector('input[name="blocker_id"]').value, "b1");
  assert.ok(form.querySelector("textarea[name='manual_text']"));
  assert.equal(
    form.querySelector('button[type="submit"]').textContent,
    "提交补全",
  );
  assert.ok(
    form.querySelector('[data-action="cancel-blocker-resolve"][data-id="b1"]'),
  );
});

test("blockerListHtml shows an empty state for no blockers", () => {
  const body = bodyFrom(blockerListHtml([]));
  assert.ok(body.querySelector("[data-blocker-empty]"));
  assert.equal(body.querySelectorAll("[data-blocker-item]").length, 0);
});

test("blockerListHtml tolerates non-array input", () => {
  const body = bodyFrom(blockerListHtml(null));
  assert.ok(body.querySelector("[data-blocker-empty]"));
  const body2 = bodyFrom(blockerListHtml(undefined));
  assert.ok(body2.querySelector("[data-blocker-empty]"));
});

/* ------------------------------------------------------------------ */
/* blockerCountBadge: pending count badge                              */
/* ------------------------------------------------------------------ */

test("blockerCountBadge returns empty string for zero / negative / null", () => {
  assert.equal(blockerCountBadge(0), "");
  assert.equal(blockerCountBadge(-3), "");
  assert.equal(blockerCountBadge(null), "");
  assert.equal(blockerCountBadge(undefined), "");
});

test("blockerCountBadge renders a button with the pending count", () => {
  const body = bodyFrom(blockerCountBadge(3));
  const button = body.querySelector("button.blocker-badge");
  assert.ok(button, "badge button is rendered");
  assert.equal(button.dataset.action, "open-blockers");
  assert.equal(button.querySelector(".blocker-badge__count").textContent, "3");
  assert.equal(button.getAttribute("aria-label"), "打开抓取阻断队列：3 条待处理");
});

test("blockerCountBadge accepts numeric strings and larger counts", () => {
  assert.ok(blockerCountBadge("2").includes(">2<"));
  assert.ok(blockerCountBadge(12).includes(">12<"));
  assert.ok(blockerCountBadge(100).includes(">100<"));
});
