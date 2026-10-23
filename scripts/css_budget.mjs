#!/usr/bin/env node
/* CSS 结构债棘轮门禁（结构债项目 Phase 0）
 *
 * 读取基线 JSON 与当前度量，逐项比较：**只允许下降或持平**，任何一项变差都
 * 以非零退出码失败。这样后续每个阶段（删 token、并选择器、收内联样式）都能
 * 用同一把尺子锁住成果，不会「这轮删了 20 个 token，下轮又加回 25 个」。
 *
 * 用法：
 *   node scripts/css_budget.mjs
 *   node scripts/css_budget.mjs --baseline docs/reports/xxx.json
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";

const args = process.argv.slice(2);
const baselineIndex = args.indexOf("--baseline");
const baselinePath =
  baselineIndex >= 0 && args[baselineIndex + 1]
    ? args[baselineIndex + 1]
    : "docs/reports/css-debt-phase2-2026-10-24.json";

const baseline = JSON.parse(readFileSync(baselinePath, "utf8"));
const current = JSON.parse(
  execFileSync("node", ["scripts/css_audit.mjs"], {
    encoding: "utf8",
    cwd: process.cwd(),
  }),
);

/* [标签, 取值函数, 说明]：全部是「越小越好」的指标。 */
const metrics = [
  ["规则块数", (m) => m.css.ruleBlocks],
  ["重复定义次数", (m) => m.css.duplicateSelectorCount],
  ["重复选择器组数", (m) => m.css.duplicateSelectorGroups],
  [".topbar 定义次数", (m) => m.css.topbarDefinitions],
  ["断点数量", (m) => m.css.breakpointCount],
  ["零引用 token", (m) => m.tokens.zeroRefCount],
  ["JS 内联 style 属性", (m) => m.js.inlineStyleAttrs],
  ["JS style.* 写入", (m) => m.js.inlineStyleWrites],
  ["JS/HTML 颜色字面量", (m) => m.js.colorLiterals],
  ["CSS 字节数", (m) => m.files.stylesCssBytes],
  ["CSS gzip 字节数", (m) => m.files.stylesCssGzipBytes],
];

let failed = false;
const rows = [];
for (const [label, get] of metrics) {
  const before = get(baseline);
  const after = get(current);
  const status = after <= before ? "ok" : "REGRESSED";
  if (after > before) failed = true;
  rows.push({ label, before, after, delta: after - before, status });
}

const pad = (value, width) => String(value).padEnd(width);
process.stdout.write(
  `${pad("指标", 22)}${pad("基线", 10)}${pad("当前", 10)}${pad("变化", 10)}状态\n`,
);
for (const row of rows) {
  process.stdout.write(
    `${pad(row.label, 22)}${pad(row.before, 10)}${pad(row.after, 10)}${pad(
      row.delta > 0 ? `+${row.delta}` : row.delta,
      10,
    )}${row.status}\n`,
  );
}

if (failed) {
  process.stderr.write(
    "\n结构债预算回退：以上指标只允许下降或持平。要么收敛，要么先更新基线并说明原因。\n",
  );
  process.exit(1);
}
process.stdout.write("\n结构债预算通过：所有指标均未变差。\n");
