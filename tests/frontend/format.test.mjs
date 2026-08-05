import { test } from "node:test";
import assert from "node:assert/strict";
import {
  benchmarkSourceBadge,
  buildDiagnosisMarkdownFrom,
  canonicalJobStatus,
  esc,
  formatDate,
  formatSalary,
  isJdUrl,
  jobStatusLabel,
  lineDiff,
  matchTone,
  normalizeVocabulary,
  normalizeVocabularyList,
  options,
  parseHashValue,
  parseImportText,
} from "../../src/resualign/static/app/format.js";

/* ------------------------------------------------------------------ */
/* esc                                                                */
/* ------------------------------------------------------------------ */

test("esc escapes HTML special characters", () => {
  assert.equal(esc(`<script>"a" & 'b'`), "&lt;script&gt;&quot;a&quot; &amp; &#39;b&#39;");
});

test("esc returns empty string for null/undefined", () => {
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
});

test("esc passes plain text through", () => {
  assert.equal(esc("hello 世界"), "hello 世界");
});

/* ------------------------------------------------------------------ */
/* formatDate                                                          */
/* ------------------------------------------------------------------ */

test("formatDate renders local datetime from unix seconds", () => {
  const ts = 1700000000;
  const date = new Date(ts * 1000);
  const expected =
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
      date.getDate(),
    ).padStart(2, "0")} ${String(date.getHours()).padStart(2, "0")}:${String(
      date.getMinutes(),
    ).padStart(2, "0")}`;
  assert.equal(formatDate(ts), expected);
});

test("formatDate returns em dash for falsy timestamps", () => {
  assert.equal(formatDate(null), "—");
  assert.equal(formatDate(undefined), "—");
  assert.equal(formatDate(0), "—");
  assert.equal(formatDate(""), "—");
});

/* ------------------------------------------------------------------ */
/* formatSalary                                                        */
/* ------------------------------------------------------------------ */

test("formatSalary formats full ranges and single bounds", () => {
  assert.equal(formatSalary({ salary_min: 15000, salary_max: 20000 }), "15-20K");
  assert.equal(formatSalary({ salary_min: 15000 }), "15K");
  assert.equal(formatSalary({ salary_max: 20000 }), "20K");
  assert.equal(formatSalary({ salary_min: 10000, salary_max: 20000, salary_currency: "USD" }), "10-20K");
});

test("formatSalary returns 薪资面议 when both bounds are missing", () => {
  assert.equal(formatSalary({}), "薪资面议");
  assert.equal(formatSalary({ salary_currency: "CNY" }), "薪资面议");
});

/* ------------------------------------------------------------------ */
/* options                                                             */
/* ------------------------------------------------------------------ */

test("options builds option html and marks the selected value", () => {
  assert.equal(
    options(["a", "b"], "b"),
    '<option value="a" >a</option><option value="b" selected>b</option>',
  );
});

test("options escapes values", () => {
  assert.equal(
    options(["<x>"], ""),
    '<option value="&lt;x&gt;" >&lt;x&gt;</option>',
  );
});

/* ------------------------------------------------------------------ */
/* vocabulary helpers                                                  */
/* ------------------------------------------------------------------ */

test("normalizeVocabularyList returns fallback copy for non-arrays", () => {
  const fallback = ["a", "b"];
  const result = normalizeVocabularyList(null, fallback);
  assert.deepEqual(result, ["a", "b"]);
  assert.notEqual(result, fallback);
});

test("normalizeVocabularyList trims, drops empties, and falls back", () => {
  assert.deepEqual(normalizeVocabularyList(["  x ", "", "y"], ["z"]), ["x", "y"]);
  assert.deepEqual(normalizeVocabularyList(["  ", ""], ["z"]), ["z"]);
});

test("normalizeVocabulary fills defaults for missing fields", () => {
  const vocab = normalizeVocabulary(null);
  assert.ok(vocab.job_functions.includes("后端"));
  assert.ok(vocab.seniorities.includes("高级"));
  assert.ok(vocab.statuses.includes("面试中"));
});

test("normalizeVocabulary keeps provided fields", () => {
  const vocab = normalizeVocabulary({
    job_functions: [" 后端 "],
    seniorities: [],
    statuses: ["进行中"],
  });
  assert.deepEqual(vocab.job_functions, ["后端"]);
  assert.ok(vocab.seniorities.length > 0);
  assert.deepEqual(vocab.statuses, ["进行中"]);
});

/* ------------------------------------------------------------------ */
/* job status                                                          */
/* ------------------------------------------------------------------ */

test("canonicalJobStatus maps aliases and passes through unknowns", () => {
  assert.equal(canonicalJobStatus("未投递"), "draft");
  assert.equal(canonicalJobStatus("已投递"), "applied");
  assert.equal(canonicalJobStatus("面试中"), "interview");
  assert.equal(canonicalJobStatus("已拿Offer"), "offer");
  assert.equal(canonicalJobStatus("放弃"), "withdrawn");
  assert.equal(canonicalJobStatus("applied"), "applied");
  assert.equal(canonicalJobStatus("自定义"), "自定义");
  assert.equal(canonicalJobStatus(null), "");
  assert.equal(canonicalJobStatus("  "), "");
});

test("jobStatusLabel maps canonical back to Chinese label", () => {
  assert.equal(jobStatusLabel("draft"), "未投递");
  assert.equal(jobStatusLabel("未投递"), "未投递");
  assert.equal(jobStatusLabel("whatever"), "whatever");
});

/* ------------------------------------------------------------------ */
/* parseImportText                                                     */
/* ------------------------------------------------------------------ */

test("parseImportText parses JSON arrays", () => {
  assert.deepEqual(parseImportText('[{"title": "A"}, {"title": "B"}]', "paste"), [
    { title: "A" },
    { title: "B" },
  ]);
});

test("parseImportText treats .json files as JSON and returns [] on parse errors", () => {
  assert.deepEqual(parseImportText("not json", "jobs.json"), []);
  assert.deepEqual(parseImportText('{"a":1}', "x.json"), []);
});

test("parseImportText parses CSV with headers", () => {
  const rows = parseImportText(
    "title,company,location\n后端工程师,Acme,上海\n前端工程师,Beta,北京",
    "paste",
  );
  assert.deepEqual(rows, [
    { title: "后端工程师", company: "Acme", location: "上海" },
    { title: "前端工程师", company: "Beta", location: "北京" },
  ]);
});

test("parseImportText returns [] for blank input", () => {
  assert.deepEqual(parseImportText("   ", "paste"), []);
});

/* ------------------------------------------------------------------ */
/* parseHashValue                                                      */
/* ------------------------------------------------------------------ */

test("parseHashValue resolves workspace and resume routes with ids", () => {
  assert.deepEqual(parseHashValue("#/workspace/job-123"), {
    name: "workspace",
    jobId: "job-123",
  });
  assert.deepEqual(parseHashValue("#/resume/r-1"), {
    name: "resume",
    jobId: null,
    resumeId: "r-1",
  });
});

test("parseHashValue decodes URI components in ids", () => {
  assert.deepEqual(parseHashValue("#/workspace/abc%20def"), {
    name: "workspace",
    jobId: "abc def",
  });
});

test("parseHashValue falls back to resume for unknown or empty routes", () => {
  assert.deepEqual(parseHashValue(""), { name: "resume", jobId: null, resumeId: null });
  assert.deepEqual(parseHashValue("#/nope"), { name: "resume", jobId: null, resumeId: null });
  assert.deepEqual(parseHashValue("#/workspace"), { name: "workspace", jobId: null, resumeId: null });
});

test("parseHashValue keeps raw value when decodeURIComponent throws", () => {
  const result = parseHashValue("#/workspace/%E0%A4%A");
  assert.equal(result.name, "workspace");
  assert.equal(result.jobId, "%E0%A4%A");
});

/* ------------------------------------------------------------------ */
/* lineDiff                                                            */
/* ------------------------------------------------------------------ */

test("lineDiff reports added and removed lines", () => {
  const rows = lineDiff("a\nb\nc", "a\nc\nd");
  assert.deepEqual(rows, [
    { type: "remove", text: "b" },
    { type: "add", text: "d" },
  ]);
});

test("lineDiff ignores blank lines and returns [] for identical input", () => {
  assert.deepEqual(lineDiff("x\n\ny", "x\n\ny"), []);
  assert.deepEqual(lineDiff("", ""), []);
});

test("lineDiff compares by trimmed content", () => {
  const rows = lineDiff("a  ", "a");
  assert.deepEqual(rows, []);
});

/* ------------------------------------------------------------------ */
/* matchTone                                                           */
/* ------------------------------------------------------------------ */

test("matchTone buckets scores at 80/60 boundaries", () => {
  assert.equal(matchTone(null), "");
  assert.equal(matchTone(90), "match--high");
  assert.equal(matchTone(80), "match--high");
  assert.equal(matchTone(70), "match--mid");
  assert.equal(matchTone(60), "match--mid");
  assert.equal(matchTone(30), "match--low");
});

/* ------------------------------------------------------------------ */
/* benchmarkSourceBadge                                                */
/* ------------------------------------------------------------------ */

test("benchmarkSourceBadge labels the settings-table source with city", () => {
  const badge = benchmarkSourceBadge({
    benchmark_source: "设置表（城市）",
    city_normalized: "上海",
  });
  assert.equal(badge.className, "badge-teal");
  assert.equal(badge.label, "设置表（上海）");
  assert.match(badge.detail, /城市归一化：上海/);
});

test("benchmarkSourceBadge labels library-median and neutral sources", () => {
  const median = benchmarkSourceBadge({ benchmark_source: "库内同类中位" });
  assert.equal(median.className, "badge-gray");
  assert.equal(median.label, "库内同类中位");
  const neutral = benchmarkSourceBadge({});
  assert.equal(neutral.className, "badge-amber");
  assert.equal(neutral.label, "暂无基准，中性处理");
});

/* ------------------------------------------------------------------ */
/* isJdUrl                                                             */
/* ------------------------------------------------------------------ */

test("isJdUrl detects http(s) URLs after trimming", () => {
  assert.equal(isJdUrl("https://example.com/jobs/1"), true);
  assert.equal(isJdUrl("  http://example.com/x  "), true);
  assert.equal(isJdUrl("ftp://example.com"), false);
  assert.equal(isJdUrl("后端工程师"), false);
  assert.equal(isJdUrl(""), false);
  assert.equal(isJdUrl(null), false);
});

/* ------------------------------------------------------------------ */
/* buildDiagnosisMarkdownFrom                                          */
/* ------------------------------------------------------------------ */

test("buildDiagnosisMarkdownFrom renders full diagnosis markdown", () => {
  const md = buildDiagnosisMarkdownFrom(
    {
      score: 72,
      model: "deepseek-chat",
      skills: ["Python", "FastAPI"],
      issues: ["缺少量化结果"],
      suggestions: ["补充性能数据"],
    },
    "我的简历",
    "原始内容",
  );
  assert.match(md, /^# 我的简历/);
  assert.match(md, /> 诊断分：72 \/ 100 · 模型：deepseek-chat/);
  assert.match(md, /## 技能/);
  assert.match(md, /- Python/);
  assert.match(md, /## 问题/);
  assert.match(md, /- 缺少量化结果/);
  assert.match(md, /## 优化建议/);
  assert.match(md, /- 补充性能数据/);
  assert.match(md, /## 原始简历/);
  assert.match(md, /原始内容/);
});

test("buildDiagnosisMarkdownFrom handles empty diagnosis gracefully", () => {
  const md = buildDiagnosisMarkdownFrom({}, "简历诊断", "");
  assert.equal(md, "# 简历诊断\n\n> 诊断分：— / 100 · 模型：未知\n");
});
