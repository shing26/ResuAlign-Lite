// UX 走查回归护栏（2026-08-28，报告 ResuAlign-UX分角色深度走查-20260828）。
// 覆盖三类已实锤的回归模式：
//   1) CSS 级联被更早的暗色 shell 规则压过（P0-A 侧栏白底白字）；
//   2) 路由别名语义漂移（P1-A #/resumes 进档案）；
//   3) 硬门禁建议卡与头部计数口径（P1-B 残留：0 条 vs N 张 invalid 卡）。
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { diffList, parseHashValue } from "../../src/resualign/static/app/format.js";

const here = dirname(fileURLToPath(import.meta.url));
const STYLES = readFileSync(
  join(here, "../../src/resualign/static/styles.css"),
  "utf8",
);

/* ---------- 护栏 1：CSS 级联（P0-A / P1-D / P2-D 同根因） ---------- */

function lastColorDecl(css, selector) {
  // 通用规则块扫描：取与 selector 完全匹配的规则块中最后一段 color 声明
  // （级联以"最后出现"取胜）。先剥离注释，避免注释里的选择器字样干扰。
  let decl = null;
  for (const m of css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    const selList = m[1];
    if (!selList.split(",").some((s) => s.trim() === selector)) continue;
    const color = m[2].match(/(?:^|;)\s*color\s*:\s*([^;]+)/);
    if (color) decl = color[1].trim();
  }
  return decl;
}

test("P0-A: rail 导航项最终 color 必须走主题感知 token，而不是暗色 shell 白字", () => {
  const decl = lastColorDecl(STYLES, ".tabs--rail button");
  assert.ok(decl, ".tabs--rail button 缺少 color 声明");
  assert.match(
    decl,
    /--ra-text-secondary/,
    "最终生效的 color 必须是 --ra-text-secondary（浅色=slate-600 / 暗色自动适配），" +
      "否则白底白字回归（2026-08-28 走查 P0-A）",
  );
});

test("P1-D: 设置页 bento 卡标签最终 color 必须走主题感知 token", () => {
  const decl = lastColorDecl(STYLES, ".settings-bento__label");
  assert.ok(decl, ".settings-bento__label 缺少 color 声明");
  assert.match(
    decl,
    /--ra-text-secondary/,
    "bento 标签不能落在暗色块 rgba(255,255,255,.4) 上（2026-08-28 走查 P1-D）",
  );
});

test("护栏: 浅色 token 组合满足 WCAG AA（slate-600 on white ≥ 4.5:1）", () => {
  const lum = (hex) => {
    const [r, g, b] = [0, 2, 4].map((i) => {
      const v = parseInt(hex.slice(i, i + 2), 16) / 255;
      return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (fg, bg) => {
    const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
    return (a + 0.05) / (b + 0.05);
  };
  // --ra-text-secondary 浅色值 #475569（styles.css 浅色 token 块）
  assert.ok(
    ratio("475569", "ffffff") >= 4.5,
    "slate-600 对白底对比度必须 ≥ 4.5:1",
  );
});

/* ---------- 护栏 2：路由矩阵（P1-A） ---------- */

test("P1-A: 裸 #/resumes ≡ #/resume/list（列表哨兵），#/resume/<id> 才进档案", () => {
  assert.deepEqual(parseHashValue("#/resumes"), {
    name: "resume",
    jobId: null,
    resumeId: "list",
  });
  assert.equal(parseHashValue("#/resume/list").resumeId, "list");
  assert.equal(parseHashValue("#/resume/abc123").resumeId, "abc123");
  // 裸 #/resume 维持「最新简历档案」（phase-20 冒烟契约依赖 detail 视图）
  assert.equal(parseHashValue("#/resume").resumeId, null);
});

/* ---------- 护栏 3：硬门禁建议卡渲染契约（P1-B 残留） ---------- */

const invalidDiff = {
  diff_id: "inv-1",
  section: "技能清单",
  type: "modify",
  original: "AI 赋能研发效能",
  proposed: "AI 研发效能专家",
  reason: "",
  confidence: "medium",
  provenance: "",
  provenance_state: "missing", // 服务端 provenance 硬门禁的拦截标记（tailor.py）
};

function sessionWith(diffs, invalidDiffs) {
  return {
    job: { job_id: "j1" },
    alignment: { status: "succeeded", diffs, invalid_diffs: invalidDiffs },
  };
}

test("P1-B: succeeded + 仅 invalid diffs 时渲染待复核卡（而非空白或空态）", () => {
  const html = diffList(sessionWith([], [invalidDiff]), "j1");
  assert.match(html, /diff-card--invalid/);
  assert.doesNotMatch(html, /data-action="accept-bullet"/);
  assert.doesNotMatch(html, /data-resume-canvas-empty/);
});

test("P1-B: succeeded 且无任何 diffs 时渲染开始对齐空态", () => {
  const html = diffList(sessionWith([], []), "j1");
  assert.match(html, /data-resume-canvas-empty/);
});
