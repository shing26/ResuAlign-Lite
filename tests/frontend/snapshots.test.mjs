import test from "node:test";
import assert from "node:assert";

import {
  applicationSnapshotsHtml,
  interviewCheatSheetHtml,
  jobTimelineFormHtml,
  snapshotDrawerHtml,
} from "../../src/resualign/static/app/format.js";

test("applicationSnapshotsHtml lists snapshots newest first with actions", () => {
  const html = applicationSnapshotsHtml(
    { job_id: "j1", title: "Backend Engineer", status: "applied" },
    [
      {
        snapshot_id: 2,
        version_index: 2,
        final_draft: "# Draft two",
        match_score: 91,
        applied_at: "2026-08-02",
        master_resume_id: "r1",
      },
      {
        snapshot_id: 1,
        version_index: 1,
        final_draft: "# Draft one",
        match_score: null,
        applied_at: "2026-07-28",
      },
    ],
  );
  assert.match(html, /投递快照/);
  assert.doesNotMatch(html, /投递定稿快照/, "ADR-0033 决策7：全站唯一「投递快照」");
  const secondPosition = html.indexOf("第 2 版投递快照");
  const firstPosition = html.indexOf("第 1 版投递快照");
  assert.ok(secondPosition >= 0 && firstPosition > secondPosition);
  assert.match(html, /匹配度 91/);
  assert.match(html, /匹配度 —/);
  assert.match(html, /data-action="open-snapshot"/);
  assert.match(html, /data-action="export-snapshot-md"/);
  assert.match(html, /data-action="export-snapshot-pdf"/);
});

test("applicationSnapshotsHtml falls back to legacy applied draft", () => {
  const html = applicationSnapshotsHtml(
    {
      job_id: "legacy",
      title: "Legacy Job",
      status: "已投递",
      final_draft: "# Legacy draft",
    },
    [],
  );
  assert.match(html, /data-legacy-snapshot/);
  assert.match(html, /早期投递版本（未生成不可篡改快照）/);
  assert.match(html, /data-action="view-legacy-draft"/);
  assert.match(html, /data-action="export-legacy-draft-pdf"/);
});

test("applicationSnapshotsHtml hides section for draft jobs without snapshots", () => {
  const html = applicationSnapshotsHtml(
    { job_id: "draft", title: "Draft Job", status: "未投递", final_draft: "# X" },
    [],
  );
  assert.equal(html, "");
});

test("interviewCheatSheetHtml derives questions from diffs and gaps", () => {
  const html = interviewCheatSheetHtml({
    jd_profile: { business_scenarios: ["高并发"] },
    gap_report: { missing_keywords: ["Redis"] },
    diffs: [
      {
        type: "modify",
        proposed: "构建高吞吐后端服务",
        confidence: "high",
        reason: "突出指标",
      },
    ],
  });
  assert.match(html, /data-interview-cheatsheet/);
  assert.match(html, /面试防深挖清单/);
  assert.match(html, />改写</);
  assert.match(html, /关于「构建高吞吐后端服务」/);
  assert.match(html, /Redis/);
  assert.match(html, /高并发/);
  assert.match(html, /cheatsheet__sop/);
});

test("interviewCheatSheetHtml escapes question topics and returns empty when no signal", () => {
  const html = interviewCheatSheetHtml({
    jd_profile: { business_scenarios: ["<危险>"] },
    gap_report: { missing_keywords: [] },
    diffs: [],
  });
  assert.match(html, /&lt;危险&gt;/);
  assert.doesNotMatch(html, /<危险>/);
  assert.equal(interviewCheatSheetHtml({}), "");
});

test("jobTimelineFormHtml embeds the snapshot section", () => {
  const html = jobTimelineFormHtml(
    { job_id: "j1", title: "Job", status: "applied" },
    [
      {
        snapshot_id: 1,
        version_index: 1,
        final_draft: "# Draft",
        match_score: 80,
        applied_at: "2026-08-01",
      },
    ],
  );
  assert.match(html, /data-snapshot-item/);
  assert.match(html, /data-form="job-detail-edit"/);
});
/* ------------------------------------------------------------------ */
/* ADR-0033 决策5：投递快照右侧抽屉                                  */
/* ------------------------------------------------------------------ */

test("snapshotDrawerHtml renders the right-side snapshot drawer", () => {
  const html = snapshotDrawerHtml(
    {
      snapshot_id: 7,
      job_id: "j1",
      version_index: 2,
      final_draft: "# Draft",
      match_score: 91,
      applied_at: "2026-08-18",
      created_at: 1780000000,
    },
    { jobId: "j1", job: { title: "Job" }, legacyDraft: null },
  );
  assert.match(html, /data-snapshot-drawer/);
  assert.match(html, /投递时匹配度 91 分/);
  assert.match(html, /版本 v2/);
  /* 「投递快照」术语由 drawer 的 modal h3 标题承载（main.js open-snapshot），
   * 正文 fragment 不重复；静态契约见 adr0033.test.mjs。 */
  assert.doesNotMatch(html, /投递定稿快照/, "ADR-0033 决策7：正文不使用「投递定稿快照」");
  assert.match(html, /下载 Markdown/);
  assert.match(html, /导出 PDF/);
  assert.match(html, /data-action="export-snapshot-md"/);
  assert.match(html, /data-action="export-snapshot-pdf"/);
  assert.match(html, /投递快照正文（预览）/);
  assert.match(html, /resume-doc/);
  assert.doesNotMatch(html, /legacy-warning/);
  assert.doesNotMatch(html, /⚠/, "warning emoji replaced by linear SVG icon");
});

test("snapshotDrawerHtml shows a placeholder match when score is missing", () => {
  const html = snapshotDrawerHtml(
    { snapshot_id: 1, job_id: "j1", version_index: 1, final_draft: "# X", match_score: null, created_at: 1780000000 },
    { jobId: "j1", job: {}, legacyDraft: null },
  );
  assert.match(html, /投递时匹配度 —/);
});

test("snapshotDrawerHtml renders the cheatsheet when the job has signals", () => {
  const html = snapshotDrawerHtml(
    { snapshot_id: 1, job_id: "j1", version_index: 1, final_draft: "# X", match_score: 80, created_at: 1780000000 },
    {
      jobId: "j1",
      job: {
        jd_profile: { business_scenarios: ["高并发"] },
        gap_report: { missing_keywords: ["Redis"] },
        diffs: [],
      },
      legacyDraft: null,
    },
  );
  assert.match(html, /面试防深挖清单/);
  assert.match(html, /Redis/);
  assert.match(html, /高并发/);
});

test("snapshotDrawerHtml legacy variant warns without a tamper-proof snapshot", () => {
  const html = snapshotDrawerHtml(null, { jobId: "j1", job: {}, legacyDraft: "# Legacy draft" });
  assert.match(html, /data-snapshot-drawer/);
  assert.match(html, /data-snapshot-legacy/);
  assert.match(html, /早期投递版本（未生成不可篡改快照）/);
  assert.match(html, /data-action="export-legacy-draft-md"/);
  assert.match(html, /data-action="export-legacy-draft-pdf"/);
  assert.match(html, /<svg/, "warning uses a linear SVG icon");
  assert.match(html, /Legacy draft/);
  assert.doesNotMatch(html, /⚠/, "warning emoji replaced by linear SVG icon");
});
