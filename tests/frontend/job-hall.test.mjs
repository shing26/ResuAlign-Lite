import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  activeFilterCount,
  audienceLabel,
  cityOptions,
  companyInitial,
  computeHallStats,
  dueItems,
  filterHallJobs,
  inferAudience,
  relativeTime,
  salaryBand,
  sortHallJobs,
} from "../../src/resualign/static/app/job-hall-model.js";

const here = dirname(fileURLToPath(import.meta.url));
const appDir = join(here, "../../src/resualign/static/app");

const NOW = Date.parse("2026-11-19T12:00:00+08:00");
const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;
const at = (msAgo) => (NOW - msAgo) / 1000;

const JOBS = [
  {
    job_id: "j1",
    title: "2027届校园招聘 · 后端工程师",
    company: "星海科技",
    location: "上海",
    job_function: "后端",
    seniority: "初级",
    salary_min: 18000,
    salary_max: 28000,
    status: "interview",
    applied_at: "2026-11-01",
    match_score: 88,
    updated_at: at(2 * HOUR),
    tech_tags: ["Java", "Spring"],
    jd_text: "面向 2027 届校园招聘，负责服务端开发。",
  },
  {
    job_id: "j2",
    title: "高级后端工程师",
    company: "北辰数据",
    location: "北京",
    job_function: "后端",
    seniority: "高级",
    salary_min: 40000,
    salary_max: 60000,
    status: "draft",
    match_score: 72,
    updated_at: at(10 * DAY),
    tech_tags: ["Go", "Kubernetes"],
    jd_text: "负责高并发交易系统。",
    source_url: "https://example.com/jobs/2",
  },
  {
    job_id: "j3",
    title: "数据开发实习生",
    company: "云图",
    location: "上海",
    job_function: "数据",
    seniority: "实习",
    salary_min: 8000,
    salary_max: 10000,
    status: "applied",
    applied_at: "2026-11-10",
    match_score: null,
    updated_at: at(26 * HOUR),
    tech_tags: ["SQL"],
    jd_text: "校园实习岗位。",
  },
  {
    job_id: "j4",
    title: "产品经理",
    company: "远山",
    location: "深圳",
    job_function: "产品",
    seniority: "中级",
    salary_min: null,
    salary_max: null,
    status: "offer",
    offer_at: "2026-11-15",
    match_score: 60,
    updated_at: at(3 * DAY),
    tech_tags: [],
    jd_text: "负责 B 端产品规划。",
  },
  {
    job_id: "j5",
    title: "测试工程师",
    company: "北辰数据",
    location: "北京",
    job_function: "测试",
    seniority: "中级",
    salary_min: 22000,
    salary_max: 30000,
    status: "withdrawn",
    match_score: 81,
    updated_at: at(8 * DAY),
    tech_tags: ["Python"],
    jd_text: "负责自动化测试。",
  },
];

test("inferAudience only trusts explicit campus signals", () => {
  assert.equal(inferAudience(JOBS[0]), "campus");
  assert.equal(inferAudience(JOBS[2]), "campus");
  assert.equal(inferAudience(JOBS[1]), "experienced");
  assert.equal(inferAudience({ title: "后端工程师", seniority: "高级" }), "experienced");
  assert.equal(audienceLabel("campus"), "校园招聘");
});

test("salaryBand maps stored monthly ranges to filter buckets", () => {
  assert.equal(salaryBand(JOBS[0]), "20-30");
  assert.equal(salaryBand(JOBS[1]), "50+");
  assert.equal(salaryBand(JOBS[2]), "10-20");
  assert.equal(salaryBand(JOBS[3]), "");
  assert.equal(salaryBand(JOBS[4]), "30-50");
});

test("filterHallJobs combines query, audience and facet filters", () => {
  const campus = filterHallJobs(JOBS, { audience: "campus" }, new Set(), NOW);
  assert.deepEqual(
    campus.map((job) => job.job_id),
    ["j1", "j3"],
  );
  const java = filterHallJobs(JOBS, { query: "java spring" }, new Set(), NOW);
  assert.deepEqual(java.map((job) => job.job_id), ["j1"]);
  const shanghaiBackend = filterHallJobs(
    JOBS,
    { city: "上海", jobFunction: "后端", salary: "20-30" },
    new Set(),
    NOW,
  );
  assert.deepEqual(shanghaiBackend.map((job) => job.job_id), ["j1"]);
  const high = filterHallJobs(JOBS, { matchMin: 80 }, new Set(), NOW);
  assert.deepEqual(high.map((job) => job.job_id), ["j1", "j5"]);
  const saved = filterHallJobs(JOBS, { savedOnly: true }, new Set(["j4"]), NOW);
  assert.deepEqual(saved.map((job) => job.job_id), ["j4"]);
  const recent = filterHallJobs(JOBS, { recentOnly: true }, new Set(), NOW);
  assert.deepEqual(
    recent.map((job) => job.job_id),
    ["j1", "j3", "j4"],
  );
});

test("sortHallJobs keeps unknown scores and salaries last", () => {
  const byMatch = sortHallJobs(JOBS, "match_desc");
  assert.deepEqual(
    byMatch.map((job) => job.job_id),
    ["j1", "j5", "j2", "j4", "j3"],
  );
  const bySalary = sortHallJobs(JOBS, "salary_desc");
  assert.deepEqual(
    bySalary.map((job) => job.job_id),
    ["j2", "j5", "j1", "j3", "j4"],
  );
});

test("computeHallStats uses exclusive current stages and cumulative conversions", () => {
  const stats = computeHallStats(JOBS, new Set(["j1", "j4"]), NOW);
  assert.equal(stats.total, 5);
  assert.equal(stats.draft, 1);
  assert.equal(stats.applied, 1);
  assert.equal(stats.interview, 1);
  assert.equal(stats.offer, 1);
  assert.equal(stats.withdrawn, 1);
  assert.equal(stats.appliedCumulative, 3);
  assert.equal(stats.interviewCumulative, 2);
  assert.equal(stats.offerCumulative, 1);
  assert.equal(stats.saved, 2);
  assert.equal(stats.highMatch, 2);
  assert.equal(stats.applyRate, 60);
  assert.equal(stats.interviewRate, 67);
  assert.equal(stats.offerRate, 33);
});

test("dueItems sorts next-step and deadline reminders together", () => {
  const jobs = [
    {
      job_id: "a",
      title: "A",
      next_step_due_at: "2026-11-20T10:00",
      deadline: "2026-11-25",
    },
    {
      job_id: "b",
      title: "B",
      deadline: "2026-11-18",
    },
  ];
  const items = dueItems(jobs, NOW);
  assert.equal(items.length, 3);
  assert.equal(items[0].job.job_id, "b");
  assert.equal(items[0].kind, "deadline");
});

test("activeFilterCount only counts effective filters", () => {
  assert.equal(activeFilterCount({}), 0);
  assert.equal(
    activeFilterCount({
      query: "java",
      audience: "campus",
      city: "上海",
      matchMin: 80,
      savedOnly: true,
    }),
    5,
  );
  assert.equal(activeFilterCount({ audience: "all", matchMin: 0 }), 0);
});

test("relativeTime and company helpers stay deterministic", () => {
  assert.equal(relativeTime(at(30 * 1000), NOW), "刚刚");
  assert.equal(relativeTime(at(5 * 60 * 1000), NOW), "5 分钟前");
  assert.equal(relativeTime(at(3 * HOUR), NOW), "3 小时前");
  assert.equal(relativeTime(at(2 * DAY), NOW), "2 天前");
  assert.equal(relativeTime(null, NOW), "");
  assert.equal(companyInitial("星海科技"), "星");
  assert.equal(companyInitial(""), "?");
  assert.deepEqual(cityOptions(JOBS), ["北京", "上海", "深圳"]);
});

test("job hall is wired into the existing shell and router", () => {
  const index = readFileSync(join(here, "../../src/resualign/static/index.html"), "utf8");
  const main = readFileSync(join(appDir, "main.js"), "utf8");
  const hall = readFileSync(join(appDir, "job-hall.js"), "utf8");
  const format = readFileSync(join(appDir, "format.js"), "utf8");
  const css = readFileSync(
    join(here, "../../src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(index, /data-route="jobs"/);
  assert.match(index, />职位</);
  assert.doesNotMatch(index, /data-route="job-hall"/);
  assert.match(
    main,
    /import \{ renderJobHall, syncJobHallFromHash \} from "\.\/job-hall\.js"/,
  );
  assert.match(main, /addEventListener\("popstate"/);
  assert.match(main, /case "jobs":/);
  assert.match(main, /case "job-hall":/);
  assert.match(main, /jobs: \["职位"/);
  assert.match(format, /"job-hall"/);
  assert.match(css, /\.jh-view\s*\{/);
  assert.match(css, /\.jh-workspace\s*\{/);
  assert.match(hall, /function paintWorkFilter\(\)/, "work filter repaints after selection");
  assert.match(hall, /function alignmentPanelHtml\(/, "failed detail exposes reason");
  assert.match(hall, /export function syncJobHallFromHash\(/, "jobs back reuses loaded data");
  assert.match(hall, /history\.pushState\(/, "opening a detail creates a history entry");
  assert.match(css, /\.jh-alignpanel--danger\s*\{/, "failure panel has an explicit tone");
  assert.match(
    css,
    /@media \(max-width: 640px\)[\s\S]*?\.jh-progress__foot\s*\{\s*display: none/,
    "mobile fold prioritizes jobs over the progress footer",
  );
});
