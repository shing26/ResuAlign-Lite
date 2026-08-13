/* Delivery-loop DOM smoke: boots the real main.js in happy-dom and verifies
 * the #23 source-link / record-application contract end to end:
 *   1. job detail modal exposes and saves source_url;
 *   2. the board card then renders 去投递 ↗;
 *   3. open-source-url opens the original JD URL;
 *   4. the same record-application action runs from the job detail modal.
 */

import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

const window = new Window({ url: "http://localhost:8011/#/jobs" });
globalThis.window = window;
globalThis.document = window.document;
globalThis.localStorage = window.localStorage;
globalThis.FormData = window.FormData;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Element = window.Element;
globalThis.Node = window.Node;
globalThis.HTMLInputElement = window.HTMLInputElement;
globalThis.HTMLFormElement = window.HTMLFormElement;

document.body.innerHTML = `
  <div class="app-main">
    <main id="app-router-view"></main>
  </div>
  <div id="print-root"></div>
  <div id="toast-region"></div>
`;

const NEW_URL = "https://example.com/jobs/j2-original";
const MOCK_JOBS = [
  {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    location: "上海",
    status: "draft",
    jd_text: "Python / FastAPI",
    source_url: "https://example.com/jobs/1",
    salary_min: 20000,
    salary_max: 30000,
  },
  {
    job_id: "j2",
    title: "前端工程师",
    company: "Beta",
    location: "北京",
    status: "draft",
    jd_text: "React / TypeScript",
    source_url: "",
    salary_min: 18000,
    salary_max: 28000,
  },
];

const calls = { patches: [], opens: [] };

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
  if (method === "GET" && url.startsWith("/api/master-resumes")) return jsonBody([]);
  if (method === "GET" && url.startsWith("/api/blockers")) return jsonBody([]);
  if (method === "PATCH" && url.startsWith("/api/jobs/")) {
    const jobId = url.split("/").pop();
    const body = JSON.parse(options.body || "{}");
    calls.patches.push({ url, body });
    const job = MOCK_JOBS.find((item) => item.job_id === jobId);
    if (job) Object.assign(job, body);
    return jsonBody(job || {});
  }
  if (method === "GET" && url.startsWith("/api/jobs/")) {
    const jobId = url.split("/").pop();
    const job = MOCK_JOBS.find((item) => item.job_id === jobId);
    return jsonBody(job || null);
  }
  if (method === "GET" && url.startsWith("/api/jobs")) return jsonBody(MOCK_JOBS);
  return jsonBody({ detail: `no mock for ${method} ${url}` }, 404);
}
globalThis.fetch = mockFetch;

/* Boot main.js after globals + shell are in place. */
await import("../../../src/resualign/static/app/main.js");

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

test("delivery loop: save source_url, open original JD, record application", async () => {
  const goJ1 = await waitFor(
    () =>
      document.querySelector(
        '[data-action="open-source-url"][data-url="https://example.com/jobs/1"]',
      ),
    "job card with source_url renders go-to-apply",
  );
  assert.match(goJ1.textContent, /去投递/);

  /* 1. 岗位详情弹窗保存 source_url。 */
  clickButton('[data-action="open-job-timeline"][data-id="j2"]');
  const backdrop = await waitFor(
    () => document.querySelector(".modal-backdrop"),
    "job detail modal opened",
  );
  const linkInput = backdrop.querySelector('input[name="source_url"]');
  assert.ok(linkInput, "source_url input exists in detail modal");
  assert.ok(
    backdrop.querySelector('[data-action="record-application"][data-id="j2"]'),
    "detail modal record button carries the job id",
  );
  linkInput.value = NEW_URL;
  const form = backdrop.querySelector("[data-form='job-detail-edit']");
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));

  await waitFor(
    () =>
      calls.patches.some(
        (call) =>
          call.url === "/api/jobs/j2" && call.body.source_url === NEW_URL,
      ),
    "detail save PATCH carries source_url",
  );
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "detail modal closes after save",
  );

  /* 2. 卡片随后显示去投递，并打开原文。 */
  const goButton = await waitFor(
    () => document.querySelector(`[data-action="open-source-url"][data-url="${NEW_URL}"]`),
    "job card shows go-to-apply after source_url saved",
  );
  globalThis.window.open = (url, name, features) => {
    calls.opens.push({ url, name, features });
    return null;
  };
  goButton.click();
  assert.equal(calls.opens.length, 1, "open-source-url calls window.open");
  assert.equal(calls.opens[0].url, NEW_URL);
  assert.equal(calls.opens[0].name, "_blank");

  /* 3. 同一 record-application action 从详情弹窗记录投递。 */
  clickButton('[data-action="open-job-timeline"][data-id="j2"]');
  const modal = await waitFor(
    () => document.querySelector(".modal-backdrop"),
    "job detail modal reopened",
  );
  modal.querySelector('[data-action="record-application"][data-id="j2"]').click();
  await waitFor(
    () =>
      calls.patches.some(
        (call) =>
          call.url === "/api/jobs/j2" &&
          call.body.status === "applied" &&
          Boolean(call.body.applied_at),
      ),
    "record-application PATCHes applied with today",
  );
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "record-application closes the detail modal",
  );
});
