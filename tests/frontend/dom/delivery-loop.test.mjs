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
  {
    job_id: "j3",
    title: "数据工程师",
    company: "Gamma",
    location: "深圳",
    status: "draft",
    jd_text: "SQL / Python",
    source_url: "",
    salary_min: 20000,
    salary_max: 35000,
  },
  {
    job_id: "j4",
    title: "产品经理",
    company: "Delta",
    location: "广州",
    status: "draft",
    jd_text: "产品规划",
    source_url: "",
    salary_min: 15000,
    salary_max: 25000,
  },
  {
    job_id: "j5",
    title: "设计工程师",
    company: "Epsilon",
    location: "杭州",
    status: "interview",
    jd_text: "交互设计",
    source_url: "",
    salary_min: 20000,
    salary_max: 30000,
  },
];

const DEEP_JOB = {
  job_id: "deep",
  title: "Deep 岗位",
  company: "Zeta",
  location: "成都",
  status: "offer",
  jd_text: "Deep learning",
  source_url: "",
  salary_min: 25000,
  salary_max: 40000,
};

const calls = { patches: [], opens: [], gets: [] };

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
    calls.gets.push({ url });
    if (jobId === DEEP_JOB.job_id) return jsonBody(DEEP_JOB);
    const job = MOCK_JOBS.find((item) => item.job_id === jobId);
    return jsonBody(job || null);
  }
  if (method === "GET" && url.startsWith("/api/jobs")) {
    calls.gets.push({ url });
    return jsonBody(MOCK_JOBS);
  }
  return jsonBody({ detail: `no mock for ${method} ${url}` }, 404);
}
globalThis.fetch = mockFetch;

const { state } = await import("../../../src/resualign/static/app/events.js");

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

test("followup modal: schedule next step through lifecycle PATCH", async () => {
  const card = document.querySelector('.board-card[data-job-id="j3"]');
  assert.ok(card, "j3 card exists");
  card.querySelector(".board-more summary").click();
  clickButton('[data-action="open-job-followup"][data-id="j3"]');

  const modal = await waitFor(
    () => document.querySelector(".modal-backdrop"),
    "followup modal opened",
  );
  const form = modal.querySelector("[data-form='job-followup']");
  assert.ok(form, "followup form exists");
  assert.match(form.outerHTML, /<option value="interview" selected/);
  form.querySelector('[name="status"]').value = "interview";
  form.querySelector('[name="interview_stage"]').value = "二面";
  form.querySelector('[name="next_step"]').value = "准备二面";
  form.querySelector('[name="next_step_due_at"]').value = "2026-08-15T10:00";
  form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true }));

  await waitFor(
    () =>
      calls.patches.some(
        (call) =>
          call.url === "/api/jobs/j3" &&
          call.body.status === "interview" &&
          call.body.next_step === "准备二面" &&
          call.body.next_step_due_at === "2026-08-15T10:00" &&
          call.body.interview_stage === "二面",
      ),
    "followup PATCH carries status and follow-up fields",
  );
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "followup modal closes after save",
  );
  await waitFor(
    () => document.body.textContent.includes("准备二面"),
    "board card shows the saved next step",
  );
});

test("terminal confirm: offer select confirms before PATCH", async () => {
  const select = document.querySelector(
    '.board-card[data-job-id="j4"] [data-board-status]',
  );
  assert.ok(select, "j4 status select exists");
  select.value = "offer";
  select.dispatchEvent(new window.Event("change", { bubbles: true }));

  const form = await waitFor(
    () => document.querySelector("[data-form='job-terminal-confirm']"),
    "terminal confirm modal opened",
  );
  assert.equal(form.querySelector('[name="status"]').value, "offer");
  const before = calls.patches.filter(
    (call) => call.url === "/api/jobs/j4" && call.body.status === "offer",
  ).length;
  form.querySelector('[name="offer_at"]').value = "2026-08-22";
  form.querySelector('[name="notes"]').value = "已收 offer";
  form.dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );

  await waitFor(
    () =>
      calls.patches.some(
        (call) =>
          call.url === "/api/jobs/j4" &&
          call.body.status === "offer" &&
          call.body.offer_at === "2026-08-22" &&
          call.body.notes === "已收 offer",
      ),
    "terminal PATCH carries offer date and notes",
  );
  assert.equal(
    calls.patches.filter(
      (call) => call.url === "/api/jobs/j4" && call.body.status === "offer",
    ).length,
    before + 1,
  );
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "confirm modal closes after save",
  );
  await waitFor(
    () => {
      const current = document.querySelector(
        '.board-card[data-job-id="j4"] [data-board-status]',
      );
      return current && current.value === "offer";
    },
    "board card reflects offer after rerender",
  );
});

test("terminal confirm: cancel keeps the previous status", async () => {
  const select = document.querySelector(
    '.board-card[data-job-id="j5"] [data-board-status]',
  );
  assert.ok(select, "j5 status select exists");
  select.value = "interview";
  assert.equal(select.value, "interview");
  select.value = "withdrawn";
  select.dispatchEvent(new window.Event("change", { bubbles: true }));

  const modal = await waitFor(
    () => document.querySelector(".modal-backdrop"),
    "withdrawn confirm modal opened",
  );
  const before = calls.patches.filter(
    (call) => call.url === "/api/jobs/j5" && call.body.status === "withdrawn",
  ).length;
  modal.querySelector('[data-action="cancel-status-back"]').click();
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "cancel closes the confirm modal",
  );
  assert.equal(
    calls.patches.filter(
      (call) => call.url === "/api/jobs/j5" && call.body.status === "withdrawn",
    ).length,
    before,
  );
  assert.equal(select.value, "interview");
});

test("terminal confirm: drag to withdrawn opens the confirm modal", async () => {
  const card = document.querySelector('.board-card[data-job-id="j5"]');
  assert.ok(card, "j5 card exists");
  const select = card.querySelector("[data-board-status]");
  select.value = "interview";
  const dragStart = new window.Event("dragstart", { bubbles: true });
  dragStart.dataTransfer = {
    setData() {},
    effectAllowed: "",
  };
  card.dispatchEvent(dragStart);

  const drop = new window.Event("drop", { bubbles: true, cancelable: true });
  drop.dataTransfer = { getData: () => "j5" };
  const column = document.querySelector(
    '.board-column[data-status="withdrawn"]',
  );
  assert.ok(column, "withdrawn column exists");
  column.dispatchEvent(drop);

  const form = await waitFor(
    () => document.querySelector("[data-form='job-terminal-confirm']"),
    "drag terminal confirm modal opened",
  );
  assert.equal(form.querySelector('[name="status"]').value, "withdrawn");
  form.querySelector('[data-action="cancel-status-back"]').click();
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "drag confirm cancel closes the modal",
  );
  assert.equal(select.value, "interview");
});

test("terminal confirm: job detail modal routes through confirm", async () => {
  clickButton('[data-action="open-job-timeline"][data-id="j5"]');
  const detail = await waitFor(
    () => document.querySelector(".modal-backdrop"),
    "job detail modal opened",
  );
  const form = detail.querySelector("[data-form='job-detail-edit']");
  assert.ok(form, "job detail form exists");
  form.querySelector('[name="status"]').value = "offer";
  form.querySelector('[name="offer_at"]').value = "2026-08-23T09:00";
  form.querySelector('[name="notes"]').value = "最终 offer";
  form.dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );

  const confirmForm = await waitFor(
    () => document.querySelector("[data-form='job-terminal-confirm']"),
    "terminal confirm modal opened from detail form",
  );
  assert.equal(confirmForm.querySelector('[name="offer_at"]').value, "2026-08-23");
  assert.equal(confirmForm.querySelector('[name="notes"]').value, "最终 offer");
  confirmForm.dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );

  await waitFor(
    () =>
      calls.patches.some(
        (call) =>
          call.url === "/api/jobs/j5" &&
          call.body.status === "offer" &&
          call.body.offer_at === "2026-08-23" &&
          call.body.notes === "最终 offer",
      ),
    "detail terminal PATCH carries date and notes",
  );
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "detail terminal flow closes all modals",
  );
});

test("review fix: job-edit fetches a deep-linked job before backward confirm", async () => {
  const form = document.createElement("form");
  form.dataset.form = "job-edit";
  form.innerHTML = `
    <input type="hidden" name="job_id" value="${DEEP_JOB.job_id}">
    <input type="hidden" name="title" value="${DEEP_JOB.title}">
    <input type="hidden" name="jd_text" value="${DEEP_JOB.jd_text}">
    <select name="status"><option value="interview" selected>面试中</option></select>
  `;
  document.body.append(form);

  const before = calls.gets.filter(
    (call) => call.url === `/api/jobs/${DEEP_JOB.job_id}`,
  ).length;
  form.dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );

  await waitFor(
    () => document.querySelector('[data-action="confirm-status-back"]'),
    "backward confirm opened for deep-linked job",
  );
  assert.equal(
    calls.gets.filter(
      (call) => call.url === `/api/jobs/${DEEP_JOB.job_id}`,
    ).length,
    before + 1,
  );

  document.querySelector('[data-action="cancel-status-back"]').click();
  await waitFor(
    () => document.querySelector("[data-form='job-edit']"),
    "cancel reopens the job editor",
  );
  assert.match(
    document.querySelector("[data-form='job-edit']").outerHTML,
    /Deep 岗位/,
  );
  document.querySelector("[data-form='job-edit'] [data-action='close-modal']").click();
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "job editor closes after review test",
  );
});

test("review fix: open-job-detail fetches a deep-linked job", async () => {
  const button = document.createElement("button");
  button.dataset.action = "open-job-detail";
  button.dataset.id = DEEP_JOB.job_id;
  document.body.append(button);

  const before = calls.gets.filter(
    (call) => call.url === `/api/jobs/${DEEP_JOB.job_id}`,
  ).length;
  button.click();

  await waitFor(
    () => document.querySelector("[data-form='job-detail-edit']"),
    "job detail modal opened via fetch fallback",
  );
  assert.equal(
    calls.gets.filter(
      (call) => call.url === `/api/jobs/${DEEP_JOB.job_id}`,
    ).length,
    before + 1,
  );
  document.querySelector("[data-form='job-detail-edit'] [data-action='close-modal']").click();
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "detail modal closes after review test",
  );
});

test("review fix: job-detail-edit fetches a deep-linked job before backward confirm", async () => {
  const form = document.createElement("form");
  form.dataset.form = "job-detail-edit";
  form.innerHTML = `
    <input type="hidden" name="job_id" value="${DEEP_JOB.job_id}">
    <select name="status"><option value="interview" selected>面试中</option></select>
  `;
  document.body.append(form);

  const before = calls.gets.filter(
    (call) => call.url === `/api/jobs/${DEEP_JOB.job_id}`,
  ).length;
  form.dispatchEvent(
    new window.Event("submit", { bubbles: true, cancelable: true }),
  );

  await waitFor(
    () => document.querySelector('[data-action="confirm-status-back"]'),
    "backward confirm opened from deep-linked detail form",
  );
  assert.equal(
    calls.gets.filter(
      (call) => call.url === `/api/jobs/${DEEP_JOB.job_id}`,
    ).length,
    before + 1,
  );

  document.querySelector('[data-action="cancel-status-back"]').click();
  await waitFor(
    () => document.querySelector("[data-form='job-detail-edit']"),
    "cancel reopens the job detail form",
  );
  document.querySelector("[data-form='job-detail-edit'] [data-action='close-modal']").click();
  await waitFor(
    () => !document.querySelector(".modal-backdrop"),
    "detail form closes after review test",
  );
});

test("review fix: Escape and backdrop close cancel a pending terminal transition", async () => {
  const select = await waitFor(
    () => document.querySelector('.board-card[data-job-id="j5"] [data-board-status]'),
    "j5 board status select exists",
  );
  const stateJob = state.jobs.find((job) => job.job_id === "j5");
  assert.ok(stateJob, "state.jobs contains j5 for terminal cancel test");
  stateJob.status = "interview";

  for (const closeBy of ["escape", "backdrop"]) {
    select.value = "withdrawn";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
    const modal = await waitFor(
      () => document.querySelector(".modal-backdrop"),
      `${closeBy} terminal confirm modal opened`,
    );
    if (closeBy === "escape") {
      document.dispatchEvent(
        new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    } else {
      modal.click();
    }
    await waitFor(
      () => !document.querySelector(".modal-backdrop"),
      `${closeBy} closes the confirm modal`,
    );
    assert.equal(select.value, "interview");
  }
});
