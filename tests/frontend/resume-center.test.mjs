import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";

import {
  atsHealthCardHtml,
  atsHealthScoreLevel,
  optimizeModuleHtml,
  optimizeOverviewHtml,
  versionChangeSummary,
  versionTimelineHtml,
} from "../../src/resualign/static/app/format.js";

function bodyFrom(html) {
  const window = new Window();
  window.document.body.innerHTML = html;
  return window.document.body;
}

/* ------------------------------------------------------------------ */
/* Sprint 4 static CSS assertions (Kanban 沉降 + hover + stats 视觉)     */
/* ------------------------------------------------------------------ */

const stylesCss = readFileSync(
  join(
    dirname(fileURLToPath(import.meta.url)),
    "..",
    "..",
    "src/resualign/static/styles.css",
  ),
  "utf8",
);

test("styles.css: board-column uses the sinking surface (surface-tint + inset shadow)", () => {
  const block = stylesCss.match(/\.board-column\s*\{([^}]*)\}/s);
  assert.ok(block, ".board-column rule exists");
  assert.match(block[1], /var\(--surface-tint\)/);
  assert.match(block[1], /var\(--line\)/);
  assert.match(block[1], /inset 0 1px/);
});

test("styles.css: board-card hover lifts with translateY and shadow", () => {
  const hover = stylesCss.match(/\.board-card:hover\s*\{([^}]*)\}/s);
  assert.ok(hover, ".board-card:hover rule exists");
  assert.match(hover[1], /translateY\(-2px\)/);
  assert.match(hover[1], /var\(--shadow-2\)/);
});

test("styles.css: board-card hover is gated by prefers-reduced-motion", () => {
  const gate = stylesCss.match(
    /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?\.board-card:hover\s*\{[\s\S]*?transform: none[\s\S]*?\n\}/,
  );
  assert.ok(gate, "a reduced-motion block cancels the board-card hover lift");
});

test("styles.css: board-card drag state deepens the shadow", () => {
  const block = stylesCss.match(/\.board-card\.is-dragging\s*\{([^}]*)\}/s);
  assert.ok(block, ".board-card.is-dragging rule exists");
  assert.match(block[1], /var\(--shadow-3\)/);
});

test("styles.css: stats bar and funnel cards reuse dashboard KPI semantics", () => {
  assert.match(stylesCss, /\.board-stats\s*\{/);
  const base = stylesCss.match(/\.board-stats-card::before\s*\{([^}]*)\}/s);
  assert.ok(base, ".board-stats-card::before rule exists");
  assert.match(base[1], /var\(--info\)/);
  const warning = stylesCss.match(/\.board-stats-card--warning::before\s*\{([^}]*)\}/s);
  const success = stylesCss.match(/\.board-stats-card--success::before\s*\{([^}]*)\}/s);
  assert.ok(warning && /var\(--warning\)/.test(warning[1]), "warning funnel card uses --warning");
  assert.ok(success && /var\(--success\)/.test(success[1]), "success funnel card uses --success");
});

test("styles.css: resume detail grid is 65/35 two-column", () => {
  const grid = stylesCss.match(/\.resume-archive-grid\s*\{([^}]*)\}/s);
  assert.ok(grid, ".resume-archive-grid rule exists");
  assert.match(grid[1], /13fr/);
  assert.match(grid[1], /7fr/);
});

/* ------------------------------------------------------------------ */
/* atsHealthScoreLevel                                                 */
/* ------------------------------------------------------------------ */

test("atsHealthScoreLevel buckets by 85/70 thresholds", () => {
  assert.equal(atsHealthScoreLevel(100), "优秀");
  assert.equal(atsHealthScoreLevel(85), "优秀");
  assert.equal(atsHealthScoreLevel(84), "良好");
  assert.equal(atsHealthScoreLevel(70), "良好");
  assert.equal(atsHealthScoreLevel(69), "待提升");
  assert.equal(atsHealthScoreLevel(0), "待提升");
});

/* ------------------------------------------------------------------ */
/* atsHealthCardHtml                                                  */
/* ------------------------------------------------------------------ */

test("atsHealthCardHtml grades 88 as 优秀 with skills highlighted", () => {
  const body = bodyFrom(
    atsHealthCardHtml({ score: 88, skills: ["Python", "K8s"], issues: [], suggestions: [] }),
  );
  const card = body.querySelector("[data-ats-health]");
  assert.ok(card);
  assert.equal(card.querySelector("[data-ats-score]").textContent, "88");
  assert.equal(card.querySelector("[data-ats-level]").textContent, "优秀");
  assert.match(card.className, /ats-health--high/);
  /* 无 issues → 优势高光展示 skills；无改进建议区 */
  const highlights = card.querySelector("[data-ats-highlights]");
  assert.ok(highlights);
  assert.match(highlights.textContent, /Python/);
  assert.match(highlights.textContent, /K8s/);
  assert.equal(card.querySelector("[data-ats-improvements]"), null);
});

test("atsHealthCardHtml grades 72 as 良好 and 50 as 待提升", () => {
  const mid = bodyFrom(atsHealthCardHtml({ score: 72 }));
  assert.equal(mid.querySelector("[data-ats-level]").textContent, "良好");
  assert.match(mid.querySelector("[data-ats-health]").className, /ats-health--mid/);
  const low = bodyFrom(atsHealthCardHtml({ score: 50 }));
  assert.equal(low.querySelector("[data-ats-level]").textContent, "待提升");
  assert.match(low.querySelector("[data-ats-health]").className, /ats-health--low/);
});

test("atsHealthCardHtml clamps score and lists issues as improvements", () => {
  const body = bodyFrom(
    atsHealthCardHtml({ score: 150, issues: ["缺少量化成果", "描述太短"], suggestions: [] }),
  );
  const card = body.querySelector("[data-ats-health]");
  assert.equal(card.querySelector("[data-ats-score]").textContent, "100");
  const items = [...card.querySelectorAll("[data-ats-improvements] li")];
  assert.equal(items.length, 2);
  assert.match(items[0].textContent, /缺少量化成果/);
  /* issues 存在时不展示 skills 高光 */
  assert.equal(card.querySelector("[data-ats-highlights]"), null);
});

test("atsHealthCardHtml takes first three improvements and falls back to suggestions", () => {
  const body = bodyFrom(
    atsHealthCardHtml({ score: 60, issues: ["a", "b", "c", "d"], suggestions: ["s1"] }),
  );
  assert.equal(body.querySelectorAll("[data-ats-improvements] li").length, 3);
  const fallback = bodyFrom(
    atsHealthCardHtml({ score: 80, issues: [], suggestions: ["s1", "s2"] }),
  );
  const items = [...fallback.querySelectorAll("[data-ats-improvements] li")];
  assert.equal(items.length, 2);
  assert.match(items[0].textContent, /s1/);
});

test("atsHealthCardHtml renders empty state for missing diagnosis", () => {
  for (const empty of [null, undefined, {}, { score: "abc" }, { skills: "x" }]) {
    const body = bodyFrom(atsHealthCardHtml(empty));
    const card = body.querySelector("[data-ats-health]");
    assert.ok(card, "empty diagnosis still renders an ATS card");
    assert.equal(card.querySelector("[data-ats-score]").textContent, "—");
    assert.match(card.querySelector("[data-ats-level]").textContent, /尚未诊断/);
    assert.match(card.className, /ats-health--empty/);
  }
});

test("atsHealthCardHtml escapes issues and skills", () => {
  const body = bodyFrom(
    atsHealthCardHtml({
      score: 66,
      issues: ['<img src=x onerror="alert(1)">'],
      skills: ["<script>alert(1)</script>"],
    }),
  );
  assert.equal(body.querySelector("img"), null);
  assert.equal(body.querySelector("script"), null);
  assert.match(body.querySelector("[data-ats-improvements]").innerHTML, /&lt;img/);
  const skillsOnly = bodyFrom(atsHealthCardHtml({ score: 90, skills: ["<b>Python</b>"] }));
  assert.match(skillsOnly.querySelector("[data-ats-highlights]").innerHTML, /&lt;b&gt;/);
  assert.equal(skillsOnly.querySelector("b"), null);
});

/* ------------------------------------------------------------------ */
/* versionChangeSummary                                               */
/* ------------------------------------------------------------------ */

test("versionChangeSummary shows initial version, diff rows, or 内容更新", () => {
  /* 契约（dom/resume-versions.test.mjs）：首版本以 add 行占位，带 "+ " 前缀 */
  assert.equal(versionChangeSummary(null, { content: "x" }), "+ 初始版本");
  assert.equal(versionChangeSummary({ content: "相同" }, { content: "相同" }), "内容更新");
  const summary = versionChangeSummary(
    { content: "旧行一\n旧行二\n旧行三" },
    { content: "新行一\n新行二\n旧行三" },
  );
  assert.match(summary, /- 旧行一/);
  assert.match(summary, /- 旧行二/);
  assert.doesNotMatch(summary, /旧行三/);
});

test("versionChangeSummary truncates long summaries at 60 chars", () => {
  const long = "x".repeat(100);
  const summary = versionChangeSummary({ content: long }, { content: "y".repeat(100) });
  assert.ok(summary.length <= 61, `summary truncated (got ${summary.length})`);
  assert.match(summary, /…$/);
});

/* ------------------------------------------------------------------ */
/* versionTimelineHtml                                                */
/* ------------------------------------------------------------------ */

const versions = [
  { version: 1, content: "# 初始\n基本信息", created_at: 1700000000 },
  { version: 2, content: "# 更新\n新增项目经历\n更多内容", created_at: 1700000100 },
  { version: 3, content: "# 更新\n新增项目经历\n更多内容\n量化结果", created_at: 1700000200 },
];

test("versionTimelineHtml renders every version with number and time", () => {
  const body = bodyFrom(versionTimelineHtml(versions, 3));
  const items = [...body.querySelectorAll("[data-version-item]")];
  assert.equal(items.length, 3);
  assert.match(items[0].querySelector(".version-timeline__no").textContent, /v1/);
  assert.match(items[1].querySelector(".version-timeline__no").textContent, /v2/);
  assert.match(items[2].querySelector(".version-timeline__no").textContent, /v3/);
  /* 每条都带 formatDate 输出的创建时间（本地时区 YYYY-MM-DD HH:mm） */
  const time = items[0].querySelector(".small.muted").textContent.trim();
  assert.match(time, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
});

test("versionTimelineHtml marks only the current version", () => {
  const body = bodyFrom(versionTimelineHtml(versions, 2));
  const current = body.querySelector("[data-version-current]");
  assert.ok(current);
  assert.equal(current.closest("[data-version-item]").dataset.version, "2");
  assert.equal(body.querySelectorAll("[data-version-current]").length, 1);
});

test("versionTimelineHtml shows change summaries and 初始版本 for v1", () => {
  const body = bodyFrom(versionTimelineHtml(versions, 3));
  const summaries = [...body.querySelectorAll("[data-version-summary]")];
  assert.match(summaries[0].textContent, /初始版本/);
  /* v1 → v2 差异前 2 行（lineDiff 删除行优先） */
  assert.match(summaries[1].textContent, /- # 初始/);
  /* v2 → v3 新增行 */
  assert.match(summaries[2].textContent, /\+ 量化结果/);
});

test("versionTimelineHtml provides preview and rollback only for non-current versions", () => {
  const body = bodyFrom(versionTimelineHtml(versions, 2, "resume-1"));
  const items = [...body.querySelectorAll("[data-version-item]")];
  assert.equal(items[1].querySelector('[data-action="preview-version"]'), null);
  assert.equal(items[1].querySelector('[data-action="rollback-resume"]'), null);
  const v1Preview = items[0].querySelector('[data-action="preview-version"]');
  assert.ok(v1Preview);
  assert.equal(v1Preview.dataset.version, "1");
  const v1Rollback = items[0].querySelector('[data-action="rollback-resume"]');
  assert.equal(v1Rollback.dataset.id, "resume-1");
  assert.equal(v1Rollback.dataset.version, "1");
  const v3Preview = items[2].querySelector('[data-action="preview-version"]');
  assert.equal(v3Preview.dataset.version, "3");
});

test("versionTimelineHtml escapes version numbers and summaries", () => {
  const body = bodyFrom(
    versionTimelineHtml(
      [{ version: "<img src=x>", content: "<script>alert(1)</script>", created_at: 1700000000 }],
      1,
      '"><script>bad</script>',
    ),
  );
  assert.equal(body.querySelector("script"), null);
  assert.equal(body.querySelector("img"), null);
});

test("versionTimelineHtml renders empty state for no versions", () => {
  const body = bodyFrom(versionTimelineHtml([], 1));
  assert.match(body.querySelector("[data-version-timeline]").textContent, /暂无版本/);
});

/* ------------------------------------------------------------------ */
/* Sprint 5: AI 优化面板 —— optimizeOverviewHtml / optimizeModuleHtml     */
/* ------------------------------------------------------------------ */

test("optimizeOverviewHtml renders score, verdict, skills and JD hits", () => {
  const body = bodyFrom(
    optimizeOverviewHtml({
      score: 82,
      skills: ["Python", "K8s"],
      highlights: ["性能提升 30%", "日活 10w"],
      issues: ["缺少量化成果"],
      project_count: 3,
      jd: {
        provided: true,
        matched_keywords: ["Python"],
        unmatched_keywords: ["Go", "Redis"],
      },
    }),
  );
  const panel = body.querySelector("[data-optimize-overview]");
  assert.ok(panel);
  assert.equal(panel.querySelector("[data-optimize-score]"), null);
  assert.equal(panel.querySelector(".optimize-overview__score").textContent, "82");
  assert.equal(panel.querySelector("[data-optimize-verdict]").textContent, "优秀");
  const skills = panel.querySelector("[data-optimize-skills]");
  assert.ok(skills);
  assert.match(skills.textContent, /Python/);
  assert.match(skills.textContent, /K8s/);
  assert.match(panel.querySelector("[data-optimize-highlights]").textContent, /性能提升 30%/);
  assert.match(panel.querySelector("[data-optimize-issues]").textContent, /缺少量化成果/);
  const jd = panel.querySelector("[data-optimize-jd]");
  assert.ok(jd);
  assert.match(jd.textContent, /1 命中 \/ 2 未命中/);
  assert.match(jd.textContent, /Go/);
  assert.equal(jd.querySelectorAll(".chip--matched").length, 1);
  assert.match(jd.querySelector(".chip--matched").textContent, /Python/);
});

test("optimizeOverviewHtml clamps score and picks verdict by 80/60 thresholds", () => {
  const mid = bodyFrom(optimizeOverviewHtml({ score: 60 }));
  assert.equal(mid.querySelector(".optimize-overview__score").textContent, "60");
  assert.equal(mid.querySelector("[data-optimize-verdict]").textContent, "建议优化");
  const low = bodyFrom(optimizeOverviewHtml({ score: 30 }));
  assert.equal(low.querySelector("[data-optimize-verdict]").textContent, "需重点优化");
  const clamped = bodyFrom(optimizeOverviewHtml({ score: 150 }));
  assert.equal(clamped.querySelector(".optimize-overview__score").textContent, "100");
  const missing = bodyFrom(optimizeOverviewHtml(null));
  assert.equal(missing.querySelector(".optimize-overview__score").textContent, "—");
  assert.equal(missing.querySelector("[data-optimize-verdict]").textContent, "建议优化");
});

test("optimizeOverviewHtml escapes skills, highlights and JD keywords", () => {
  const body = bodyFrom(
    optimizeOverviewHtml({
      score: 66,
      skills: ["<script>alert(1)</script>"],
      highlights: ["<img src=x onerror=alert(1)>"],
      jd: {
        provided: true,
        matched_keywords: ["<b>Python</b>"],
        unmatched_keywords: ["</script>"],
      },
    }),
  );
  assert.equal(body.querySelector("script"), null);
  assert.equal(body.querySelector("img"), null);
  assert.match(body.querySelector("[data-optimize-skills]").innerHTML, /&lt;script&gt;/);
  assert.match(body.querySelector("[data-optimize-highlights]").innerHTML, /&lt;img/);
  assert.match(body.querySelector("[data-optimize-jd]").innerHTML, /&lt;b&gt;Python&lt;\/b&gt;/);
});

test("optimizeModuleHtml renders diff rows, rationale and accept/ignore actions", () => {
  const item = {
    module: "projects",
    index: 1,
    title: "订单系统",
    original: "负责订单模块开发\n修复线上问题",
    optimized: "负责订单模块开发\n性能提升 30%",
    rationale: "补充量化成果",
    status: "ok",
  };
  const body = bodyFrom(optimizeModuleHtml(item, 3));
  const card = body.querySelector("[data-optimize-module]");
  assert.ok(card);
  assert.equal(card.dataset.optimizeKey, "3");
  assert.match(card.querySelector(".optimize-module__title").textContent, /订单系统/);
  assert.match(card.querySelector(".badge-gray").textContent, /projects/);
  const diffs = [...card.querySelectorAll(".optimize-diff")];
  assert.equal(diffs.length, 2);
  assert.match(diffs[0].className, /optimize-diff--remove/);
  assert.match(diffs[0].textContent, /修复线上问题/);
  assert.match(diffs[1].className, /optimize-diff--add/);
  assert.match(diffs[1].textContent, /性能提升 30%/);
  assert.match(card.querySelector(".optimize-module__rationale").textContent, /补充量化成果/);
  const accept = card.querySelector('[data-action="optimize-accept-item"]');
  const ignore = card.querySelector('[data-action="optimize-reject-item"]');
  assert.ok(accept);
  assert.ok(ignore);
  assert.equal(accept.dataset.optimizeKey, "3");
  assert.match(accept.textContent, /采纳/);
  assert.match(ignore.textContent, /忽略/);
  assert.equal(card.querySelector("[data-optimize-accepted-mark]"), null);
});

test("optimizeModuleHtml marks accepted card with 已采纳", () => {
  const item = {
    module: "projects",
    index: 0,
    title: "支付中台",
    original: "a",
    optimized: "b",
    rationale: "",
    status: "ok",
  };
  const body = bodyFrom(optimizeModuleHtml(item, 0, true));
  const card = body.querySelector("[data-optimize-module]");
  assert.match(card.className, /is-accepted/);
  assert.ok(card.querySelector("[data-optimize-accepted-mark]"));
  assert.match(card.querySelector('[data-action="optimize-accept-item"]').textContent, /已采纳/);
});

test("optimizeModuleHtml renders failed cards without accept buttons", () => {
  const item = {
    module: "projects",
    index: 2,
    title: "风控引擎",
    status: "failed",
    error: '模型账户欠费或余额不足 <script>alert(1)</script>',
  };
  const body = bodyFrom(optimizeModuleHtml(item, 2));
  const card = body.querySelector("[data-optimize-module]");
  assert.ok(card);
  assert.match(card.className, /optimize-module--failed/);
  assert.match(card.querySelector(".badge-red").textContent, /润色失败/);
  assert.equal(card.querySelector('[data-action="optimize-accept-item"]'), null);
  assert.equal(card.querySelector('[data-action="optimize-reject-item"]'), null);
  assert.equal(body.querySelector("script"), null);
  assert.match(card.querySelector(".form-error").textContent, /模型账户欠费或余额不足/);
});

/* ------------------------------------------------------------------ */
/* Sprint 5: styles.css .optimize-* rules                              */
/* ------------------------------------------------------------------ */

test("styles.css: optimize diff rows use success/danger accents", () => {
  const add = stylesCss.match(/\.optimize-diff--add\s*\{([^}]*)\}/s);
  assert.ok(add, ".optimize-diff--add rule exists");
  assert.match(add[1], /var\(--ra-success/);
  const remove = stylesCss.match(/\.optimize-diff--remove\s*\{([^}]*)\}/s);
  assert.ok(remove, ".optimize-diff--remove rule exists");
  assert.match(remove[1], /var\(--ra-danger/);
  assert.match(remove[1], /line-through/);
});

test("styles.css: accepted module and JD chip reuse success accent", () => {
  const accepted = stylesCss.match(/\.optimize-module\.is-accepted\s*\{([^}]*)\}/s);
  assert.ok(accepted, ".optimize-module.is-accepted rule exists");
  assert.match(accepted[1], /var\(--ra-success/);
  const chip = stylesCss.match(/\.chip--matched\s*\{([^}]*)\}/s);
  assert.ok(chip, ".chip--matched rule exists");
  assert.match(chip[1], /var\(--ra-success/);
  const failed = stylesCss.match(/\.optimize-module--failed\s*\{([^}]*)\}/s);
  assert.ok(failed, ".optimize-module--failed rule exists");
  assert.match(failed[1], /var\(--ra-danger/);
});
