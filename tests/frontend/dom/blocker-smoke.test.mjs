/* Sprint 3 browser-smoke substitute: boot the real main.js in happy-dom with
 * a mocked fetch (backend /api/jobs/fetch-url + /api/blockers not ready yet),
 * then verify the setCanvasRenderHook mounts the 抓取 Bar + blocker badge and
 * the data-action flows (fetch-url toast, open-blockers modal, ignore, resolve).
 *
 * The shell mirrors index.html so the real module graph (events.js, theme.js,
 * command-panel.js, split-canvas.js, format.js) boots with its normal globals.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost:8011/#/jobs" });
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
globalThis.FormData = window.FormData;
/* showModal() / focus-trap use these browser constructors; expose them from
 * the happy-dom Window so the real module graph runs unmodified. */
globalThis.HTMLElement = window.HTMLElement;
globalThis.Element = window.Element;
globalThis.Node = window.Node;
globalThis.HTMLInputElement = window.HTMLInputElement;
globalThis.HTMLFormElement = window.HTMLFormElement;

document.body.innerHTML = `
  <div class="app-main">
    <main id="app"></main>
  </div>
  <div id="print-root"></div>
  <div id="toast-region"></div>
`;

/* ---- fetch mock: contract-shaped responses ---- */

const MOCK_JOBS = [
  {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    location: "上海",
    status: "draft",
    jd_text: "Python / FastAPI",
    salary_min: 20000,
    salary_max: 30000,
  },
];

const MOCK_BLOCKERS = [
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
    reason: "需要验证码",
    category: "captcha",
    status: "pending",
    created_at: 1700000060,
  },
];

const calls = { fetchUrl: [], blockers: 0, ignore: [], resolve: [] };
let fetchUrlResult = { status: "created", job_id: "j9" };

function jsonBody(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

async function mockFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const url = String(path);
  if (method === "GET" && url.startsWith("/api/auth/me")) return jsonBody({ ok: true });
  if (method === "GET" && url.startsWith("/api/settings")) {
    return jsonBody({
      classification_vocabulary: {
        job_functions: ["后端", "前端"],
        seniorities: ["初级", "高级"],
        statuses: ["未投递", "已投递"],
      },
    });
  }
  if (method === "GET" && url.startsWith("/api/jobs")) return jsonBody(MOCK_JOBS);
  if (method === "GET" && url.startsWith("/api/master-resumes")) return jsonBody([]);
  if (method === "GET" && url.startsWith("/api/blockers")) {
    calls.blockers += 1;
    return jsonBody(MOCK_BLOCKERS);
  }
  if (method === "POST" && url.startsWith("/api/jobs/fetch-url")) {
    calls.fetchUrl.push(JSON.parse(options.body || "{}"));
    return jsonBody(fetchUrlResult);
  }
  if (method === "POST" && url.startsWith("/api/blockers/")) {
    if (url.endsWith("/ignore")) {
      calls.ignore.push(url);
      return jsonBody(null, 204);
    }
    if (url.endsWith("/resolve")) {
      calls.resolve.push({ url, body: JSON.parse(options.body || "{}") });
      return jsonBody({ status: "resolved", job_id: "j9" });
    }
  }
  return jsonBody({ detail: `no mock for ${method} ${url}` }, 404);
}
globalThis.fetch = mockFetch;

/* Boot main.js AFTER globals + shell are in place (module scope runs boot()). */
await import("../../../src/resualign/static/app/main.js");

/* ---- helpers ---- */

async function waitFor(fn, label, timeoutMs = 3000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = fn();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  throw new Error(`waitFor timeout: ${label}`);
}

function clickButton(selector) {
  const button = document.querySelector(selector);
  assert.ok(button, `button found: ${selector}`);
  button.click();
  return button;
}

/* ---- smoke: board mounts fetch bar + blocker badge ---- */

test("Sprint3 smoke: jobs board mounts fetch bar and pending blocker badge", async () => {
  await waitFor(
    () => document.querySelector("[data-fetch-url-bar]"),
    "fetch bar mounted by setCanvasRenderHook",
  );

  const input = document.querySelector("[data-fetch-url]");
  assert.ok(input, "url input exists");
  const button = document.querySelector('[data-action="fetch-job-url"]');
  assert.ok(button, "自动抓取 button exists");
  assert.equal(button.textContent.trim(), "自动抓取");

  const badgeMount = document.querySelector("[data-blocker-badge]");
  assert.ok(badgeMount, "blocker badge mount exists");
  await waitFor(
    () => document.querySelector(".blocker-badge"),
    "badge renders when pending > 0",
  );
  assert.equal(
    document.querySelector(".blocker-badge__count").textContent,
    "2",
    "badge count matches pending blockers",
  );
  assert.ok(calls.blockers >= 1, "GET /api/blockers was called");
});

test("Sprint3 smoke: fetch-url created shows toast and refreshes the board", async () => {
  const input = document.querySelector("[data-fetch-url]");
  assert.ok(input);
  input.value = "https://example.com/jobs/3";
  clickButton('[data-action="fetch-job-url"]');

  await waitFor(
    () =>
      [...document.querySelectorAll(".toast")].some((node) =>
        node.textContent.includes("岗位已抓取"),
      ),
    "created toast",
  );
  assert.equal(calls.fetchUrl.length, 1);
  assert.equal(calls.fetchUrl[0].url, "https://example.com/jobs/3");
  assert.equal(input.value, "", "input cleared after created");
  await waitFor(
    () => document.querySelector("[data-fetch-url-bar]"),
    "board re-rendered after render()",
  );
});

test("Sprint3 smoke: fetch-url blocked shows reason toast and badge stays", async () => {
  fetchUrlResult = { status: "blocked", blocker_id: "b3", reason: "需要验证码" };
  const input = document.querySelector("[data-fetch-url]");
  input.value = "https://example.com/jobs/4";
  clickButton('[data-action="fetch-job-url"]');
  await waitFor(
    () =>
      [...document.querySelectorAll(".toast")].some((node) =>
        node.textContent.includes("已加入阻断队列：需要验证码"),
      ),
    "blocked toast with reason",
  );
  assert.equal(calls.fetchUrl.length, 2);
});

test("Sprint3 smoke: blocker modal ignores one and resolves the other", async () => {
  /* badge re-mounted after the render() above; open the modal */
  await waitFor(
    () => document.querySelector(".blocker-badge"),
    "badge visible again",
  );
  clickButton(".blocker-badge");

  const backdrop = await waitFor(
    () => document.querySelector(".modal-backdrop"),
    "modal opened",
  );
  assert.equal(
    backdrop.querySelector("h3").textContent,
    "抓取阻断队列",
  );
  const items = [...backdrop.querySelectorAll("[data-blocker-item]")];
  assert.equal(items.length, 2, "two blockers listed");
  assert.ok(
    backdrop.querySelector('.blocker-item__meta').textContent.includes("https://example.com/jobs/1"),
  );

  /* 忽略 b1 */
  clickButton('[data-action="ignore-blocker"][data-id="b1"]');
  await waitFor(
    () => document.querySelectorAll("[data-blocker-item]").length === 1,
    "ignored item removed from modal",
  );
  assert.equal(calls.ignore[0], "/api/blockers/b1/ignore");
  assert.equal(
    document.querySelector(".blocker-badge__count").textContent,
    "1",
    "badge count decremented",
  );

  /* 手动补全 b2 */
  clickButton('[data-action="toggle-blocker-resolve"][data-id="b2"]');
  const form = backdrop.querySelector("[data-form='blocker-resolve']");
  assert.ok(form && !form.hidden, "resolve form expanded");
  const textarea = form.querySelector("textarea[name='manual_text']");
  textarea.value = "岗位职责：负责前端架构...";
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));

  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "modal closed after resolve",
  );
  assert.equal(calls.resolve.length, 1);
  assert.ok(
    calls.resolve[0].url.endsWith("/api/blockers/b2/resolve"),
    "blocker_id travels in the URL per the contract",
  );
  assert.equal(calls.resolve[0].body.manual_text, "岗位职责：负责前端架构...");
  await waitFor(
    () =>
      [...document.querySelectorAll(".toast")].some((node) =>
        node.textContent.includes("已手动补全并入库存档"),
      ),
    "resolve success toast",
  );
});
