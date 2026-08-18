import test from "node:test";
import assert from "node:assert";

import {
  applicationSnapshotsHtml,
  jobTimelineFormHtml,
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
  assert.match(html, /投递定稿快照/);
  const secondPosition = html.indexOf("第 2 版投递定稿");
  const firstPosition = html.indexOf("第 1 版投递定稿");
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
