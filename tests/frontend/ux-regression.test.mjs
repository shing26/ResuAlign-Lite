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

import {
  diffList,
  parseHashValue,
  renderGap,
  resumeListPreview,
  shortenGapPhrase,
  workbenchGuideHtml,
} from "../../src/resualign/static/app/format.js";

const here = dirname(fileURLToPath(import.meta.url));
const STYLES_RAW = readFileSync(
  join(here, "../../src/resualign/static/styles.css"),
  "utf8",
);
/* 注释剥离后的样式表：级联/token 解析统一用它，避免注释里的选择器字样干扰 */
const STYLES = STYLES_RAW.replace(/\/\*[\s\S]*?\*\//g, "");

/* ---------- 护栏 1：CSS 级联（P0-A / P1-D / P2-D 同根因） ---------- */

/** CSS 特异性 (id, class/属性/伪类, 元素/伪元素)。 */
function specificity(sel) {
  const s = String(sel).trim();
  const ids = (s.match(/#[\w-]+/g) || []).length;
  const classes =
    (s.match(/\.[\w-]+/g) || []).length +
    (s.match(/\[[^\]]*\]/g) || []).length +
    (s.match(/:(?!:)[\w-]+/g) || []).length;
  const pseudoEls = (s.match(/::[\w-]+/g) || []).length;
  const elements =
    (s.replace(/::[\w-]+/g, " ").match(/(^|[\s>+~])[a-zA-Z][\w-]*/g) || [])
      .length + pseudoEls;
  return [ids, classes, elements];
}

/**
 * 按真实级联裁定 color：先比特异性，特异性相同则取源码靠后者。
 *
 * 2026-08-29：原先的 lastColorDecl 只做"精确选择器字符串匹配 + 取最后一条"，
 * 完全不建模特异性，所以它查 `.tabs--rail button` 时拿到的是文件末尾的
 * token 声明，而浏览器实际生效的是更具体的
 * `.tabs--rail button.nav-btn { color: rgba(255,255,255,.6) }`——
 * 护栏 green，线上白底白字。这里改为显式列出会互相竞争的选择器集合，
 * 让测试按浏览器同样的方式裁定胜者。
 */
function resolveColor(css, selectors) {
  const wanted = new Set(selectors);
  const decls = [];
  let order = 0;
  for (const m of css.matchAll(/([^{}]+)\{([^}]*)\}/g)) {
    for (const part of m[1].split(",")) {
      const sel = part.trim();
      if (!wanted.has(sel)) continue;
      const color = m[2].match(/(?:^|;)\s*color\s*:\s*([^;]+)/);
      if (color) {
        decls.push({ sel, color: color[1].trim(), spec: specificity(sel), order: order++ });
      }
    }
  }
  if (!decls.length) return null;
  decls.sort((a, b) => {
    for (let i = 0; i < 3; i += 1) {
      if (a.spec[i] !== b.spec[i]) return a.spec[i] - b.spec[i];
    }
    return a.order - b.order;
  });
  return decls[decls.length - 1];
}

/**
 * rail 导航默认态 color 的竞争者集合。
 * 新增/改动相关规则时，选择器必须同步加到这里，否则护栏会失明。
 */
const RAIL_NAV_SELECTORS = [
  ".tabs--rail button",
  ".tabs--rail button.nav-btn",
];

test("P0-A: rail 导航项最终 color 必须走主题感知 token，而不是暗色 shell 白字", () => {
  const winner = resolveColor(STYLES, RAIL_NAV_SELECTORS);
  assert.ok(winner, "rail 导航默认态缺少 color 声明");
  assert.match(
    winner.color,
    /--ra-text-secondary/,
    `默认态胜出规则必须声明 --ra-text-secondary。` +
      `实际胜出：${winner.sel} { color: ${winner.color} }` +
      `（特异性 ${winner.spec.join(",")}）。` +
      `若胜出者是更具体的暗色 shell 白字规则，说明修复选择器特异性不足` +
      `（2026-08-28 走查 P0-A / 2026-08-29 复验：修复需带 .nav-btn）`,
  );
});

test("P1-D: 设置页 bento 卡标签最终 color 必须走主题感知 token", () => {
  const decl = resolveColor(STYLES, [".settings-bento__label"]);
  assert.ok(decl, ".settings-bento__label 缺少 color 声明");
  assert.match(
    decl.color,
    /--ra-text-secondary/,
    "bento 标签不能落在暗色块 rgba(255,255,255,.4) 上（2026-08-28 走查 P1-D）",
  );
});

test("护栏: 浅色主题 --ra-text-secondary 实际值对白底满足 WCAG AA ≥ 4.5:1", () => {
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
  // 浅色 ra 壳层 token 块以 --ra-canvas（浅色画布色）为标记；暗色主题由
  // html.dark/[data-theme=dark] 高特异性块覆盖。解析该块里
  // --ra-text-secondary 的真实色值——token 改坏时护栏直接报警。
  const rootBlocks = [...STYLES.matchAll(/:root\s*{([^}]*)}/g)].map((m) => m[1]);
  const lightBlock = [...rootBlocks].reverse().find((b) => b.includes("--ra-canvas")) || "";
  const value = lightBlock.match(/--ra-text-secondary:\s*(#[0-9a-fA-F]{6})/);
  assert.ok(value, "浅色 :root 块必须定义十六进制 --ra-text-secondary");
  assert.ok(
    ratio(value[1].slice(1), "ffffff") >= 4.5,
    `--ra-text-secondary=${value[1]} 对白底对比度必须 ≥ 4.5:1`,
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

/* ---------- 遗留待办（P1-C / P2-A / P2-B / P2-C） ---------- */

test("P2-A: 列表卡预览跳过 Markdown 标题行、截断并附全文字数", () => {
  const longLine = "- 五年后端研发经验，主导过支付网关重构与性能优化，熟悉高并发场景，深入理解 JVM 调优与分布式事务一致性。".repeat(3);
  const content = `# 陈振成 Java 全栈\n\n${longLine}\n\n## 技能\nJava`;
  const preview = resumeListPreview(content);
  assert.ok(!preview.startsWith("#"), "预览不应以 Markdown 标题开头");
  assert.ok(preview.includes("（全文约"), "截断时应附全文字数提示");
  assert.ok(preview.length <= 140, "预览必须短于全文（降低扫描成本）");
  // 短简历不截断也不画蛇添足
  const short = resumeListPreview("# 只有标题\n\nhello");
  assert.equal(short, "hello");
  assert.equal(resumeListPreview(""), "（暂无内容 · 共 0 字）");
});

test("P2-B: 缺口短语超长时截断为省略号，短句原样透传", () => {
  const long = "AI Agent 基本概念（LLM API 调用、工具调用/Function Calling、MCP 协议等）或对 AI+运维方向有浓厚兴趣";
  const shortened = shortenGapPhrase(long);
  assert.ok(shortened.length <= 41, "截断后 ≤ 40 字 + 省略号");
  assert.ok(shortened.endsWith("…"));
  assert.equal(shortenGapPhrase("Redis 缓存"), "Redis 缓存");
  // renderGap 输出完整原文进 title、短语进标签体
  const html = renderGap({ missing_keywords: [long], strength_matches: [], misaligned_emphasis: [] });
  assert.match(html, /title="AI Agent 基本概念/);
  assert.ok(!html.includes("Function Calling、MCP 协议等）或对 AI+运维方向有浓厚兴趣</span>"));
});

test("P2-C: idle 任务（无草稿）不渲染投递闭环引导条", () => {
  const idleJob = { job_id: "j1", final_draft: null };
  assert.equal(workbenchGuideHtml(idleJob, false), "");
  // 有草稿才出现引导（已生成草稿 → 记录投递 → 安排跟进）
  const withDraft = { job_id: "j1", final_draft: "draft text" };
  assert.match(workbenchGuideHtml(withDraft, false), /workbench-guide/);
});
