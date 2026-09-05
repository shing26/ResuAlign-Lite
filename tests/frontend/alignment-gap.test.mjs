/* v2.0 增量对齐：折叠筛选 Toolbar 与简历双态编辑的 DOM 契约测试。
 * 与 imports-check.mjs 同模式 —— 直接读源码断言渲染模板保留的
 * data-* 契约，确保未来重构不会静默丢掉这两个已恢复的功能。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appDir = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "src/resualign/static/app",
);

function read(name) {
  return readFileSync(join(appDir, name), "utf8");
}

/* ------------------------------------------------------------------ */
/* kanban.js 折叠筛选 Toolbar                                          */
/* ------------------------------------------------------------------ */

test("kanban.js renders the collapsible filter toolbar (job-filter form)", () => {
  const src = read("kanban.js");
  assert.match(src, /data-board-filter/, "collapsible filter container");
  assert.match(src, /data-form="job-filter"/, "reuses the existing filter handler");
  /* 四维筛选字段必须齐备（关键词/职能/级别/状态） */
  assert.match(src, /name="search"/);
  assert.match(src, /name="job_function"/);
  assert.match(src, /name="seniority"/);
  assert.match(src, /name="status"/);
  /* 清除按钮复用既有 clear-filters action */
  assert.match(src, /data-action="clear-filters"/);
});

test("styles.css styles the collapsible filter toolbar", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(css, /\.board-filter\s*\{/);
  assert.match(css, /\.board-filter__summary\s*\{/);
  assert.match(css, /\.board-filter__form\s*\{/);
  assert.match(css, /\.board-filter\[open\]/, "expanded state hook");
});

/* ------------------------------------------------------------------ */
/* resume-center.js 双态编辑                                           */
/* ------------------------------------------------------------------ */

test("resume-center.js keeps the inline source editor (dual-mode editing)", () => {
  const src = read("resume-center.js");
  assert.match(src, /data-resume-inline-edit/, "hidden inline form");
  assert.match(
    src,
    /data-form="resume-edit"/,
    "inline save reuses the existing resume-edit submit handler",
  );
  assert.match(src, /data-action="toggle-resume-inline-edit"/, "toggle into source mode");
  assert.match(src, /data-action="cancel-resume-inline-edit"/, "cancel restores the view");
  assert.match(src, /name="content"/, "markdown textarea field");
});

test("main.js wires the dual-mode edit actions", () => {
  const src = read("main.js");
  assert.match(src, /"toggle-resume-inline-edit"/);
  assert.match(src, /"cancel-resume-inline-edit"/);
});

test("styles.css styles the inline source editor", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(css, /\.resume-inline-edit\s*\{/);
  assert.match(css, /body\.resume-inline-editing/, "view hidden while editing");
  /* P1-1 回归：.resume-inline-edit {display:flex} 靠后声明会压过早先的
     .hidden {display:none}，必须存在 body:not(.resume-inline-editing) 守卫
     保证简历档案页初始不渲染内联源码编辑框。 */
  assert.match(
    css,
    /body:not\(\.resume-inline-editing\)\s*\.resume-inline-edit\.hidden/,
    "initial hidden beats the flex layout rule",
  );
});

/* ------------------------------------------------------------------ */
/* v2.1 对齐：240px 侧栏 + 64px 顶栏 + 岗位库单一 Top Bar + 简历默认详情 */
/* ------------------------------------------------------------------ */

test("index.html: rail brand, jobs count badge and topbar title slots", () => {
  const html = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/index.html"),
    "utf8",
  );
  assert.match(html, /class="rail-brand\b/, "rail brand block");
  assert.match(html, /Career Studio v3/, "rail brand tagline");
  assert.match(html, /data-jobs-rail-count/, "jobs nav count badge");
  assert.match(html, /id="page-title"/, "dynamic topbar title");
  assert.match(html, /id="page-title"[^>]*>驾驶舱</, "dashboard title matches template");
  assert.match(html, /id="page-subtitle"/, "dynamic topbar subtitle");
  assert.doesNotMatch(html, /quick-jd-btn/, "A1: quick import JD button removed");
  assert.doesNotMatch(html, /快速导入 JD/, "A1: quick import JD label removed");
  assert.match(html, /data-rail-quota/, "rail foot quota card slot (A1/rail quota)");
  assert.match(html, /class="nav-index\b/, "numbered rail indicators");
  assert.match(html, />驾驶舱</, "dashboard rail label");
  assert.match(html, />工作台</, "workspace rail label");
  assert.match(html, />岗位库</, "jobs rail label");
  assert.match(html, />简历中心</, "resume rail label");
  assert.match(html, />系统设置</, "settings rail label");
});

test("styles.css: 240px rail + 64px topbar override layer", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(css, /\.app-rail\s*\{[^}]*240px/, "240px rail column");
  assert.match(css, /\.rail-brand\s*\{/, "rail brand styles");
  assert.match(css, /\.rail-count\s*\{/, "rail count badge styles");
  assert.match(css, /\.topbar\s*\{[^}]*height:\s*64px/, "64px topbar");
  assert.match(css, /\.header-title\s*\{/, "topbar title styles");
  assert.match(css, /\.quick-jd-btn\s*\{/, "quick JD button styles");
  assert.match(css, /\.rail-icon\s*\{/, "rail emoji icon styles");
  assert.match(css, /\.jobs-topbar__conversion\s*\{/, "conversion pill row styles");
  assert.match(css, /\.jobs-tools\s*\{/, "secondary jobs tools row styles");
});

test("styles.css: mobile rail hides the brand so nav buttons stay tappable", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(
    css,
    /@media \(max-width: 900px\)[\s\S]*?\.app-rail \.rail-brand\s*\{\s*display:\s*none;/,
    "final mobile override hides the full-width brand block",
  );
});

test("kanban.js: single jobs top bar keeps conversion and export contracts", () => {
  const src = read("kanban.js");
  assert.match(src, /data-jobs-topbar/, "unified jobs top bar");
  assert.doesNotMatch(src, /data-fetch-url-bar/, "fetch bar removed (crawler de-bloat)");
  assert.doesNotMatch(src, /data-blocker-badge/, "blocker badge mount removed (blocker UI de-bloat)");
  assert.match(src, /data-jobs-conversion/, "template conversion row");
  assert.match(src, /data-jobs-apply-rate/, "apply conversion pill");
  assert.match(src, /data-jobs-interview-rate/, "interview conversion pill");
  assert.match(src, /data-action="show-add-job"/, "add job action");
  assert.match(src, /data-action="show-import"/, "batch import action");
  assert.match(src, /data-action="export-jobs-csv"/, "CSV export action");
  assert.match(src, /data-action="export-jobs-backup"/, "library backup action");
  assert.match(src, /data-jobs-tools/, "tools row inside collapsible toolbar");
  assert.match(src, /data-jobs-forms-mount/, "job forms mount");
  assert.match(src, /data-jobs-batch-mount/, "batch panel mount");
  assert.doesNotMatch(src, /page-header--jobs/, "template top bar replaces jobs page header");
});

test("main.js: route meta, rail count and resume list route", () => {
  const src = read("main.js");
  assert.match(src, /PAGE_META\s*=\s*\{/, "page meta map");
  assert.match(src, /dashboard: \["驾驶舱"/, "dashboard route meta matches template");
  assert.match(src, /refreshHeaderMeta\(\)/, "header meta refreshed per route");
  assert.match(src, /refreshJobsRailCount\(/, "jobs rail count refresh");
  assert.match(src, /#\/resume\/list/, "explicit resume list route");
  assert.match(src, /settingsBentoHtml\(activeNode, latency\)/, "settings runtime status bento");
  assert.match(src, /data-llm-nodes-panel/, "settings LLM node panel");
  assert.match(src, /\.jobs-topbar"\) \|\| app\.querySelector\("\.page-header"\)/, "jobs strip hooks target the top bar");
  assert.doesNotMatch(src, /page-header--jobs \.row/, "old fetch-bar hook removed");
});

test("split-canvas.js renders the template workbench three-pane structure", () => {
  const src = read("split-canvas.js");
  assert.match(src, /目标岗位/, "target job header");
  assert.match(src, /岗位职责萃取/, "duty extraction block");
  assert.match(src, /技能缺口/, "gap block");
  assert.match(src, /简历精修/, "alignment canvas title");
  assert.match(src, /workbenchPrimaryButtonHtml/, "primary button helper mounted");
  const formatSrc = read("format.js");
  assert.match(formatSrc, /开始对齐/, "rerun alignment button");
  assert.match(formatSrc, /data-action="run-alignment"/, "rerun alignment action");
  assert.match(src, /data-inspector-pane/, "inspector pane contract");
  assert.match(src, /data-diff-pane/, "diff pane contract");
  assert.match(src, /data-live-sheet-pane/, "live sheet pane contract");
  assert.match(src, /data-job-switcher/, "job switcher contract");
});

test("split-canvas.js drops legacy application-record panel and keeps wb-run contract", () => {
  const src = read("split-canvas.js");
  assert.doesNotMatch(src, /data-applications-panel/, "applications panel removed");
  assert.doesNotMatch(src, /data-form="application-create"/, "application create form removed");
  assert.doesNotMatch(src, /renderApplicationsPanel/, "applications renderer removed");
  assert.doesNotMatch(src, /\/api\/applications/, "applications API fetch removed from canvas");
  assert.match(src, /data-form="wb-run"/, "legacy wb-run form contract");
  assert.doesNotMatch(src, /data-action="update-application-status"/, "application status action removed");
  assert.doesNotMatch(src, /data-action="run-application"/, "application run action removed");
  assert.doesNotMatch(src, /data-action="delete-application"/, "application delete action removed");
  assert.match(src, /data-action="set-wb-tab-v3"/, "aux pane tabs use delegated actions");
  assert.match(src, /state\.wbOriginalContent = null/, "new run clears stale diff original");
  assert.match(src, /state\.wbAcceptedIndices = null/, "new run clears stale accepted indices");
});

test("main.js drops legacy application create/edit/delete actions", () => {
  const src = read("main.js");
  assert.doesNotMatch(src, /"run-application"/, "application run action removed");
  assert.doesNotMatch(src, /"update-application-status"/, "application status action removed");
  assert.doesNotMatch(src, /"delete-application"/, "application delete action removed");
  assert.doesNotMatch(src, /case "application-create"/, "application create form removed");
  assert.doesNotMatch(src, /stopApplicationPolling/, "application polling removed");
});

test("skill-gap frequency labels live in skillGapHtml honestly", () => {
  /* 2026-09-01 重构：内联渲染收敛到 format.js skillGapHtml（颜色倒挂修复），
   * 契约目标随实现迁移；诚实文案语义不变。 */
  const src = read("format.js");
  assert.match(src, /需求最多/, "peak-frequency skill label");
  assert.doesNotMatch(src, /已覆盖/, "no misleading covered label");
  const dash = read("dashboard-view.js");
  assert.match(dash, /skillGapHtml\(/, "dashboard consumes the shared renderer");
  assert.doesNotMatch(dash, /skill-fill.*warn/, "no legacy inverted tone logic");
});

test("main.js wires the rerun alignment action", () => {
  const src = read("main.js");
  assert.match(src, /"run-alignment":/, "run-alignment action registered");
  assert.match(src, /data-form='split-align'/, "submits the split align form");
});

test("styles.css styles the template workbench blocks", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "src/resualign/static/styles.css"),
    "utf8",
  );
  assert.match(css, /\.workbench-job-head\s*\{/, "workbench job head styles");
  assert.match(css, /\.workbench-job-title\s*\{/, "workbench job title styles");
  assert.match(css, /\.workbench-duty-text\s*\{/, "duty extraction styles");
  assert.match(css, /\.workbench-gap\s*\{/, "gap block styles");
  assert.match(css, /\.workbench-tune\s*\{/, "alignment tune collapsible styles");
});

test("resume-center.js: default route opens the latest resume detail", () => {
  const src = read("resume-center.js");
  assert.match(src, /showList/, "list route flag accepted");
  assert.match(src, /renderResumeDetailView\(app, first\.resume_id\)/, "defaults to latest resume detail");
  assert.match(src, /renderResumeListView/, "list view still available");
});
