import { test } from "node:test";
import assert from "node:assert/strict";

import {
  applicationSummaryHtml,
  jobTimelineHtml,
  recordApplicationFormHtml,
} from "../../src/resualign/static/app/format.js";

test("application summary shows date, channel, version and sha prefix", () => {
  const html = applicationSummaryHtml({
    applied_at: "2026-10-28",
    channel: "官网",
    final_draft_version: 3,
    draft_sha256: "a".repeat(64),
    status: "interview",
  });
  assert.match(html, /2026-10-28 · 官网 · v3 · sha aaaaaaaaaa/);
  assert.match(html, /interview/);
});

test("missing application renders a hint", () => {
  assert.match(applicationSummaryHtml(null), /未记录投递/);
});

test("timeline renders events with labels and details", () => {
  const html = jobTimelineHtml({
    job_id: "j1",
    events: [
      { at: 1700000000, kind: "created", label: "岗位入库", detail: "后端" },
      { at: 1700000100, kind: "application", label: "记录投递", detail: "官网" },
    ],
  });
  assert.match(html, /data-job-timeline/);
  assert.match(html, /岗位入库/);
  assert.match(html, /记录投递/);
  assert.match(html, /官网/);
});

test("empty timeline says so", () => {
  assert.match(jobTimelineHtml({ events: [] }), /还没有时间线/);
});

test("record form carries job id, channels and today's date", () => {
  const html = recordApplicationFormHtml({ job_id: "job-9" });
  assert.match(html, /data-form="record-application"/);
  assert.match(html, /data-id="job-9"/);
  for (const channel of ["官网", "招聘平台", "邮箱", "内推", "其他"]) {
    assert.match(html, new RegExp(channel));
  }
  assert.match(html, /<input class="field-input" type="date" name="applied_at" value="\d{4}-\d{2}-\d{2}"/);
});
