import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  batchPanelHtml,
  renderBatchMatrixHtml,
} from "../../../src/resualign/static/app/format.js";

function docFromHtml(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document;
}

/* ------------------------------------------------------------------ */
/* renderBatchMatrixHtml (batch comparison matrix)                    */
/* ------------------------------------------------------------------ */

const completedBatch = {
  rows: [
    {
      job_id: "j1",
      title: "后端工程师",
      company: "Acme",
      status: "succeeded",
      summary: { score: 86, key_gaps: ["K8s", "高并发", "分布式锁"] },
    },
    {
      job_id: "j2",
      title: "前端工程师",
      company: "Beta",
      status: "succeeded",
      summary: { score: 54, key_gaps: ["WebGL"] },
    },
  ],
  summary: { completed: 2, total: 2 },
};

test("renderBatchMatrixHtml renders horizontal score bars with widths", () => {
  const doc = docFromHtml(renderBatchMatrixHtml(completedBatch));
  const bars = doc.querySelectorAll("[data-batch-bar]");
  assert.equal(bars.length, 2);
  const fills = doc.querySelectorAll("[data-batch-bar-fill]");
  assert.equal(fills[0].style.width, "86%");
  assert.equal(fills[1].style.width, "54%");
  assert.equal(doc.querySelector("[data-batch-bar-score]").textContent, "86");
});

test("renderBatchMatrixHtml renders side-by-side key gap columns", () => {
  const doc = docFromHtml(renderBatchMatrixHtml(completedBatch));
  const cols = doc.querySelectorAll("[data-batch-gap-col]");
  assert.equal(cols.length, 2);
  assert.match(cols[0].textContent, /后端工程师/);
  const gaps = doc.querySelectorAll("[data-batch-gap]");
  assert.equal(gaps.length, 4); // 3 + 1
  assert.match(gaps[0].textContent, /K8s/);
});

test("renderBatchMatrixHtml includes the CSV export button", () => {
  const doc = docFromHtml(renderBatchMatrixHtml(completedBatch));
  const button = doc.querySelector('[data-action="export-batch-csv"]');
  assert.ok(button);
  assert.match(button.textContent, /导出对比 CSV/);
});

test("renderBatchMatrixHtml shows progress badges before summaries exist", () => {
  const doc = docFromHtml(
    renderBatchMatrixHtml({
      rows: [
        { job_id: "j1", title: "A", status: "queued" },
        { job_id: "j2", title: "B", status: "running" },
      ],
    }),
  );
  assert.equal(doc.querySelectorAll(".badge-pending").length, 2);
  assert.equal(doc.querySelector("[data-action='export-batch-csv']"), null);
  assert.equal(doc.querySelector("[data-batch-bar]"), null);
});

test("renderBatchMatrixHtml surfaces failure reason on progress badges", () => {
  const doc = docFromHtml(
    renderBatchMatrixHtml({
      rows: [
        { job_id: "j1", title: "A", status: "failed", error: "LLM 429: rate limited" },
        { job_id: "j2", title: "B", status: "canceled", error: "Canceled by user" },
      ],
    }),
  );
  const failed = doc.querySelector("[data-batch-failed]");
  assert.ok(failed);
  assert.match(failed.getAttribute("title"), /LLM 429/);
  assert.match(failed.textContent, /failed/);
  assert.equal(doc.querySelectorAll("[data-batch-failed]").length, 2);
});

test("renderBatchMatrixHtml shows failure reason in result table rows", () => {
  const doc = docFromHtml(
    renderBatchMatrixHtml({
      rows: [
        { job_id: "j1", title: "A", status: "succeeded", summary: { score: 80, key_gaps: [] } },
        { job_id: "j2", title: "B", status: "failed", error: "模型响应异常，请重试" },
      ],
    }),
  );
  const failed = doc.querySelector("tr [data-batch-failed]");
  assert.ok(failed);
  assert.match(failed.getAttribute("title"), /模型响应异常/);
  assert.equal(doc.querySelectorAll("tr [data-batch-failed]").length, 1);
});

test("renderBatchMatrixHtml escapes user-controlled titles", () => {
  const doc = docFromHtml(
    renderBatchMatrixHtml({
      rows: [
        {
          job_id: "j1",
          title: '<script>alert("x")</script>',
          status: "succeeded",
          summary: { score: 80, key_gaps: [] },
        },
      ],
    }),
  );
  assert.equal(doc.querySelector("[data-batch-bar]").querySelector("script"), null);
  assert.match(doc.querySelector("[data-batch-gap-col]").innerHTML, /&lt;script&gt;/);
});

/* ------------------------------------------------------------------ */
/* batchPanelHtml (history entry)                                     */
/* ------------------------------------------------------------------ */

test("batchPanelHtml offers the last-batch history entry with gap note", () => {
  const doc = docFromHtml(batchPanelHtml([], []));
  const button = doc.querySelector('[data-action="show-last-batch"]');
  assert.ok(button);
  assert.match(doc.body.innerHTML, /后端暂无批次列表接口/);
});
