// Phase 4 (2026-08-30): CSS 结构护栏。
// 背景：styles.css 累积到 12020 行、271 个简单选择器存在重复定义，
// 「简历中心堆叠」等布局问题多源于多时代定义叠加（.resume-archive-grid
// 的 align-items:start 未被 v3 覆盖）。本护栏锁定三条结构不变式：
//   1) 花括号平衡（防语法破坏）；
//   2) 关键布局选择器必须存在（防误删 v3 定义）；
//   3) 关键布局选择器的最后一条定义必须位于 v3 区段（文件后 1/3），
//      防止被早先的暗色/旧版规则覆盖（P0-A 同根因）。
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const RAW = readFileSync(
  join(here, "../../src/resualign/static/styles.css"),
  "utf8",
);
const LINES = RAW.split("\n");
const STYLES = RAW.replace(/\/\*[\s\S]*?\*\//g, "");

/* 关键布局选择器：shell 骨架 + 简历中心网格（Phase 1 修复的堆叠根因面）。 */
const CRITICAL_SELECTORS = [
  ".app-shell",
  ".app-rail",
  ".app-main",
  "#app-router-view",
  ".resume-view",
  ".resume-archive-grid",
  ".resume-grid",
  ".resume-sheet",
  ".resume-doc",
  ".resume-rail",
];

function braceBalance(text) {
  let depth = 0;
  for (const ch of text) {
    if (ch === "{") depth += 1;
    else if (ch === "}") depth -= 1;
    if (depth < 0) return false;
  }
  return depth === 0;
}

/* 收集某选择器的定义行号（选择器片段出现在规则头行，粗略但够护栏用）。 */
function definitionLines(selector) {
  const out = [];
  for (let i = 0; i < LINES.length; i += 1) {
    const line = LINES[i].trim();
    if (line.endsWith("{") && line.slice(0, -1).split(",").map((s) => s.trim()).includes(selector)) {
      out.push(i + 1);
    }
  }
  return out;
}

test("css braces are balanced", () => {
  assert.equal(braceBalance(STYLES), true, "花括号不平衡，样式表被破坏");
});

test("css has no empty rule bodies", () => {
  const empty = STYLES.match(/\{\s*\}/g) || [];
  assert.equal(empty.length, 0, `发现空规则体: ${empty.length} 处`);
});

for (const sel of CRITICAL_SELECTORS) {
  test(`critical selector ${sel} exists and v3 definition survives`, () => {
    const lines = definitionLines(sel);
    assert.ok(lines.length > 0, `${sel} 未定义`);
    const v3Start = Math.floor(LINES.length * 0.66);
    /* 定义可能写成逗号多行选择器列表（如 .resume-archive-grid, 换行 .resume-grid）,
       单行精确匹配会漏；用 v3 区段的字符串出现兜底。 */
    const v3Text = LINES.slice(v3Start).join("\n");
    const regex = new RegExp(sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    assert.ok(
      regex.test(v3Text),
      `${sel} 在 v3 区段(第 ${v3Start} 行起)无定义；`
        + "旧版规则可能覆盖当前渲染（堆叠/配色类回归）。",
    );
  });
}

/* 简历中心网格行高约束（Phase 1 修复）必须存在，防止回退到 align-items:start。 */
test("resume detail grid keeps viewport-constrained rows", () => {
  assert.match(
    STYLES,
    /\.resume-archive-grid[\s\S]{0,600}grid-template-rows:\s*minmax\(0,\s*1fr\)/,
    "缺失 grid-template-rows: minmax(0, 1fr)（Phase 1 高度约束被移除）",
  );
});

/* Phase C (2026-08-30): 标题去重不变式 —— 顶栏 refreshHeaderMeta 已按
 * PAGE_META 渲染页标题，resume 列表页与设置页的视图内 header 不得再渲染
 * 重复的 h2（实测 #/resumes 与 #/settings 曾出现双重「简历中心/系统设置」）。
 * 源码级断言：列表页 page-header 只保留副标题；settings-head 无 h2。 */
const RESUME_CENTER = readFileSync(
  join(here, "../../src/resualign/static/app/resume-center.js"),
  "utf8",
);
const MAIN_JS = readFileSync(
  join(here, "../../src/resualign/static/app/main.js"),
  "utf8",
);

test("resume list page-header has no duplicated h2 title", () => {
  const header = RESUME_CENTER.match(
    /page-header page-header--resume[\s\S]{0,220}?<div class="sub">/,
  );
  assert.ok(header, "简历列表页 page-header 结构缺失（sub 副标题被移除）");
  assert.doesNotMatch(
    header[0],
    /<h2>/,
    "简历列表页 page-header 不得再渲染 h2（顶栏已有「简历中心」）",
  );
});

test("settings head has no duplicated h2 title", () => {
  const head = MAIN_JS.match(/class="settings-head"[\s\S]{0,260}/);
  assert.ok(head, "settings-head 结构缺失");
  assert.doesNotMatch(
    head[0],
    /<h2>/,
    "设置页 settings-head 不得再渲染 h2（顶栏已有「系统设置」）",
  );
});
