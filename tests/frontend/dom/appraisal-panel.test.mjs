import test from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";

import "./happy-setup.mjs";
import { state } from "../../../src/resualign/static/app/events.js";
import {
  appraisalBodyHtml,
  fillAppraisalPanel,
  renderAppraisalSync,
} from "../../../src/resualign/static/app/appraisal-panel.js";

const APPRAISAL = {
  score: 63,
  verdict: "考虑",
  conclusion: "综合看可以投递",
  benchmark_source: "暂无基准，中性处理",
  components: {
    match: 70,
    salary: 60,
    hard_conditions: 80,
    quality: 50,
    commute: 90,
  },
  reasons: ["匹配度高", "薪资中位"],
};

test("appraisalBodyHtml renders score ring, verdict, radar and conclusion", () => {
  const html = appraisalBodyHtml(APPRAISAL);
  assert.match(html, /score-ring--mid/);
  assert.match(html, /--score:63/);
  assert.match(html, /badge-amber">考虑/);
  assert.match(html, /appraisal-radar/);
  assert.match(html, /radar-svg/);
  assert.match(html, /综合看可以投递/);
  assert.match(html, /匹配度高/);
  assert.doesNotMatch(html, /<h3>/);
});

test("appraisalBodyHtml falls back to neutral verdict and empty lists", () => {
  const html = appraisalBodyHtml({ score: 40, verdict: "", components: {} });
  assert.match(html, /score-ring--low/);
  assert.match(html, /badge-red/);
  assert.doesNotMatch(html, /appraisal-radar/);
});

test("fillAppraisalPanel fills a data-appraisal-body placeholder without duplicating h3", () => {
  const window = new Window();
  window.document.body.innerHTML = `
    <details data-appraisal-panel>
      <summary>投递价值评估</summary>
      <div class="appraisal-body" data-appraisal-body>
        <div class="muted small">占位</div>
      </div>
    </details>`;
  const panel = window.document.querySelector("[data-appraisal-panel]");
  fillAppraisalPanel(panel, APPRAISAL);
  const body = panel.querySelector("[data-appraisal-body]");
  assert.match(body.innerHTML, /appraisal-score/);
  assert.doesNotMatch(body.innerHTML, /<h3>/);
  assert.equal(panel.querySelector("summary").textContent, "投递价值评估");
});

test("fillAppraisalPanel writes h3 into classic panel", () => {
  const window = new Window();
  window.document.body.innerHTML = `<div data-appraisal-panel></div>`;
  const panel = window.document.querySelector("[data-appraisal-panel]");
  fillAppraisalPanel(panel, APPRAISAL);
  assert.match(panel.innerHTML, /<h3>投递价值评估<\/h3>/);
});

test("renderAppraisalSync renders cache for the matching job and misses otherwise", () => {
  state.wbAppraisal = { job_id: "job-1", ...APPRAISAL };
  try {
    const window = new Window();
    window.document.body.innerHTML =
      '<div data-appraisal-panel><div data-appraisal-body></div></div>';
    const panel = window.document.querySelector("[data-appraisal-panel]");
    assert.equal(renderAppraisalSync(panel, "job-1"), true);
    assert.match(panel.innerHTML, /score-ring/);
    /* a miss leaves the previously rendered content untouched */
    assert.equal(renderAppraisalSync(panel, "job-2"), false);
    assert.match(panel.innerHTML, /score-ring/);
    assert.doesNotMatch(panel.innerHTML, /占位/);
  } finally {
    delete state.wbAppraisal;
  }
});
