import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";

/* review-view.js imports events.js，其模块顶层读取 localStorage——
 * 必须先挂 happy-dom 全局再 import（同 tests/frontend/dom/jobs-match.test.mjs）。 */
const domWindow = new Window({ url: "http://localhost:8000/" });
globalThis.window = domWindow;
globalThis.document = domWindow.document;
globalThis.localStorage = domWindow.localStorage;

const { pendingAnnotateJobs, quickAnnotateHtml } = await import(
  "../../src/resualign/static/app/review-view.js"
);

const here = dirname(fileURLToPath(import.meta.url));

function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

const NOW = Date.parse("2026-09-10T12:00:00Z");

function job(overrides = {}) {
  return {
    job_id: "j1",
    title: "后端工程师",
    company: "Acme",
    status: "applied",
    applied_at: "2026-09-05T09:00:00Z",
    application_result: null,
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/* pendingAnnotateJobs: 复盘快速标注卡的候选过滤                          */
/* ------------------------------------------------------------------ */

test("pendingAnnotateJobs keeps applied-within-14d jobs without attribution", () => {
  const rows = pendingAnnotateJobs(
    [
      job(), // in window, no result -> keep
      job({ job_id: "j2", applied_at: "2026-08-01T09:00:00Z" }), // too old
      job({ job_id: "j3", application_result: "screen_pass" }), // already annotated
      job({ job_id: "j4", status: "draft" }), // not applied yet
      job({ job_id: "j5", status: "interview" }), // later stage, still counts
      job({ job_id: "j6", status: "withdrawn" }), // terminal but annotatable
      job({ job_id: "j7", applied_at: "2026-09-09T23:00:00Z" }), // boundary inside
      job({ job_id: "j8", status: "applied", applied_at: "" }), // no parseable date -> excluded
      null,
    ],
    NOW,
  );
  assert.deepEqual(
    rows.map(({ job: j }) => j.job_id),
    ["j7", "j1", "j5", "j6"],
    "newest first, only applied+ within window without result",
  );
});

test("pendingAnnotateJobs window boundary is 14 full days", () => {
  const edge = pendingAnnotateJobs(
    [
      job({ job_id: "in", applied_at: "2026-08-27T12:01:00Z" }),
      job({ job_id: "out", applied_at: "2026-08-27T11:59:00Z" }),
    ],
    NOW,
  );
  assert.deepEqual(edge.map(({ job: j }) => j.job_id), ["in"]);
});

test("pendingAnnotateJobs tolerates a non-array input", () => {
  assert.equal(pendingAnnotateJobs(null, NOW).length, 0);
});

/* ------------------------------------------------------------------ */
/* quickAnnotateHtml: 快速标注卡渲染                                     */
/* ------------------------------------------------------------------ */

test("quickAnnotateHtml renders one select per job with attribution options", () => {
  const body = bodyFrom(
    quickAnnotateHtml(
      [job(), job({ job_id: "j2", title: "前端工程师", company: "" })],
      2,
    ),
  );
  const rows = [...body.querySelectorAll("[data-annotate-row]")];
  assert.equal(rows.length, 2);
  assert.equal(rows[0].dataset.jobId, "j1");
  assert.match(rows[0].textContent, /后端工程师/);
  assert.match(rows[0].textContent, /Acme/);
  assert.match(rows[1].textContent, /前端工程师/);
  const selects = [...body.querySelectorAll("[data-annotate-select]")];
  assert.equal(selects.length, 2);
  const values = [...selects[0].querySelectorAll("option")].map((o) => o.value);
  assert.deepEqual(values, ["", "screen_pass", "ats_reject", "no_response", "other"]);
  assert.match(body.querySelector(".badge-amber").textContent, /2/);
});

test("quickAnnotateHtml escapes job titles", () => {
  const body = bodyFrom(quickAnnotateHtml([job({ title: "<b>x</b>" })], 1));
  assert.equal(body.querySelector("b"), null);
  assert.match(body.querySelector("[data-annotate-row]").textContent, /<b>x<\/b>/);
});

test("quickAnnotateHtml notes truncation when total exceeds rows", () => {
  const body = bodyFrom(quickAnnotateHtml([job()], 9));
  assert.match(body.textContent, /仅显示最近 1 条/);
  const body2 = bodyFrom(quickAnnotateHtml([job()], 1));
  assert.doesNotMatch(body2.textContent, /仅显示最近/);
});

/* ------------------------------------------------------------------ */
/* 源码级契约：空态 CTA 与卡片挂载点                                     */
/* ------------------------------------------------------------------ */

test("review view wires empty-state CTA and annotate card mount", () => {
  const source = readFileSync(
    join(here, "../../src/resualign/static/app/review-view.js"),
    "utf8",
  );
  assert.match(source, /data-review-annotate/, "annotate card is tagged");
  assert.match(source, /data-annotate-select/, "selects are delegated");
  assert.match(source, /去岗位库标注/, "attribution empty state has CTA");
  assert.match(source, /去岗位库录入/, "module empty state has CTA");
  assert.match(source, /application_result: select\.value/, "PATCH carries attribution");
  assert.match(source, /method: "PATCH"/, "uses the existing partial-update endpoint");
});
