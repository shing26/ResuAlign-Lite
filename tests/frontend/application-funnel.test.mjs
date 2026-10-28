import { test } from "node:test";
import assert from "node:assert/strict";

import { funnelHtml } from "../../src/resualign/static/app/format.js";

const FUNNEL = {
  counts: { jobs: 10, aligned: 4, usable: 3, drafts: 2, applications: 1 },
  rates: { draft_rate: 0.2, applied_rate: 0.5, interview_rate: null, offer_rate: null },
  applications: [
    {
      job_id: "j1",
      job_title: "后端工程师",
      applied_at: "2026-10-28",
      channel: "官网",
      final_draft_version: 2,
      accepted_count: 3,
      status: "applied",
      outcome_at: "",
    },
  ],
  note: "样本很小，只做自检",
};

test("funnel renders counters, rates and the adoption row", () => {
  const html = funnelHtml(FUNNEL);
  assert.match(html, /岗位 10/);
  assert.match(html, /已保存定稿 2/);
  assert.match(html, /已记录投递 1/);
  assert.match(html, /定稿率 20%/);
  assert.match(html, /投递率 50%/);
  assert.match(html, /面试率 —/);
  assert.match(html, /后端工程师/);
  assert.match(html, /官网/);
  assert.match(html, /v2/);
  assert.match(html, /样本很小/);
});

test("funnel offers outcome buttons except the current status", () => {
  const html = funnelHtml(FUNNEL);
  assert.match(html, /data-action="application-outcome" data-id="j1" data-status="interview"/);
  assert.match(html, /data-status="offer"/);
  assert.match(html, /data-status="rejected"/);
  assert.doesNotMatch(html, /data-status="applied"/);
});

test("funnel with no applications renders a hint", () => {
  const html = funnelHtml({ counts: { jobs: 0 }, rates: {}, applications: [], note: "" });
  assert.match(html, /还没有记录投递/);
});
