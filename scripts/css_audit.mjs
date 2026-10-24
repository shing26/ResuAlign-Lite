#!/usr/bin/env node
/* CSS 结构债度量脚本（结构债项目 Phase 0）
 *
 * 只用 Node 标准库，无第三方依赖：给「重复选择器 / 零引用 token / 内联样式 /
 * 断点膨胀 / !important」这些只能靠人眼发现的问题一个可重复的计数口径，供
 * `scripts/css_budget.mjs` 做棘轮门禁（数字只能降不能升）。
 *
 * 用法：
 *   node scripts/css_audit.mjs                 # 打印 JSON 摘要
 *   node scripts/css_audit.mjs --write <path>  # 同时写基线 JSON
 *   node scripts/css_audit.mjs --pretty        # 缩进输出
 */
import { readFileSync, readdirSync, mkdirSync, writeFileSync } from "node:fs";
import { groupByContextSelector, parseRules } from "./css-rules.mjs";
import { gzipSync } from "node:zlib";
import { dirname, join } from "node:path";

const STATIC_DIR = "src/resualign/static";
const CSS_PATH = join(STATIC_DIR, "styles.css");
const HTML_PATH = join(STATIC_DIR, "index.html");
const APP_DIR = join(STATIC_DIR, "app");

const args = process.argv.slice(2);
const pretty = args.includes("--pretty");
const writeIndex = args.indexOf("--write");

/* 统一成 LF 再度量：Windows 检出会按 core.autocrlf 把工作区文件写成 CRLF，
 * 同一份内容在磁盘上会凭空多出「行数」个字节，让体积指标随 checkout 漂移。 */
const toLf = (text) => text.replace(/\r\n/g, "\n");
const css = toLf(readFileSync(CSS_PATH, "utf8"));
const html = toLf(readFileSync(HTML_PATH, "utf8"));
const appFiles = readdirSync(APP_DIR)
  .filter((name) => name.endsWith(".js"))
  .map((name) => ({ name, text: toLf(readFileSync(join(APP_DIR, name), "utf8")) }));
const jsText = appFiles.map((file) => file.text).join("\n");

const stripComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const cssBody = stripComments(css);

/** 提取所有规则块的 prelude（`{` 前的那段选择器/at-rule 文本）。 */
function rulePreludes(text) {
  const out = [];
  const regex = /([^{}]+)\{/g;
  let match;
  while ((match = regex.exec(text))) {
    const prelude = match[1].trim().replace(/\s+/g, " ");
    if (prelude) out.push(prelude);
  }
  return out;
}

function isAtRule(prelude) {
  return prelude.startsWith("@");
}

const preludes = rulePreludes(cssBody);
/* @keyframes 的 from/to/百分比是帧步而不是选择器，别算进「重复选择器」。 */
const isKeyframeStep = (prelude) =>
  /^(?:from|to|\d{1,3}%)$/.test(prelude) ||
  /^(?:from|to|\d{1,3}%),/.test(prelude);
const rulePreludesOnly = preludes.filter(
  (p) => !isAtRule(p) && !isKeyframeStep(p),
);

/* 选择器重复度：只统计「同上下文（同 @layer + 同 @media 链）内的重复定义」。
 * 跨上下文的同名选择器（如桌面规则 + @media 内覆盖）是合法的响应式写法，
 * 不算结构债；把它们算进去只会得到虚高的数字。 */
const parsedRules = parseRules(css);
const contextGroups = groupByContextSelector(parsedRules);
const duplicateGroups = [...contextGroups.values()].filter(
  (group) => group.length > 1,
);
const duplicateSelectorCount = duplicateGroups.reduce(
  (sum, group) => sum + (group.length - 1),
  0,
);
const duplicateSelectorGroups = duplicateGroups.length;
const duplicateSelectorsTop20 = duplicateGroups
  .map((group) => [group[0].selector, group.length])
  .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
  .slice(0, 20);

/* 断点：所有 @media 的条件，按出现次数排序。 */
const mediaCounts = new Map();
for (const match of cssBody.matchAll(/@media\s*([^{]+)\{/g)) {
  const condition = match[1].trim().replace(/\s+/g, " ");
  mediaCounts.set(condition, (mediaCounts.get(condition) || 0) + 1);
}
const breakpoints = [...mediaCounts.entries()].sort(
  (a, b) => b[1] - a[1] || a[0].localeCompare(b[0]),
);

/* token：定义 vs 引用（CSS 的 var() + JS 里出现的 --token 字符串）。 */
/* 只认「行首的自定义属性声明」：`.dashboard-kpi--teal::before` 这类修饰类名
 * 里的 `--teal::` 不是 token 定义（之前用宽松正则会把它们算进 token 总数）。 */
const definedTokens = new Set(
  [...cssBody.matchAll(/^[ \t]*(--[\w-]+)[ \t]*:/gm)].map((m) => m[1]),
);
/* 「被引用」只认真正的消费点：CSS var()、JS/HTML 里的 var()、以及运行时
 * getPropertyValue/setProperty。裸的 `--token` 字样（注释、文档字符串）不算，
 * 否则一个只在注释里被提到的 token 会假装「有人用」，与 G6 的口径也不一致。 */
const referencedTokens = new Set([
  ...[...cssBody.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]),
  ...[...jsText.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]),
  ...[...jsText.matchAll(/getPropertyValue\(\s*["'`](--[\w-]+)/g)].map((m) => m[1]),
  ...[...jsText.matchAll(/setProperty\(\s*["'`](--[\w-]+)/g)].map((m) => m[1]),
  ...[...html.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]),
]);
const zeroRefTokens = [...definedTokens]
  .filter((name) => !referencedTokens.has(name))
  .sort();

/* JS / HTML 里的内联样式与颜色字面量。 */
/* Phase 3 口径：style="--x: …"（运行时注入自定义属性，CSS 消费）是受认可的
 * 动态样式通道，不计违规；只有携带常规 CSS 属性的 style=" 才算。 */
const inlineStyleAttrs =
  (jsText.match(/style="(?!--)/g) || []).length +
  (html.match(/style="(?!--)/g) || []).length;
const inlineStyleWrites =
  (jsText.match(/\.style\.(?!setProperty|removeProperty)[a-zA-Z]+/g) || []).length;
const stripJsComments = (text) => text.replace(/\/\*[\s\S]*?\*\//g, "");
const colorLiteralRe = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)/g;
const colorLiterals =
  (stripJsComments(jsText).match(colorLiteralRe) || []).length +
  (stripJsComments(html).match(colorLiteralRe) || []).length;
const importantCount = (cssBody.match(/!important/g) || []).length;

/* Tailwind 遗留工具类（index.html 里 body/壳层还在用的原子类）。 */
/* 只认真正的 Tailwind 原子类（带任意值括号 / 斜杠透明度 / 已知工具类名），
 * 避免把 .gap-row / .select-all 这类项目自定义 class 误算进来。 */
const tailwindClasses = new Set();
for (const match of (html + jsText).matchAll(
  /\b(?:bg-appbg|text-white\/\d+|h-screen|min-h-screen|flex-1|flex-col|flex-wrap|items-center|justify-between|overflow-hidden|overflow-y-auto|space-[xy]-\d+|select-none)\b|\btext-\[[^\]]+\]/g,
)) {
  tailwindClasses.add(match[0]);
}

const cssBytes = Buffer.byteLength(css);
const cssGzipBytes = gzipSync(css).length;

const metrics = {
  generatedAt: new Date().toISOString(),
  files: {
    stylesCssBytes: cssBytes,
    stylesCssGzipBytes: cssGzipBytes,
    appJsFiles: appFiles.length,
  },
  css: {
    ruleBlocks: rulePreludesOnly.length,
    atRuleBlocks: preludes.length - rulePreludesOnly.length,
    selectorCount: new Set(parsedRules.map((rule) => rule.selector)).size,
    duplicateSelectorCount,
    duplicateSelectorGroups,
    duplicateSelectorsTop20,
    topbarDefinitions: parsedRules.filter((rule) => rule.selector === ".topbar").length,
    importantCount,
    breakpointCount: breakpoints.length,
    breakpoints,
  },
  tokens: {
    definedCount: definedTokens.size,
    referencedCount: referencedTokens.size,
    zeroRefCount: zeroRefTokens.length,
    zeroRefTokens,
  },
  js: {
    inlineStyleAttrs,
    inlineStyleWrites,
    colorLiterals,
    tailwindUtilityClasses: [...tailwindClasses].sort(),
    tailwindUtilityClassCount: tailwindClasses.size,
  },
};

const serialized = JSON.stringify(metrics, null, pretty ? 2 : 0);
if (writeIndex >= 0 && args[writeIndex + 1]) {
  const outPath = args[writeIndex + 1];
  mkdirSync(dirname(outPath), { recursive: true });
  writeFileSync(outPath, `${JSON.stringify(metrics, null, 2)}\n`, "utf8");
  process.stderr.write(`baseline written: ${outPath}\n`);
}
process.stdout.write(`${serialized}\n`);
