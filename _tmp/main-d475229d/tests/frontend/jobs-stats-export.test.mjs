import { test } from "node:test";
import assert from "node:assert/strict";
import {
  BACKUP_RESTORE_STEPS,
  backupRestoreGuide,
  batchRowsToCsv,
  buildJobsBackup,
  computeJobStats,
  csvEscape,
  funnelPercent,
  jobsToCsv,
} from "../../src/resualign/static/app/format.js";

/* ------------------------------------------------------------------ */
/* computeJobStats / funnelPercent                                    */
/* ------------------------------------------------------------------ */

test("computeJobStats counts five canonical states and funnel stages", () => {
  const jobs = [
    { status: "draft" },
    { status: "draft" },
    { status: "draft" },
    { status: "draft" },
    { status: "applied" },
    { status: "applied" },
    { status: "interview" },
    { status: "interview" },
    { status: "offer" },
    { status: "withdrawn" },
  ];
  const stats = computeJobStats(jobs);
  assert.deepEqual(stats.counts, {
    draft: 4,
    applied: 2,
    interview: 2,
    offer: 1,
    withdrawn: 1,
  });
  assert.equal(stats.total, 10);
  assert.deepEqual(stats.funnel, {
    applied: 5,
    interview: 3,
    offer: 1,
    applyRate: 50,
    interviewRate: 60,
    offerRate: 33,
  });
});

test("computeJobStats uses historical peak for withdrawn jobs", () => {
  const stats = computeJobStats([
    { status: "withdrawn", applied_at: "2026-08-01" },
    { status: "withdrawn", applied_at: "2026-08-02", offer_at: "2026-08-10" },
    { status: "offer", applied_at: "2026-08-03" },
    { status: "interview" },
  ]);
  assert.deepEqual(stats.counts, {
    draft: 0,
    applied: 0,
    interview: 1,
    offer: 1,
    withdrawn: 2,
  });
  assert.equal(stats.funnel.applied, 4);
  assert.equal(stats.funnel.interview, 3);
  assert.equal(stats.funnel.offer, 2);
});

test("computeJobStats accepts Chinese status labels via aliases", () => {
  const stats = computeJobStats([{ status: "已投递" }, { status: "面试中" }]);
  assert.equal(stats.counts.applied, 1);
  assert.equal(stats.counts.interview, 1);
  assert.equal(stats.funnel.applied, 2);
  assert.equal(stats.funnel.applyRate, 100);
});

test("computeJobStats ignores unknown statuses and empty input", () => {
  assert.deepEqual(computeJobStats([]).counts, {
    draft: 0,
    applied: 0,
    interview: 0,
    offer: 0,
    withdrawn: 0,
  });
  assert.equal(computeJobStats([]).funnel.applyRate, null);
  const stats = computeJobStats([{ status: "unknown-status" }]);
  assert.equal(stats.total, 1);
  assert.equal(stats.funnel.applied, 0);
});

test("funnelPercent returns null for zero/negative denominators", () => {
  assert.equal(funnelPercent(3, 0), null);
  assert.equal(funnelPercent(3, -1), null);
  assert.equal(funnelPercent(3, null), null);
  assert.equal(funnelPercent(3, undefined), null);
});

test("funnelPercent rounds to integer percent", () => {
  assert.equal(funnelPercent(1, 3), 33);
  assert.equal(funnelPercent(2, 3), 67);
  assert.equal(funnelPercent(1, 400), 0);
  assert.equal(funnelPercent(5, 10), 50);
});

/* ------------------------------------------------------------------ */
/* csvEscape / jobsToCsv                                              */
/* ------------------------------------------------------------------ */

test("csvEscape quotes fields containing separators and doubles quotes", () => {
  assert.equal(csvEscape("plain"), "plain");
  assert.equal(csvEscape("含,逗号"), '"含,逗号"');
  assert.equal(csvEscape('say "hi"'), '"say ""hi"""');
  assert.equal(csvEscape("line1\nline2"), '"line1\nline2"');
  assert.equal(csvEscape(null), "");
  assert.equal(csvEscape(0), "0");
});

test("jobsToCsv emits BOM, headers and one row per job", () => {
  const csv = jobsToCsv([
    {
      job_id: "j1",
      title: "后端工程师",
      company: "Acme, Inc.",
      location: "上海",
      salary_min: 15000,
      salary_max: 25000,
      status: "已投递",
      match_score: 83.6,
      final_draft_version: 2,
    },
    {
      job_id: "j2",
      title: "前端工程师",
      company: "Beta",
      location: "北京",
      status: "draft",
      match_score: null,
      final_draft_version: null,
    },
  ]);
  assert.ok(csv.startsWith("\uFEFF"));
  const lines = csv.replace(/^\uFEFF/, "").split("\r\n");
  assert.deepEqual(lines[0].split(","), [
    "岗位",
    "公司",
    "城市",
    "薪资",
    "状态",
    "匹配分",
    "定稿版本",
  ]);
  assert.equal(lines[1], '后端工程师,"Acme, Inc.",上海,15-25K,已投递,84,2');
  assert.equal(lines[2], "前端工程师,Beta,北京,薪资面议,未投递,,");
});

test("jobsToCsv handles empty library", () => {
  const csv = jobsToCsv([]);
  assert.ok(csv.startsWith("\uFEFF"));
  assert.equal(csv.replace(/^\uFEFF/, "").split("\r\n").length, 1);
});

/* ------------------------------------------------------------------ */
/* batchRowsToCsv                                                     */
/* ------------------------------------------------------------------ */

test("batchRowsToCsv maps verdict thresholds and joins gaps", () => {
  const csv = batchRowsToCsv({
    rows: [
      {
        job_id: "j1",
        title: "A",
        company: "C1",
        status: "succeeded",
        summary: { score: 90, key_gaps: ["K8s", "高并发"], next_step: "Apply" },
      },
      {
        job_id: "j2",
        title: "B",
        status: "succeeded",
        summary: { score: 60, key_gaps: ["英语"], next_step: "Consider" },
      },
      {
        job_id: "j3",
        title: "C",
        status: "failed",
        summary: null,
      },
    ],
  });
  const lines = csv.replace(/^\uFEFF/, "").split("\r\n");
  assert.deepEqual(lines[0].split(","), [
    "岗位",
    "公司",
    "匹配分",
    "关键缺口",
    "结论",
    "下一步",
  ]);
  assert.equal(lines[1], "A,C1,90,K8s；高并发,投递,Apply");
  assert.equal(lines[2], "B,,60,英语,考虑,Consider");
  assert.equal(lines[3], "C,,,,,failed");
});

/* ------------------------------------------------------------------ */
/* buildJobsBackup / backupRestoreGuide                               */
/* ------------------------------------------------------------------ */

test("buildJobsBackup wraps jobs with metadata and restore steps", () => {
  const jobs = [{ job_id: "j1", title: "T" }];
  const backup = buildJobsBackup(jobs);
  assert.equal(backup.type, "jobs-backup");
  assert.equal(backup.count, 1);
  assert.equal(backup.jobs, jobs);
  assert.ok(Array.isArray(backup.restore_steps));
  assert.ok(backup.restore_steps.length > 0);
  assert.match(backup.exported_at, /^\d{4}-\d{2}-\d{2}T/);
});

test("buildJobsBackup normalizes non-array input", () => {
  const backup = buildJobsBackup(undefined);
  assert.equal(backup.count, 0);
  assert.deepEqual(backup.jobs, []);
});

test("BACKUP_RESTORE_STEPS documents the import endpoint", () => {
  assert.ok(BACKUP_RESTORE_STEPS.some((step) => step.includes("/api/jobs/import")));
  const guide = backupRestoreGuide();
  assert.match(guide, /整库备份与还原/);
  assert.match(guide, /批量导入/);
});
