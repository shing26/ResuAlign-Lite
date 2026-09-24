/* ADR-0033 消费者视觉刷新 —— 静态契约回归测试。
 * 与 alignment-gap.test.mjs 同模式：直接读源码断言视觉刷新必须保留的
 * 契约（token 重映射 / 右侧抽屉 / 术语 / emoji→SVG / 缓存版本），
 * 防止后续重构静默回退已拍板的视觉决策。
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const staticDir = join(root, "src/resualign/static");
const appDir = join(staticDir, "app");

function readStatic(name) {
  return readFileSync(join(staticDir, name), "utf8");
}
function readApp(name) {
  return readFileSync(join(appDir, name), "utf8");
}

/* ------------------------------------------------------------------ */
/* 决策1 已被 ADR-0047 取代：冷青强调色，A4 纸恒白                  */
/* ------------------------------------------------------------------ */

test("styles.css canonical tokens use the cold-teal light accent", () => {
  const css = readStatic("styles.css");
  assert.match(css, /:root\s*\{[\s\S]*--accent:\s*#0E7C8F/i, "light accent = #0E7C8F");
  assert.match(css, /:root\s*\{[\s\S]*--accent-hover:\s*#0C6D7E/i, "light hover = #0C6D7E");
  assert.match(css, /:root\s*\{[\s\S]*--accent-soft:\s*#E2F3F6/i, "light soft = #E2F3F6");
  assert.match(css, /:root\s*\{[\s\S]*--bg-canvas:\s*#F7F8FA/i, "light canvas = #F7F8FA");
  assert.match(css, /html\.dark[\s\S]*--paper-bg:\s*#ffffff/i, "dark keeps A4 paper white");
});

test("index.html defaults to light theme (no hardcoded dark class)", () => {
  const html = readStatic("index.html");
  assert.doesNotMatch(html, /class="dark"/, "ADR-0033: default light, dark applied by theme.js");
});

/* ------------------------------------------------------------------ */
/* 决策5：投递快照右侧抽屉                                             */
/* ------------------------------------------------------------------ */

test("styles.css lays out snapshot as a right-side drawer", () => {
  const css = readStatic("styles.css");
  assert.match(css, /\.modal-backdrop\.modal--drawer\s*\{[^}]*justify-content:\s*flex-end/, "drawer backdrop anchors right");
  assert.match(css, /\.modal-backdrop\.modal--drawer \.modal\s*\{[^}]*width:\s*480px/, "drawer panel 480px");
  assert.match(css, /\.modal--drawer \.modal > h3\s*\{/, "drawer header");
  assert.match(css, /\.snapshot-drawer\s*\{/, "snapshot drawer body block");
  assert.match(css, /\.modal-close\s*\{/, "drawer close button styles");
});

test("events.js showModal accepts drawer options (className + close button)", () => {
  const src = readApp("events.js");
  assert.match(src, /export function showModal\(title, bodyHtml, options = \{\}\)/);
  assert.match(src, /options\.className/, "backdrop class hook");
  assert.match(src, /options\.closeBtn/, "close button hook");
  assert.match(src, /class="modal-close"/, "close button markup");
});

test("main.js opens snapshots and legacy drafts via the right drawer", () => {
  const src = readApp("main.js");
  assert.match(src, /"open-snapshot":[\s\S]*snapshotDrawerHtml/, "open-snapshot renders the drawer body");
  assert.match(src, /"open-snapshot":[\s\S]*`投递快照 · 第 \$\{snapshot\.version_index\} 版`/, "drawer header title uses 投递快照");
  assert.match(src, /"open-snapshot":[\s\S]*className: "modal--drawer"/, "open-snapshot uses drawer layout");
  assert.match(src, /"view-legacy-draft":[\s\S]*snapshotDrawerHtml/, "legacy draft uses the drawer body");
  assert.match(src, /"view-legacy-draft":[\s\S]*className: "modal--drawer"/, "legacy draft uses drawer layout");
});

/* ------------------------------------------------------------------ */
/* 决策7：全站唯一「投递快照」（无「投递定稿快照」自造词）            */
/* ------------------------------------------------------------------ */

test("UI copy uses the single term 投递快照", () => {
  const sources = [readApp("main.js"), readApp("format.js"), readApp("dashboard-view.js"), readApp("split-canvas.js")];
  for (const src of sources) {
    assert.doesNotMatch(src, /投递定稿快照/, "no 投递定稿快照 in UI copy");
  }
});

/* ------------------------------------------------------------------ */
/* 决策9：emoji → 16px SVG 线性图标                                    */
/* ------------------------------------------------------------------ */

test("UI templates no longer ship emoji glyphs (warning/check/cross)", () => {
  const sources = [readApp("main.js"), readApp("format.js"), readApp("events.js")];
  for (const src of sources) {
    assert.doesNotMatch(src, /\u26A0/, "no U+26A0 warning emoji");
    assert.doesNotMatch(src, /\u2713/, "no U+2713 check emoji");
    assert.doesNotMatch(src, /\u2717/, "no U+2717 cross emoji");
  }
  assert.match(readApp("format.js"), /icon\("check", 13\)/, "format.js uses the shared icon factory");
  assert.match(readApp("icons.js"), /<svg[^>]*class="\$\{classes\}"/, "linear SVG factory introduced");
});

/* ------------------------------------------------------------------ */
/* 静态缓存版本                                                        */
/* ------------------------------------------------------------------ */

test("index.html bumps static cache version to v=59", () => {
  const html = readStatic("index.html");
  assert.match(html, /\/static\/styles\.css\?v=59/);
  assert.match(html, /\/static\/app\/main\.js\?v=59/);
});
