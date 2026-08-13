import { test } from "node:test";
import assert from "node:assert/strict";
import {
  alignProgressPercent,
  alignmentControls,
  boardCard,
  buildCmpSideHtml,
  buildLiveCompareHtml,
  crawlStatusLine,
  diffCard,
  diffList,
  diffSectionBadge,
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

/* T3: diff.section 徽章（后端契约：DiffItem.section，字符串，可为空） */

test("diffSectionBadge renders empty for missing or blank section", () => {
  assert.equal(diffSectionBadge(null), "");
  assert.equal(diffSectionBadge({}), "");
  assert.equal(diffSectionBadge({ section: undefined }), "");
  assert.equal(diffSectionBadge({ section: null }), "");
  assert.equal(diffSectionBadge({ section: "" }), "");
  assert.equal(diffSectionBadge({ section: "   " }), "");
});

test("diffSectionBadge renders an escaped badge for a non-empty section", () => {
  assert.equal(
    diffSectionBadge({ section: "工作经历" }),
    '<span class="badge badge-gray diff-card__section">工作经历</span>',
  );
  assert.equal(
    diffSectionBadge({ section: " <项目> & 技能" }),
    '<span class="badge badge-gray diff-card__section">&lt;项目&gt; &amp; 技能</span>',
  );
});

test("diffCard renders the section badge in the card head when section is set", () => {
  const html = diffCard({ ...SAMPLE_DIFF, section: "项目经历" }, 0, "job-1");
  assert.match(html, /<span class="badge badge-gray diff-card__section">项目经历<\/span>/);
  /* 徽章紧跟 type 徽章，位于卡片头部 .diff-card__type 内 */
  const typeGroup = html.match(/<div class="diff-card__type">([\s\S]*?)<\/div>/)[1];
  assert.match(typeGroup, /badge-blue">改写<\/span>/);
  assert.match(typeGroup, /diff-card__section">项目经历<\/span>/);
  assert.match(typeGroup, /置信度 high/);
});

test("diffCard omits the section badge when section is blank", () => {
  assert.doesNotMatch(diffCard({ ...SAMPLE_DIFF, section: "" }, 0, "job-1"), /diff-card__section/);
  assert.doesNotMatch(diffCard(SAMPLE_DIFF, 0, "job-1"), /diff-card__section/);
  assert.doesNotMatch(diffCard({ ...SAMPLE_DIFF, section: "   " }, 0, "job-1"), /diff-card__section/);
});

test("diffList carries section badges through diffCard and escapes them", () => {
  const session = {
    alignment: {
      diffs: [
        { ...SAMPLE_DIFF, section: "工作经历" },
        { ...SAMPLE_DIFF, diff_id: "d2", section: "" },
      ],
    },
  };
  const html = diffList(session, "job-1");
  assert.equal((html.match(/diff-card__section/g) || []).length, 1);
  assert.match(html, /diff-card__section">工作经历<\/span>/);
  const escaped = diffList(
    { alignment: { diffs: [{ ...SAMPLE_DIFF, section: "<危险> & 技能" }] } },
    "job-1",
  );
  assert.match(escaped, /diff-card__section">&lt;危险&gt; &amp; 技能<\/span>/);
  assert.doesNotMatch(escaped, /<危险>/);
});

/* ------------------------------------------------------------------ */
/* #17: live 工作台字符级高亮（卡片行内标记 + 并排对比视图）              */
/* ------------------------------------------------------------------ */

test("diffCard marks inserted characters on the proposed side", () => {
  const html = diffCard(
    { diff_id: "d2", type: "modify", original: "负责系统开发", proposed: "负责高并发系统开发" },
    0,
    "job-1",
  );
  // 采纳 interaction must survive the highlight change.
  assert.match(html, /data-action="accept-bullet"/);
  assert.match(html, /data-action="polish-bullet"/);
  // Inserted 高并发 is wrapped, the shared prefix/suffix stay plain.
  assert.match(html, /<span class="diff-char-ins">高并发<\/span>/);
  assert.equal((html.match(/diff-char-del/g) || []).length, 0);
  assert.match(html, /data-diff-original>负责系统开发<\/div>/);
  assert.match(html, /data-diff-proposed>负责<span class="diff-char-ins">高并发<\/span>系统开发<\/div>/);
});

test("diffCard marks deleted characters on the original side", () => {
  const html = diffCard(
    { diff_id: "d3", type: "modify", original: "负责高并发系统开发", proposed: "负责系统开发" },
    0,
    "job-1",
  );
  assert.match(html, /<span class="diff-char-del">高并发<\/span>/);
  assert.equal((html.match(/diff-char-ins/g) || []).length, 0);
  assert.match(html, /data-diff-proposed>负责系统开发<\/div>/);
});

test("diffCard keeps add/remove diffs plain (no counterpart to mark)", () => {
  const add = diffCard(
    { type: "add", proposed: "新行", provenance: "来源" },
    0,
    "job-1",
  );
  assert.match(add, /data-diff-original><\/div>/);
  assert.match(add, /data-diff-proposed>新行<\/div>/);
  assert.doesNotMatch(add, /diff-char-/);
  const remove = diffCard({ type: "remove", original: "旧行" }, 1, "job-1");
  assert.match(remove, /data-diff-original>旧行<\/div>/);
  assert.doesNotMatch(remove, /diff-char-/);
});

test("diffList renders cards with char-level marks and intact actions", () => {
  const session = {
    alignment: {
      diffs: [
        {
          diff_id: "d1",
          type: "modify",
          original: "负责系统开发",
          proposed: "负责高并发系统开发",
          provenance: "来源：项目经历",
          provenance_state: "verified",
        },
      ],
    },
  };
  const html = diffList(session, "job-1");
  assert.match(html, /data-diff-list/);
  assert.match(html, /<span class="diff-char-ins">高并发<\/span>/);
  assert.match(html, /data-action="accept-bullet"/);
  assert.match(html, /data-action="reject-bullet"/);
  assert.match(html, /data-action="polish-bullet"/);
});

test("diffList unchanged modify diffs produce no marks", () => {
  const html = diffList(
    {
      alignment: {
        diffs: [{ type: "modify", original: "完全一致", proposed: "完全一致" }],
      },
    },
    "job-1",
  );
  assert.match(html, /data-diff-list/);
  assert.doesNotMatch(html, /diff-char-/);
});

/* buildCmpSideHtml —— legacy result 视图与 live 并排对比共用的渲染核心 */

test("buildCmpSideHtml renders addressable lines with char-level marks", () => {
  const html = buildCmpSideHtml(
    "负责系统开发\n相同行",
    "负责高并发系统开发\n相同行",
    [{ type: "modify", original: "负责系统开发", proposed: "负责高并发系统开发" }],
  );
  assert.match(html, /cmp-grid cmp-grid--workbench/);
  assert.match(html, /data-line="0"/);
  assert.match(html, /cmp-line-num">1<\/span>/);
  assert.match(html, /<span class="diff-char-ins">高并发<\/span>/);
  // the unchanged second line appears in both columns without marks
  assert.equal((html.match(/相同行/g) || []).length, 2);
});

test("buildCmpSideHtml renders placeholder lines for empty input", () => {
  const html = buildCmpSideHtml("", "", []);
  assert.match(html, /cmp-grid/);
  assert.match(html, /cmp-line/);
});

/* buildLiveCompareHtml —— live 会话（alignment.draft + diffs）驱动 */

test("buildLiveCompareHtml builds compare from a live session", () => {
  const session = {
    alignment: {
      draft: "负责高并发系统开发",
      diffs: [{ type: "modify", original: "负责系统开发", proposed: "负责高并发系统开发" }],
    },
  };
  const html = buildLiveCompareHtml(session, "负责系统开发");
  assert.match(html, /cmp-grid/);
  assert.match(html, /<span class="diff-char-ins">高并发<\/span>/);
});

test("buildLiveCompareHtml tolerates missing draft and diffs", () => {
  const html = buildLiveCompareHtml({}, "");
  assert.match(html, /cmp-grid/);
  assert.match(html, /cmp-line/);
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

test("alignmentControls shows cancel button while queued/running only", () => {
  const running = alignmentControls(
    { alignment: { status: "running", stage: "tailoring" } },
    [],
    "job-9",
  );
  assert.match(running, /data-action="cancel-align-job"/);
  assert.doesNotMatch(running, /cancel-align-job" hidden/);
  const queued = alignmentControls(
    { alignment: { status: "queued" } },
    [],
    "job-9",
  );
  assert.doesNotMatch(queued, /cancel-align-job" hidden/);
  const idle = alignmentControls({ alignment: { status: "idle" } }, [], "job-9");
  assert.match(idle, /cancel-align-job" hidden/);
  const failed = alignmentControls({ alignment: { status: "failed", error: "x" } }, [], "job-9");
  assert.match(failed, /cancel-align-job" hidden/);
});

test("alignmentControls offers rerun on failure and keeps run button enabled", () => {
  const html = alignmentControls(
    { alignment: { status: "failed", error: "LLM 超时" } },
    [],
    "job-9",
  );
  assert.match(html, /重新运行对齐/);
  assert.match(html, /任务失败：LLM 超时/);
  assert.doesNotMatch(html, /data-align-run" disabled/);
  assert.doesNotMatch(html, /data-align-progress/);
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

test("boardCard shows 去投递 when source_url exists", () => {
  const html = boardCard({
    job_id: "j1",
    title: "后端",
    status: "applied",
    source_url: "https://example.com/jobs/1",
  });
  assert.match(html, /data-action="open-source-url"/);
  assert.match(html, /去投递 ↗/);
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
  assert.match(html, /data-action="open-job-timeline"/);
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

test("renderBoardCard shows 去投递 when source_url exists", () => {
  const html = renderBoardCard({
    job_id: "j1",
    title: "前端",
    status: "applied",
    source_url: "https://example.com/jobs/1",
  });
  assert.match(html, /data-action="open-source-url"/);
  assert.match(html, /去投递 ↗/);
});

/* F10: 看板卡片匹配徽章 title 标注来源（job.match_score 来自工作台评估） */
test("boardCard match badge title discloses the score source", () => {
  const html = boardCard({
    job_id: "j1",
    title: "后端",
    status: "applied",
    match_score: 80,
  });
  assert.match(html, /class="match-badge match--high" title="匹配度 · 来自对齐评估">80<\/span>/);
  assert.match(
    boardCard({ job_id: "j2", title: "T", status: "draft" }),
    /class="match-badge match-badge--empty" title="尚未分析">待分析<\/span>/,
  );
});

test("renderBoardCard match badge carries the source title", () => {
  const html = renderBoardCard({
    job_id: "j1",
    title: "前端",
    status: "applied",
    match_score: 66,
  });
  assert.match(html, /class="match-badge match--mid" title="匹配度 · 来自对齐评估">66<\/span>/);
  const empty = renderBoardCard({ job_id: "j2", title: "T", status: "draft" });
  assert.match(empty, /class="match-badge match-badge--empty" title="尚未分析">待分析<\/span>/);
});

/* F2: 分类待定徽章可点击重分类（badge → button，带 aria-label） */
test("boardCard classification-pending badge is a reclassify button", () => {
  const html = boardCard({
    job_id: "j1",
    title: "后端",
    status: "applied",
    classification_pending: true,
  });
  assert.match(
    html,
    /<button type="button" class="badge badge-amber badge-pending" data-action="reclassify-job" data-id="j1" aria-label="重新分类">分类待定<\/button>/,
  );
  assert.doesNotMatch(
    boardCard({ job_id: "j2", title: "T", status: "draft" }),
    /data-action="reclassify-job"/,
  );
});

test("renderBoardCard classification-pending badge is a reclassify button", () => {
  const html = renderBoardCard({
    job_id: "j1",
    title: "前端",
    status: "applied",
    classification_pending: true,
  });
  assert.match(
    html,
    /<button type="button" class="badge badge-amber badge-pending" data-action="reclassify-job" data-id="j1" aria-label="重新分类">分类待定<\/button>/,
  );
  assert.doesNotMatch(
    renderBoardCard({ job_id: "j2", title: "T", status: "draft" }),
    /data-action="reclassify-job"/,
  );
});

/* U11: 时间线按钮与岗位详情弹窗标题统一为「详情」 */
test("boardCard timeline action label is unified as 详情", () => {
  const html = boardCard({ job_id: "j1", title: "后端", status: "applied" });
  assert.match(html, /data-action="open-job-timeline" data-id="j1">详情<\/button>/);
  assert.doesNotMatch(html, />时间线<\/button>/);
});

/* ------------------------------------------------------------------ */
/* F1 工作台调优表单 per-run 评估开关                                   */
/* ------------------------------------------------------------------ */

test("alignmentControls includes a run_eval checkbox (unchecked by default)", () => {
  const html = alignmentControls(
    { alignment: { status: "idle" } },
    [],
    "job-9",
  );
  assert.match(html, /<input type="checkbox" name="run_eval">/);
  assert.match(html, /本次运行评估（幻觉检测 \/ JD 匹配分）/);
  assert.match(html, /不勾选则按设置页默认执行/);
  assert.doesNotMatch(html, /name="run_eval"[^>]*checked/);
});

/* ------------------------------------------------------------------ */
/* B7 卡片徽章：待补全 / 抓取失败                                       */
/* ------------------------------------------------------------------ */

test("boardCard shows 待补全 badge when company/salary missing", () => {
  const html = boardCard({ job_id: "j1", title: "后端", status: "applied" });
  assert.match(html, /badge-amber/);
  assert.match(html, />待补全</);
  assert.match(html, /title="缺少：公司、薪资"/);
});

test("boardCard shows 抓取失败 for junk JD even when fields complete", () => {
  const html = boardCard({
    job_id: "j1",
    title: "后端",
    company: "Acme",
    salary_min: 20000,
    status: "applied",
    jd_text: '{"pageConfig":{}}',
  });
  assert.match(html, />抓取失败，可重试</);
  assert.doesNotMatch(html, />待补全</);
});

test("renderBoardCard shows 待补全 badge when title/company/salary missing", () => {
  const html = renderBoardCard({ job_id: "j1", status: "draft" });
  assert.match(html, />待补全</);
  assert.match(html, /title="缺少：标题、公司、薪资"/);
  const complete = renderBoardCard({
    job_id: "j2",
    title: "T",
    company: "C",
    salary_max: 1,
    status: "draft",
  });
  assert.doesNotMatch(complete, />待补全</);
});
