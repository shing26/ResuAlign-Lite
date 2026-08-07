import { test } from "node:test";
import assert from "node:assert/strict";
import {
  applyAcceptedDiffsToDraft,
  applyDiffToDraft,
  benchmarkSourceBadge,
  buildDiagnosisMarkdownFrom,
  buildWbResultHtmlFrom,
  canonicalJobStatus,
  cmpLineHtml,
  esc,
  formatDate,
  formatElapsed,
  formatSalary,
  hasEvalResult,
  inlineDiff,
  isJdUrl,
  isJunkJd,
  jobCompleteness,
  jobCompletenessBadge,
  jobEditFormHtml,
  jobStatusLabel,
  jobTimelineFormHtml,
  lineDiff,
  matchBadgeInfo,
  matchTone,
  normalizeVocabulary,
  normalizeVocabularyList,
  options,
  parseHashValue,
  parseImportText,
  renderInlineDiffSide,
  renderMatchBadge,
  runEvalFromForm,
  tokenizeInline,
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
    resumeId: null,
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
    resumeId: null,
  });
});

test("parseHashValue parses ?resume= deep-link query into resumeId", () => {
  assert.deepEqual(parseHashValue("#/workspace/job-1?resume=r-42"), {
    name: "workspace",
    jobId: "job-1",
    resumeId: "r-42",
  });
  assert.deepEqual(parseHashValue("#/workspace?resume=r-42"), {
    name: "workspace",
    jobId: null,
    resumeId: "r-42",
  });
  assert.deepEqual(parseHashValue("#/workspace/job-1?resume=r%2042"), {
    name: "workspace",
    jobId: "job-1",
    resumeId: "r 42",
  });
  assert.deepEqual(parseHashValue("#/workspace?other=1"), {
    name: "workspace",
    jobId: null,
    resumeId: null,
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
/* Inline diff (token-level) + cmp line HTML                           */
/* ------------------------------------------------------------------ */

test("tokenizeInline splits CJK chars and keeps ASCII words/whitespace runs", () => {
  assert.deepEqual(tokenizeInline("负责系统开发"), ["负", "责", "系", "统", "开", "发"]);
  assert.deepEqual(tokenizeInline("Redis 缓存3年"), ["Redis", " ", "缓", "存", "3", "年"]);
  assert.deepEqual(tokenizeInline(""), []);
  assert.deepEqual(tokenizeInline(null), []);
});

test("inlineDiff marks only the changed word on single-word edits", () => {
  const segments = inlineDiff("负责系统开发", "负责高并发系统开发");
  assert.deepEqual(segments, [
    { type: "same", text: "负责" },
    { type: "ins", text: "高并发" },
    { type: "same", text: "系统开发" },
  ]);
});

test("inlineDiff merges consecutive segments and handles full replacement", () => {
  assert.deepEqual(inlineDiff("负责系统开发", "负责系统开发"), [
    { type: "same", text: "负责系统开发" },
  ]);
  assert.deepEqual(inlineDiff("abc", "xyz"), [
    { type: "del", text: "abc" },
    { type: "ins", text: "xyz" },
  ]);
});

test("inlineDiff handles insertions at the start and deletions at the end", () => {
  assert.deepEqual(inlineDiff("系统", "高并发系统"), [
    { type: "ins", text: "高并发" },
    { type: "same", text: "系统" },
  ]);
  assert.deepEqual(inlineDiff("系统", "系"), [
    { type: "same", text: "系" },
    { type: "del", text: "统" },
  ]);
  // ASCII words are single tokens: "React" -> "React Native" inserts " Native".
  assert.deepEqual(inlineDiff("React", "React Native"), [
    { type: "same", text: "React" },
    { type: "ins", text: " Native" },
  ]);
});

test("renderInlineDiffSide shows del on original side and ins on proposed side", () => {
  // Pure insertion: original side stays plain, proposed side marks 高并发.
  const originalSide = renderInlineDiffSide("负责系统开发", "负责高并发系统开发", "original");
  assert.equal(originalSide, "负责系统开发");
  assert.ok(!originalSide.includes("diff-char"));
  const proposedSide = renderInlineDiffSide("负责系统开发", "负责高并发系统开发", "proposed");
  assert.ok(proposedSide.includes('<span class="diff-char-ins">高并发</span>'));
  assert.ok(!proposedSide.includes("diff-char-del"));
  // Pure deletion: original side marks 高并发, proposed side stays plain.
  const deletedSide = renderInlineDiffSide("负责高并发系统开发", "负责系统开发", "original");
  assert.ok(deletedSide.includes('<span class="diff-char-del">高并发</span>'));
  assert.ok(!deletedSide.includes("diff-char-ins"));
  assert.equal(renderInlineDiffSide("负责高并发系统开发", "负责系统开发", "proposed"), "负责系统开发");
});

test("renderInlineDiffSide escapes text inside and outside marks", () => {
  const html = renderInlineDiffSide("<b>x", "<b>y", "proposed");
  assert.ok(html.includes("&lt;b&gt;"));
  assert.ok(!html.includes("<b>"));
  assert.ok(html.includes('<span class="diff-char-ins">y</span>'));
});

test("cmpLineHtml emits addressable rows with 1-based visible numbers", () => {
  assert.equal(
    cmpLineHtml(0, "diff-add", "＋", "abc"),
    '<div class="cmp-line diff-add" data-line="0"><span class="cmp-line-num">1</span>＋abc</div>',
  );
  assert.ok(cmpLineHtml(9, "", "", "x").includes('data-line="9"'));
  assert.ok(cmpLineHtml(9, "", "", "x").includes(">10<"));
  assert.ok(cmpLineHtml(0, "diff-modify", "", "x").includes('class="cmp-line diff-modify"'));
});

/* ------------------------------------------------------------------ */
/* buildWbResultHtmlFrom side view (line-level + char-level marks)     */
/* ------------------------------------------------------------------ */

const WB_RESULT = {
  tailored_resume: { sections: { a: "负责高并发系统开发" } },
  score: 70,
  model: "deepseek-chat",
  elapsed_seconds: 3,
};

test("buildWbResultHtmlFrom marks modify rows with char-level spans and line numbers", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    [{ type: "modify", original: "负责系统开发", proposed: "负责高并发系统开发" }],
    new Set(),
    "负责系统开发",
    "side",
  );
  assert.ok(html.includes('class="cmp-line diff-modify" data-line="0"'));
  assert.ok(html.includes('<span class="cmp-line-num">1</span>'));
  assert.ok(html.includes('<span class="diff-char-ins">高并发</span>'));
});

test("buildWbResultHtmlFrom keeps diff-remove/diff-add line semantics", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    [{ type: "add", original: "", proposed: "负责高并发系统开发" }],
    new Set(),
    "旧行",
    "side",
  );
  assert.ok(html.includes('class="cmp-line diff-remove" data-line="0"'));
  assert.ok(html.includes("−"));
  assert.ok(html.includes('class="cmp-line diff-add" data-line="0"'));
  assert.ok(html.includes("＋"));
});

test("buildWbResultHtmlFrom leaves unchanged lines plain", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    [],
    new Set(),
    "负责高并发系统开发",
    "side",
  );
  assert.ok(html.includes('class="cmp-line" data-line="0"'));
  assert.ok(!html.includes("diff-remove"));
  assert.ok(!html.includes("diff-add"));
  assert.ok(!html.includes("diff-char"));
});

test("buildWbResultHtmlFrom list view omits compare columns", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    [{ type: "modify", original: "负责系统开发", proposed: "负责高并发系统开发" }],
    new Set(),
    "负责系统开发",
    "list",
  );
  assert.ok(!html.includes("cmp-column"));
  assert.ok(html.includes("diff-line diff-remove"));
  assert.ok(html.includes("diff-line diff-add"));
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

/* ------------------------------------------------------------------ */
/* U7 diff 应用纯函数                                                   */
/* ------------------------------------------------------------------ */

test("applyDiffToDraft applies modify / add / remove diffs", () => {
  const modify = applyDiffToDraft("负责系统开发", {
    type: "modify",
    original: "负责系统开发",
    proposed: "负责高并发系统开发",
  });
  assert.equal(modify, "负责高并发系统开发");

  const add = applyDiffToDraft("已有行", { type: "add", proposed: "新增行" });
  assert.equal(add, "已有行\n新增行");

  const remove = applyDiffToDraft("A行\nB行", {
    type: "remove",
    original: "B行",
  });
  assert.equal(remove, "A行\n");

  assert.equal(applyDiffToDraft("原样", { type: "unknown" }), "原样");
  assert.equal(applyDiffToDraft("原样", null), "原样");
  assert.equal(applyDiffToDraft(undefined, { type: "add", proposed: "x" }), "\nx");
});

test("applyAcceptedDiffsToDraft applies only the accepted diff set", () => {
  const diffs = [
    { diff_id: "a1", type: "modify", original: "旧技能", proposed: "新技能" },
    { diff_id: "b2", type: "add", proposed: "量化成果" },
    { diff_id: "c3", type: "remove", original: "冗余行" },
  ];
  const draft = applyAcceptedDiffsToDraft("旧技能\n冗余行", diffs, ["b2"]);
  assert.equal(draft, "旧技能\n冗余行\n量化成果");

  const none = applyAcceptedDiffsToDraft("旧技能\n冗余行", diffs, []);
  assert.equal(none, "旧技能\n冗余行");

  const all = applyAcceptedDiffsToDraft("旧技能\n冗余行", diffs, ["a1", "b2", "c3"]);
  assert.equal(all, "新技能\n\n量化成果");

  /* 不存在的 id 忽略 */
  const unknown = applyAcceptedDiffsToDraft("旧技能", diffs, ["zzz"]);
  assert.equal(unknown, "旧技能");
});

test("applyAcceptedDiffsToDraft falls back to diff-index keys", () => {
  const diffs = [
    { type: "add", proposed: "X" },
    { type: "add", proposed: "Y" },
  ];
  const draft = applyAcceptedDiffsToDraft("底稿", diffs, ["diff-1"]);
  assert.equal(draft, "底稿\nY");
});

/* ------------------------------------------------------------------ */
/* F10/U11 匹配度来源标注                                               */
/* ------------------------------------------------------------------ */

test("matchBadgeInfo prefers eval score, then gap, then persisted job score", () => {
  const session = {
    alignment: { eval_score: { jd_match_score: 88 } },
    gap: { score: 60 },
  };
  assert.deepEqual(matchBadgeInfo(session, { match_score: 50 }), {
    score: 88,
    source: "来自对齐评估",
  });

  assert.deepEqual(
    matchBadgeInfo({ gap: { score: 60 } }, { match_score: 50 }),
    { score: 60, source: "来自差距分析" },
  );

  assert.deepEqual(matchBadgeInfo({}, { match_score: 50 }), {
    score: 50,
    source: "来自对齐评估",
  });

  assert.deepEqual(matchBadgeInfo({}, {}), { score: null, source: "" });
  assert.deepEqual(matchBadgeInfo(null, null), { score: null, source: "" });
});

test("renderMatchBadge renders score, source title and muted source label", () => {
  const html = renderMatchBadge(
    { alignment: { eval_score: { jd_match_score: 82.4 } } },
    {},
  );
  assert.match(html, /class="match-badge match--high" data-match-badge/);
  assert.match(html, /title="来自对齐评估"/);
  assert.match(html, />匹配 82</);
  assert.match(html, /data-match-source>来自对齐评估</);

  assert.equal(renderMatchBadge({}, {}), "");
});

/* ------------------------------------------------------------------ */
/* F6/U10 时间线弹窗 / 编辑弹窗表单 HTML                                 */
/* ------------------------------------------------------------------ */

test("jobTimelineFormHtml includes structured follow-up fields", () => {
  const html = jobTimelineFormHtml({
    job_id: "j1",
    status: "interview",
    next_step_due_at: "2026-08-10T14:30",
    interview_stage: "二面",
  });
  assert.match(html, /data-form="job-detail-edit"/);
  assert.match(html, /type="datetime-local" name="next_step_due_at" value="2026-08-10T14:30"/);
  assert.match(html, /name="interview_stage"/);
  assert.match(html, /<option value=""\s*>无<\/option>/);
  assert.match(html, /<option value="一面"\s*>一面<\/option>/);
  assert.match(html, /<option value="二面" selected>二面<\/option>/);
  assert.match(html, /<option value="HR面"\s*>HR面<\/option>/);
  assert.match(html, /<option value="谈薪"\s*>谈薪<\/option>/);
  assert.match(html, /<option value="笔试"\s*>笔试<\/option>/);
  assert.match(html, /<option value="其他"\s*>其他<\/option>/);
  /* 未设置阶段时默认“无” */
  const empty = jobTimelineFormHtml({ job_id: "j2", status: "draft" });
  assert.match(empty, /name="interview_stage"><option value="" selected>无<\/option>/);
  assert.match(empty, /type="datetime-local" name="next_step_due_at" value=""/);});

test("jobEditFormHtml adds the reclassify secondary action", () => {
  const html = jobEditFormHtml(
    { job_id: "j1", title: "后端", jd_text: "JD", tech_tags: ["Go"] },
    { statuses: ["面试中"], job_functions: ["后端"], seniorities: ["高级"] },
  );
  assert.match(html, /data-form="job-edit"/);
  assert.match(html, /data-action="reclassify-job" data-id="j1">重新分类<\/button>/);
  assert.match(html, /type="submit">保存<\/button>/);
  /* 未传 vocabulary 时回退内置列表 */
  const fallback = jobEditFormHtml({ job_id: "j2", title: "T", jd_text: "" });
  assert.match(fallback, /<option value="后端" >后端<\/option>/);
});

/* ------------------------------------------------------------------ */
/* B7 采集数据完整性：jobCompleteness / isJunkJd / jobCompletenessBadge */
/* ------------------------------------------------------------------ */

test("jobCompleteness returns [] for a complete job", () => {
  assert.deepEqual(
    jobCompleteness({
      title: "后端",
      company: "Acme",
      salary_min: 20000,
      salary_max: 30000,
    }),
    [],
  );
  /* salary 只有一界也算完整（面议/开口岗位） */
  assert.deepEqual(
    jobCompleteness({ title: "T", company: "C", salary_min: 20000 }),
    [],
  );
});

test("jobCompleteness lists missing title/company/salary", () => {
  assert.deepEqual(jobCompleteness({ title: "T" }), ["company", "salary"]);
  assert.deepEqual(jobCompleteness({ company: "C" }), ["title", "salary"]);
  assert.deepEqual(
    jobCompleteness({ title: "T", company: "C" }),
    ["salary"],
  );
  assert.deepEqual(jobCompleteness({}), ["title", "company", "salary"]);
  assert.deepEqual(jobCompleteness(null), ["title", "company", "salary"]);
  assert.deepEqual(jobCompleteness(undefined), ["title", "company", "salary"]);
  /* 空白 title 视为缺失 */
  assert.deepEqual(
    jobCompleteness({ title: "   ", company: "C", salary_max: 1 }),
    ["title"],
  );
});

test("isJunkJd detects whole-page JSON payloads", () => {
  assert.equal(isJunkJd('{"pageConfig":{"title":"x"}}'), true);
  assert.equal(isJunkJd('  [{"id":1},{"id":2}]'), true);
  assert.equal(isJunkJd("{\n  \"name\": \"__NEXT_DATA__\"\n}"), true);
});

test("isJunkJd detects whole-page HTML with many scripts", () => {
  const html = `<!DOCTYPE html><html><head></head><body>
    <script>var a = 1;</script>
    <script>var b = 2;</script>
    <script>var c = 3;</script>
    <div>岗位内容</div></body></html>`;
  assert.equal(isJunkJd(html), true);
});

test("isJunkJd detects SPA inline state markers", () => {
  assert.equal(
    isJunkJd('<html><head></head><body><script>window.pageConfig = {}</script></body></html>'),
    true,
  );
  assert.equal(
    isJunkJd('<html>__NEXT_DATA__</html>'),
    true,
  );
});

test("isJunkJd passes normal JD text", () => {
  assert.equal(
    isJunkJd("岗位职责：负责后端服务开发。任职要求：3 年以上经验。"),
    false,
  );
  /* 单个 script 标签（如岗位描述提及）不算整页 */
  assert.equal(isJunkJd("我们需要熟悉 <script> 语法的工程师"), false);
  assert.equal(isJunkJd(""), false);
  assert.equal(isJunkJd(null), false);
  assert.equal(isJunkJd(undefined), false);
});

test("jobCompletenessBadge returns empty for complete jobs", () => {
  assert.equal(
    jobCompletenessBadge({
      title: "后端",
      company: "Acme",
      salary_min: 1,
    }),
    "",
  );
});

test("jobCompletenessBadge shows 待补全 with missing detail on title", () => {
  const html = jobCompletenessBadge({ title: "后端" });
  assert.match(html, /badge-amber/);
  assert.match(html, />待补全</);
  assert.match(html, /title="缺少：公司、薪资"/);
  const html2 = jobCompletenessBadge({ title: "后端", company: "Acme" });
  assert.match(html2, /title="缺少：薪资"/);
});

test("jobCompletenessBadge prefers 抓取失败 for junk JD", () => {
  const html = jobCompletenessBadge({
    title: "后端",
    company: "Acme",
    jd_text: '{"pageConfig":{}}',
  });
  assert.match(html, />抓取失败，可重试</);
  assert.doesNotMatch(html, />待补全</);
});

/* ------------------------------------------------------------------ */
/* U5 耗时格式化：formatElapsed                                         */
/* ------------------------------------------------------------------ */

test("formatElapsed shows seconds under a minute", () => {
  assert.equal(formatElapsed(0), "0s");
  assert.equal(formatElapsed(5_000), "5s");
  assert.equal(formatElapsed(59_999), "59s");
});

test("formatElapsed switches to 分:秒 after a minute", () => {
  assert.equal(formatElapsed(60_000), "1:00");
  assert.equal(formatElapsed(90_000), "1:30");
  assert.equal(formatElapsed(3_600_000), "60:00");
  assert.equal(formatElapsed(3_661_000), "61:01");
});

test("formatElapsed clamps negatives and handles missing input", () => {
  assert.equal(formatElapsed(-1000), "0s");
  assert.equal(formatElapsed(null), "0s");
  assert.equal(formatElapsed(undefined), "0s");
  assert.equal(formatElapsed("5000"), "5s");
});

/* ------------------------------------------------------------------ */
/* F1 Eval 开关：hasEvalResult / runEvalFromForm                        */
/* ------------------------------------------------------------------ */

test("hasEvalResult is true when any eval field exists", () => {
  assert.equal(hasEvalResult({ jd_match_score: 80 }), true);
  assert.equal(hasEvalResult({ hallucination_detected: false }), true);
  assert.equal(hasEvalResult({ improvement: 0 }), true);
  assert.equal(hasEvalResult({ gap_coverage: "60%" }), true);
  assert.equal(hasEvalResult({}), false);
  assert.equal(hasEvalResult(null), false);
  assert.equal(hasEvalResult(undefined), false);
});

test("runEvalFromForm maps checked to true, unchecked to undefined", () => {
  assert.equal(runEvalFromForm({ run_eval: "on" }), true);
  assert.equal(runEvalFromForm({ run_eval: true }), true);
  assert.equal(runEvalFromForm({}), undefined);
  assert.equal(runEvalFromForm({ run_eval: "off" }), undefined);
  assert.equal(runEvalFromForm(null), undefined);
});
