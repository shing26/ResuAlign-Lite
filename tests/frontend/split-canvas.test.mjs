import { test } from "node:test";
import assert from "node:assert/strict";
import {
  alignProgressPercent,
  alignmentControls,
  boardCard,
  buildWbResultHtmlFrom,
  crawlStatusLine,
  diffCard,
  diffList,
  exportDock,
  jdProfileSummary,
  radarHtml,
  renderBoardCard,
  renderGap,
  renderSkills,
  stageProgress,
  stageStepper,
} from "../../src/resualign/static/app/format.js";

const EMPTY_SESSION = {};

const READY_SESSION = {
  crawl: { status: "succeeded" },
  jd: { status: "ready", profile: { job_title: "后端工程师" } },
  gap: { status: "ready" },
  alignment: { status: "succeeded" },
};

/* ------------------------------------------------------------------ */
/* alignProgressPercent                                                */
/* ------------------------------------------------------------------ */

test("alignProgressPercent maps known stages and falls back", () => {
  assert.equal(alignProgressPercent("tailoring"), 85);
  assert.equal(alignProgressPercent("succeeded"), 100);
  assert.equal(alignProgressPercent("queued"), 5);
  assert.equal(alignProgressPercent("unknown-stage"), 55);
  assert.equal(alignProgressPercent(""), 8);
  assert.equal(alignProgressPercent(null), 8);
});

/* ------------------------------------------------------------------ */
/* jdProfileSummary                                                    */
/* ------------------------------------------------------------------ */

test("jdProfileSummary extracts the summary object or null", () => {
  assert.equal(jdProfileSummary(null), null);
  assert.deepEqual(
    jdProfileSummary({
      job_title: "后端",
      seniority: "高级",
      education_requirements: ["本科"],
      business_scene: "高并发",
    }),
    { title: "后端", seniority: "高级", education: ["本科"], summary: "高并发" },
  );
});

test("jdProfileSummary falls back through alternate fields", () => {
  assert.deepEqual(
    jdProfileSummary({ title: "T", experience_level: "资深", summary: "S" }),
    { title: "T", seniority: "资深", education: [], summary: "S" },
  );
  assert.deepEqual(jdProfileSummary({}), {
    title: "目标岗位",
    seniority: "",
    education: [],
    summary: "",
  });
});

/* ------------------------------------------------------------------ */
/* stageProgress / stageStepper                                        */
/* ------------------------------------------------------------------ */

test("stageProgress marks no steps for an empty session", () => {
  const steps = stageProgress(EMPTY_SESSION);
  assert.equal(steps.length, 5);
  assert.deepEqual(
    steps.map((s) => s.key),
    ["crawl", "classify", "profile", "gap", "align"],
  );
  for (const step of steps) {
    assert.equal(step.done, false);
    assert.equal(step.active, false);
  }
});

test("stageProgress marks completed stages for a ready session", () => {
  const steps = stageProgress(READY_SESSION);
  const done = steps.filter((s) => s.done).map((s) => s.key);
  assert.deepEqual(done, ["crawl", "classify", "profile", "gap", "align"]);
});

test("stageProgress marks crawl active while queued", () => {
  const steps = stageProgress({
    crawl: { status: "queued" },
    jd: {},
    gap: {},
    alignment: {},
  });
  const crawl = steps.find((s) => s.key === "crawl");
  assert.equal(crawl.active, true);
  assert.equal(crawl.done, false);
});

test("stageProgress treats idle crawl as done and blocked gap as done", () => {
  const steps = stageProgress({
    crawl: { status: "idle" },
    jd: { status: "ready" },
    gap: { status: "blocked" },
    alignment: {},
  });
  assert.equal(steps.find((s) => s.key === "crawl").done, true);
  assert.equal(steps.find((s) => s.key === "gap").done, true);
  assert.equal(steps.find((s) => s.key === "align").done, false);
});

test("stageStepper renders step labels with done/active classes", () => {
  const html = stageStepper(READY_SESSION);
  assert.match(html, /data-split-stepper/);
  assert.match(html, /split-step is-done/);
  assert.match(html, />抓取<\/span>/);
  assert.match(html, />对齐<\/span>/);
  const emptyHtml = stageStepper(EMPTY_SESSION);
  assert.doesNotMatch(emptyHtml, /is-done/);
});

/* ------------------------------------------------------------------ */
/* crawlStatusLine                                                     */
/* ------------------------------------------------------------------ */

test("crawlStatusLine returns empty for idle", () => {
  assert.equal(crawlStatusLine({}), "");
  assert.equal(crawlStatusLine({ crawl: { status: "idle" } }), "");
});

test("crawlStatusLine renders status text and escaped error", () => {
  const queued = crawlStatusLine({ crawl: { status: "queued" } });
  assert.match(queued, /排队抓取中\.\.\./);
  const failed = crawlStatusLine({ crawl: { status: "failed", error: "超时<x>" } });
  assert.match(failed, /抓取失败/);
  assert.match(failed, /&lt;x&gt;/);
});

/* ------------------------------------------------------------------ */
/* renderSkills / renderGap                                            */
/* ------------------------------------------------------------------ */

test("renderSkills renders required and nice-to-have chips", () => {
  const html = renderSkills({
    required_skills: ["Python", "FastAPI"],
    nice_to_have_skills: ["Redis"],
  });
  assert.match(html, /chip chip--required">Python<\/span>/);
  assert.match(html, /加分技能/);
  assert.match(html, />Redis<\/span>/);
  assert.doesNotMatch(html, /暂无提取结果/);
});

test("renderSkills shows extraction placeholder when skills are empty", () => {
  const html = renderSkills({});
  assert.match(html, /暂无提取结果/);
});

test("renderGap renders blocks for each gap section", () => {
  const html = renderGap({
    missing_keywords: ["K8s"],
    strength_matches: ["Python"],
    misaligned_emphasis: ["前端"],
  });
  assert.match(html, /gap-group--missing/);
  assert.match(html, />K8s<\/span>/);
  assert.match(html, /gap-group--strength/);
  assert.match(html, /gap-tag--ok/);
  assert.match(html, /gap-group--warn/);
});

test("renderGap returns null for empty gap and placeholder when blank", () => {
  assert.equal(renderGap(null), null);
  assert.match(renderGap({}), /尚未生成差距报告/);
});

/* ------------------------------------------------------------------ */
/* radarHtml                                                           */
/* ------------------------------------------------------------------ */

test("radarHtml renders radar markup with clamped score", () => {
  const html = radarHtml(85);
  assert.match(html, /data-match-radar/);
  assert.match(html, /aria-label="岗位匹配雷达"/);
  assert.match(html, /<strong>85<\/strong>/);
  assert.match(html, /radar-fill/);
  assert.match(html, />硬技能</);
  const clamped = radarHtml(150);
  assert.match(clamped, /<strong>100<\/strong>/);
  const low = radarHtml(-5);
  assert.match(low, /<strong>0<\/strong>/);
});

/* ------------------------------------------------------------------ */
/* diffCard / diffList                                                 */
/* ------------------------------------------------------------------ */

const SAMPLE_DIFF = {
  diff_id: "d1",
  type: "modify",
  original: "旧句",
  proposed: "新句",
  reason: "更贴合 JD",
  confidence: "high",
  provenance: "来源：项目经历",
  provenance_state: "verified",
};

test("diffCard renders actionable modify card with provenance", () => {
  const html = diffCard(SAMPLE_DIFF, 0, "job-1");
  assert.match(html, /data-diff-id="d1"/);
  assert.match(html, /data-action="accept-bullet"/);
  assert.match(html, /来源已验证/);
  assert.match(html, /置信度 high/);
  assert.doesNotMatch(html, /diff-card--invalid/);
});

test("diffCard flags add diffs without provenance as invalid gate", () => {
  const html = diffCard({ type: "add", proposed: "凭空新增" }, 1, "job-1");
  assert.match(html, /diff-card--invalid/);
  assert.doesNotMatch(html, /data-action="accept-bullet"/);
  assert.match(html, /无来源新增/);
  assert.match(html, /diff-id="diff-1"/);
});

test("diffList renders cards or the empty state", () => {
  const html = diffList({ alignment: { diffs: [SAMPLE_DIFF] } }, "job-1");
  assert.match(html, /data-diff-list/);
  assert.match(html, /data-diff-id="d1"/);
  const empty = diffList({}, "job-1");
  assert.match(empty, /data-resume-canvas-empty/);
  assert.match(empty, /还没有对齐结果/);
});

/* ------------------------------------------------------------------ */
/* alignmentControls                                                   */
/* ------------------------------------------------------------------ */

test("alignmentControls renders form with selected resume and granularity options", () => {
  const html = alignmentControls(
    {
      resume: { selected_resume_id: "r2" },
      alignment: { status: "idle" },
    },
    [
      { resume_id: "r1", title: "简历一", current_version: 2 },
      { resume_id: "r2", title: "简历二", current_version: 1 },
    ],
    "job-9",
  );
  assert.match(html, /data-form="split-align"/);
  assert.match(html, /name="job_id" value="job-9"/);
  assert.match(html, /value="r2" selected/);
  assert.match(html, />重构<\/option>/);
  assert.match(html, /一键生成对齐简历/);
  assert.doesNotMatch(html, /data-align-progress/);
});

test("alignmentControls shows progress when running", () => {
  const html = alignmentControls(
    { alignment: { status: "running", stage: "tailoring" } },
    [],
    "job-9",
  );
  assert.match(html, /data-align-progress/);
  assert.match(html, /width:85%/);
  assert.match(html, /AI 改写简历/);
  assert.match(html, /disabled/);
});

/* ------------------------------------------------------------------ */
/* exportDock                                                          */
/* ------------------------------------------------------------------ */

test("exportDock renders all export actions and draft badge", () => {
  const html = exportDock("job-1", { alignment: { draft: "内容" } });
  assert.match(html, /data-export-dock/);
  assert.match(html, /copy-align-markdown/);
  assert.match(html, /export-align-markdown/);
  assert.match(html, /export-align-pdf/);
  assert.match(html, /export-align-json/);
  assert.match(html, /badge-green">已生成/);
  assert.doesNotMatch(exportDock("job-1", {}), /已生成/);
});

/* ------------------------------------------------------------------ */
/* boardCard (copilot board) vs renderBoardCard (jobs board)           */
/* ------------------------------------------------------------------ */

test("boardCard renders copilot card with drag handle and match badge", () => {
  const html = boardCard({
    job_id: "j1",
    title: "后端",
    company: "Acme",
    location: "上海",
    status: "未投递",
    match_score: 82.4,
    salary_min: 20000,
    salary_max: 30000,
  });
  assert.match(html, /copilot-card/);
  assert.match(html, /data-board-drag/);
  assert.match(html, /data-action="open-optimizer"/);
  assert.match(html, /data-action="delete-job"/);
  assert.match(html, /match--high/);
  assert.match(html, />82<\/span>/);
  assert.match(html, /20-30K/);
});

test("boardCard shows 待分析 when no match score", () => {
  const html = boardCard({ job_id: "j1", title: "T", status: "applied" });
  assert.match(html, /待分析/);
  assert.match(html, /match-badge--empty/);
});

test("renderBoardCard renders job-board card with check and edit actions", () => {
  const html = renderBoardCard({
    job_id: "j1",
    title: "前端",
    status: "面试中",
    classification_pending: false,
  });
  assert.match(html, /data-board-check/);
  assert.match(html, /data-action="open-job-detail"/);
  assert.match(html, /data-action="edit-job"/);
  assert.match(html, /data-action="delete-job"/);
  assert.match(html, /aria-label="选择 前端"/);
  assert.match(html, /value="interview" selected/);
  assert.doesNotMatch(html, /board-card--pending/);
  assert.match(
    renderBoardCard({ job_id: "j1", title: "T", status: "x", classification_pending: true }),
    /board-card--pending/,
  );
});

/* ------------------------------------------------------------------ */
/* buildWbResultHtmlFrom                                               */
/* ------------------------------------------------------------------ */

const WB_RESULT = {
  score: 88,
  model: "deepseek-chat",
  elapsed_seconds: 12,
  tailored_resume: { sections: { exp: "新经验" } },
  diffs: [
    {
      type: "modify",
      original: "旧经验",
      proposed: "新经验",
      reason: "对齐 JD",
      confidence: "中",
      provenance_quote: "来源句",
    },
  ],
};

test("buildWbResultHtmlFrom renders side-by-side view when compareView is side", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    WB_RESULT.diffs,
    new Set(),
    "旧经验",
    "side",
  );
  assert.match(html, /cmp-grid cmp-grid--workbench/);
  assert.match(html, /data-accept-diff="0"/);
  assert.match(html, /aria-pressed="true">并排对比/);
  assert.match(html, /score-ring--high/);
  assert.match(html, /diff-line diff-remove">- 旧经验/);
  assert.match(html, /diff-line diff-add">\+ 新经验/);
  assert.match(html, /Provenance 来源/);
});

test("buildWbResultHtmlFrom hides side view and respects accepted set", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    WB_RESULT.diffs,
    new Set([0]),
    "旧经验",
    "list",
  );
  assert.doesNotMatch(html, /cmp-grid/);
  assert.doesNotMatch(html, /data-accept-diff="0" checked/);
  assert.match(html, /aria-pressed="true">修改列表/);
});

test("buildWbResultHtmlFrom checks unaccepted diffs by default", () => {
  const html = buildWbResultHtmlFrom(
    WB_RESULT,
    WB_RESULT.diffs,
    new Set(),
    "旧经验",
    "list",
  );
  assert.match(html, /data-accept-diff="0" checked/);
});

test("buildWbResultHtmlFrom renders placeholder lines when content is empty", () => {
  const html = buildWbResultHtmlFrom({}, [], new Set(), "", "side");
  assert.match(html, /cmp-line/);
  assert.match(html, /无修改项/);
  assert.match(html, /暂无来源引用/);
});
