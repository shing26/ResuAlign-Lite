import { test } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import {
  batchPanelHtml,
  computeJobStats,
  renderBatchMatrixHtml,
  renderJobStatsHtml,
} from "../../../src/resualign/static/app/format.js";

function docFromHtml(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document;
}

/* ------------------------------------------------------------------ */
/* renderJobStatsHtml (dashboard stats bar)                           */
/* ------------------------------------------------------------------ */

const sampleJobs = [
  { status: "draft" },
  { status: "draft" },
  { status: "applied" },
  { status: "interview" },
  { status: "offer" },
  { status: "withdrawn" },
];

test("renderJobStatsHtml shows five status counts", () => {
  const doc = docFromHtml(renderJobStatsHtml(computeJobStats(sampleJobs)));
  const counts = doc.querySelector("[data-board-stats-counts]");
  assert.equal(counts.querySelectorAll(".badge").length, 5);
  assert.equal(counts.querySelector('[data-stat-count="draft"]').textContent, "2");
  assert.equal(counts.querySelector('[data-stat-count="applied"]').textContent, "1");
  assert.equal(counts.querySelector('[data-stat-count="interview"]').textContent, "1");
  assert.equal(counts.querySelector('[data-stat-count="offer"]').textContent, "1");
  assert.equal(counts.querySelector('[data-stat-count="withdrawn"]').textContent, "1");
});

test("renderJobStatsHtml shows funnel conversion percentages", () => {
  const doc = docFromHtml(renderJobStatsHtml(computeJobStats(sampleJobs)));
  const funnel = doc.querySelector("[data-board-stats-funnel]");
  // applied = 1+1+1 = 3 of 6 -> 50%; interview = 1+1 = 2 of 3 -> 67%; offer = 1 of 2 -> 50%
  assert.equal(funnel.querySelector('[data-stat-rate="applyRate"]').textContent, "50%");
  assert.equal(funnel.querySelector('[data-stat-rate="interviewRate"]').textContent, "67%");
  assert.equal(funnel.querySelector('[data-stat-rate="offerRate"]').textContent, "50%");
});

test("renderJobStatsHtml renders em dash when a funnel denominator is zero", () => {
  const doc = docFromHtml(renderJobStatsHtml(computeJobStats([{ status: "draft" }])));
  const funnel = doc.querySelector("[data-board-stats-funnel]");
  // 投递/总数 has a live denominator (1) -> 0%; 面试/投递 and Offer/面试 divide by 0 -> "—"
  assert.equal(funnel.querySelector('[data-stat-rate="applyRate"]').textContent, "0%");
  assert.equal(funnel.querySelector('[data-stat-rate="interviewRate"]').textContent, "—");
  assert.equal(funnel.querySelector('[data-stat-rate="offerRate"]').textContent, "—");
});

test("renderJobStatsHtml falls back to empty stats", () => {
  const doc = docFromHtml(renderJobStatsHtml());
  assert.equal(doc.querySelectorAll("[data-board-stats-counts] .badge").length, 5);
  assert.equal(doc.querySelector('[data-stat-count="draft"]').textContent, "0");
});

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
