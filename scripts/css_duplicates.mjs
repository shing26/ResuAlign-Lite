#!/usr/bin/env node
/* 重复选择器明细报告（结构债 Phase 2 施工用）
 *
 * 输出每个重复选择器的所有规则：行号 + 声明体，方便判断「哪条是主定义、
 * 哪些只是后续追加的润色块」。只读，不改文件。
 *
 * 用法：
 *   node scripts/css_duplicates.mjs                 # 全部重复组
 *   node scripts/css_duplicates.mjs .topbar select  # 只看指定选择器
 *   node scripts/css_duplicates.mjs --top 20        # 重复次数最多的 20 组
 */
import { readFileSync } from "node:fs";

const CSS_PATH = "src/resualign/static/styles.css";
const css = readFileSync(CSS_PATH, "utf8");
const args = process.argv.slice(2);
const topIndex = args.indexOf("--top");
const topOnly = topIndex >= 0 ? Number(args[topIndex + 1] || 20) : null;
const wanted = args.filter(
  (arg) => !arg.startsWith("--") && !(topIndex >= 0 && arg === args[topIndex + 1]),
);

/* 与 css_audit.mjs 相同的口径：去掉注释、取 `{` 前的 prelude。 */
const body = css.replace(/\/\*[\s\S]*?\*\//g, "");
const occurrences = new Map(); // selector -> [{ line, text }]
const preludeRegex = /([^{}]+)\{/g;
let match;
while ((match = preludeRegex.exec(body))) {
  const prelude = match[1].trim().replace(/\s+/g, " ");
  if (!prelude || prelude.startsWith("@")) continue;
  if (/^(?:from|to|\d{1,3}%)$/.test(prelude)) continue;
  const line = body.slice(0, match.index).split("\n").length;
  for (const raw of prelude.split(",")) {
    const selector = raw.trim();
    if (!selector) continue;
    // 规则体的起点：prelude 之后到下一个 `}` 之前
    const startBrace = match.index + match[0].length;
    const endBrace = body.indexOf("}", startBrace);
    const decls = body
      .slice(startBrace, endBrace)
      .split(";")
      .map((part) => part.trim().replace(/\s+/g, " "))
      .filter(Boolean);
    if (!occurrences.has(selector)) occurrences.set(selector, []);
    occurrences.get(selector).push({ line, decls });
  }
}

const groups = [...occurrences.entries()]
  .filter(([, list]) => list.length > 1)
  .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));

const selected = wanted.length
  ? groups.filter(([selector]) => wanted.includes(selector))
  : topOnly
    ? groups.slice(0, topOnly)
    : groups;

process.stdout.write(`# duplicate selector groups: ${groups.length}\n`);
for (const [selector, list] of selected) {
  process.stdout.write(`\n## ${selector}  (${list.length} definitions)\n`);
  for (const { line, decls } of list) {
    process.stdout.write(`  L${line}: ${decls.join("; ")}\n`);
  }
}
