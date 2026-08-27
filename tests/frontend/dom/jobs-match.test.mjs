/* MVP-07: real main.js boots on #/jobs, renders match dimensions, wires the
 * sort selector + deep link, and recomputes stale matches through the API. */

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

const MOCK_JOBS = [
  {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    location: "上海",
    status: "draft",
    match_score: 72,
    match_score_detail: {
      hard_skills: 80,
      scenario: 70,
      expression: 60,
      experience: 75,
    },
    match_reason: "存在技能缺口，可先补齐关键词",
    match_reason_source: "fallback",
    match_stale: true,
  },
  {
    job_id: "j2",
    title: "前端工程师",
    company: "Beta",
    location: "杭州",
    status: "draft",
    match_score: 55,
    match_score_detail: {
      hard_skills: 60,
      scenario: 50,
      expression: 45,
      experience: 55,
    },
    match_reason: "关键能力缺口明显",
    match_reason_source: "llm",
    match_stale: true,
  },
];

const calls = { jobs: [], match: [] };
const recomputed = new Set();
let matchShouldFail = false;

function jsonBody(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function visibleJobs() {
  return MOCK_JOBS.map((job) =>
    recomputed.has(job.job_id)
      ? { ...job, match_stale: false, match_reason: "已重新评分" }
      : job,
  );
}

async function mockFetch(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const url = String(path);
  if (method === "GET" && url.startsWith("/api/auth/me")) {
    return jsonBody({ ok: true });
  }
  if (method === "GET" && url.startsWith("/api/settings")) {
    return jsonBody({
      classification_vocabulary: {
        job_functions: ["后端", "前端"],
        seniorities: ["初级", "高级"],
        statuses: ["未投递", "已投递"],
      },
    });
  }
  if (method === "GET" && url.startsWith("/api/jobs")) {
    calls.jobs.push(url);
    return jsonBody(visibleJobs());
  }
  if (method === "POST" && /\/api\/jobs\/[^/]+\/match$/.test(url)) {
    calls.match.push(url);
    if (matchShouldFail) {
      return jsonBody({ detail: "评分服务暂不可用" }, 502);
    }
    const jobId = url.split("/")[3];
    recomputed.add(jobId);
    return jsonBody({
      job_id: jobId,
      match_score: 90,
      match_reason: "已重新评分，建议优先投递",
      match_reason_source: "llm",
      match_stale: false,
    });
  }
  if (method === "GET" && url.startsWith("/api/master-resumes")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/llm/nodes")) {
    return jsonBody([]);
  }
  if (method === "GET" && url.startsWith("/api/automation/rules")) {
    return jsonBody([]);
  }
  return jsonBody({ detail: `no mock for ${method} ${url}` }, 404);
}
globalThis.fetch = mockFetch;

await import("../../../src/resualign/static/app/main.js");
const { state } = await import("../../../src/resualign/static/app/events.js");

async function waitFor(fn, label, timeoutMs = 3000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const value = fn();
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 15));
  }
  throw new Error(`waitFor timeout: ${label}`);
}

test("jobs board renders sort selector, four dimensions and stale button", async () => {
  await waitFor(
    () => document.querySelector("[data-match-block]"),
    "match block rendered",
  );
  const select = document.querySelector("[data-job-sort]");
  assert.ok(select, "sort select exists");
  assert.equal(select.value, "updated_at_desc");
  assert.equal(
    document.querySelectorAll("[data-match-dimension]").length,
    8,
  );
  assert.ok(document.querySelector("[data-match-total]"));
  assert.ok(document.querySelector("[data-match-reason]"));
  assert.ok(document.querySelector("[data-match-stale]"));
  assert.ok(document.querySelector('[data-action="recompute-match"][data-id="j1"]'));
});

test("deep link #/jobs?sort=match_score_asc restores the sort", async () => {
  window.location.hash = "#/jobs?sort=match_score_asc";
  window.dispatchEvent(new window.Event("hashchange"));
  await waitFor(
    () => document.querySelector("[data-job-sort]"),
    "sort select rendered after deep link",
  );
  assert.equal(state.filters.sort, "match_score_asc");
  const ascOption = document.querySelector(
    '[data-job-sort] option[value="match_score_asc"]',
  );
  assert.ok(ascOption, "asc option rendered");
  assert.equal(
    ascOption.hasAttribute("selected"),
    true,
    "asc option carries the selected attribute",
  );
  assert.ok(
    calls.jobs.some((url) => url.includes("sort=match_score_asc")),
    "request used the deep-linked sort",
  );
});

test("sort change requests match_score_desc and keeps the board route", async () => {
  const select = document.querySelector("[data-job-sort]");
  select.value = "match_score_desc";
  select.dispatchEvent(new window.Event("change", { bubbles: true }));
  await waitFor(
    () =>
      state.filters.sort === "match_score_desc" &&
      calls.jobs.some((url) => url.includes("sort=match_score_desc")),
    "sort request",
  );
  assert.equal(select.value, "match_score_desc");
  assert.ok(document.querySelector("#job-board"));
});

test("recompute-match disables, calls the API and clears stale on success", async () => {
  const button = document.querySelector(
    '[data-action="recompute-match"][data-id="j1"]',
  );
  assert.ok(button, "stale j1 button exists");
  button.click();
  await waitFor(
    () => calls.match.length >= 1,
    "match API called",
  );
  await waitFor(
    () => {
      const j1Card = [...document.querySelectorAll("[data-job-id='j1']")][0];
      return j1Card && !j1Card.querySelector("[data-match-stale]");
    },
    "j1 stale badge cleared",
  );
});

test("recompute-match failure restores the button", async () => {
  matchShouldFail = true;
  const button = document.querySelector(
    '[data-action="recompute-match"][data-id="j2"]',
  );
  assert.ok(button, "stale j2 button exists");
  const before = calls.match.length;
  button.click();
  await waitFor(
    () => calls.match.length === before + 1,
    "failed match API called",
  );
  await waitFor(
    () => {
      const current = document.querySelector(
        '[data-action="recompute-match"][data-id="j2"]',
      );
      return current && current.textContent === "重新评分" && !current.disabled;
    },
    "button restored after failure",
  );
});
